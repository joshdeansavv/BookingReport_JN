#!/usr/bin/env python3
import os, io, shutil, re, sqlite3
import fitz, pdfplumber
from PIL import Image

SRC = "archive"
DST = "archive"  # Keep processed files in archive
DB_FILE = "jail_records.db"

name_row = re.compile(
    r"^(?P<name>[A-Z ,'\-]+)\s+(?P<booked>\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}:\d{2}\s+[AP]M)\s+"
    r"(?P<dob>\d{1,2}/\d{1,2}/\d{4})\s+(?P<gender>[A-Z]+)\s+(?P<brought>.+)$"
)

def parse_name(full_name):
    """Parse full name into first, middle, last name components"""
    # Remove commas and clean up the name
    clean_name = full_name.strip().replace(',', '').strip()
    name_parts = clean_name.split()
    
    if len(name_parts) == 1:
        return name_parts[0], "", ""
    elif len(name_parts) == 2:
        return name_parts[0], "", name_parts[1]
    else:
        # First name, middle names, last name
        return name_parts[0], " ".join(name_parts[1:-1]), name_parts[-1]

def create_database():
    """Create SQLite database and table for jail records"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Create table for jail records
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS jail_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            first_name TEXT,
            middle_name TEXT,
            last_name TEXT,
            booking_date TEXT,
            date_of_birth TEXT,
            gender TEXT,
            arrestor TEXT,
            charges TEXT,
            image_data BLOB,
            source_pdf TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()
    print(f"Database created/verified: {DB_FILE}")

def save_records_to_database(records_with_images, pdf_filename):
    """Save all records from a PDF to SQLite database"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    for record, image_bytes in records_with_images:
        # Parse name components
        first_name, middle_name, last_name = parse_name(record['name'])
        
        # Prepare data
        charges_text = "; ".join(record['charges']) if record['charges'] else "None"
        
        # Clean up data
        booking_date = record['booked'].strip()
        dob = record['dob'].strip()
        gender = record['gender'].strip()
        arrestor = record['brought'].strip()
        
        # Insert record into database
        cursor.execute('''
            INSERT INTO jail_records 
            (first_name, middle_name, last_name, booking_date, date_of_birth, 
             gender, arrestor, charges, image_data, source_pdf)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (first_name, middle_name, last_name, booking_date, dob, 
              gender, arrestor, charges_text, image_bytes, pdf_filename))
    
    conn.commit()
    conn.close()
    print(f"Saved {len(records_with_images)} records to database from {pdf_filename}")

def extract_records(pdf_path):
    out = []
    with pdfplumber.open(pdf_path) as pp, fitz.open(pdf_path) as doc:
        for pidx, page_pp in enumerate(pp.pages):
            words = page_pp.extract_words()
            lines = []
            if words:
                cur_top = None
                bucket = []
                for w in words:
                    if cur_top is None:
                        cur_top = w['top']
                    if abs(w['top'] - cur_top) <= 3:
                        bucket.append(w)
                    else:
                        lines.append((" ".join(x['text'] for x in bucket).strip(), cur_top))
                        bucket = [w]
                        cur_top = w['top']
                if bucket:
                    lines.append((" ".join(x['text'] for x in bucket).strip(), cur_top))
            else:
                raw = page_pp.extract_text() or ""
                lines = [(l, 0) for l in raw.splitlines()]

            page_img_regions = []
            full_img = None
            try:
                full_pix = doc[pidx].get_pixmap(matrix=fitz.Matrix(2,2))
                full_img = Image.open(io.BytesIO(full_pix.tobytes("png")))
                scale_y = full_img.height / page_pp.height if page_pp.height else 1.0
            except Exception:
                full_img = None
                scale_y = 1.0

            for im in (page_pp.images or []):
                try:
                    x0 = int(im.get("x0", 0))
                    top = int(im.get("top", 0))
                    x1 = int(im.get("x1", 0))
                    bottom = int(im.get("bottom", 0))
                    if full_img and x1 > x0 and bottom > top:
                        sx = full_img.width / page_pp.width if page_pp.width else 1.0
                        sy = full_img.height / page_pp.height if page_pp.height else 1.0
                        
                        # Skip header images (usually at top of page, small, or logo-like)
                        img_height = (bottom - top) * sy
                        img_width = (x1 - x0) * sx
                        
                        # Skip images that are too small (likely logos/headers)
                        if img_height < 50 or img_width < 50:
                            continue
                            
                        # Skip images at the very top of the page (headers)
                        if top * sy < 100:
                            continue
                            
                        crop = full_img.crop((int(x0 * sx), int(top * sy), int(x1 * sx), int(bottom * sy)))
                        buf = io.BytesIO()
                        crop.save(buf, "PNG")
                        buf.seek(0)
                        page_img_regions.append({"mid_y": (top + bottom) * 0.5 * sy, "bytes": buf.getvalue()})
                except Exception:
                    continue

            # If no images found with coordinates, try fitz method
            if not page_img_regions:
                imgs = doc[pidx].get_images(full=True) or []
                seq = []
                for im in imgs:
                    try:
                        xref = im[0]
                        pix = fitz.Pixmap(doc, xref)
                        if pix.n - pix.alpha < 4:
                            imgbytes = pix.tobytes("png")
                        else:
                            pix = fitz.Pixmap(fitz.csRGB, pix)
                            imgbytes = pix.tobytes("png")
                        seq.append(imgbytes)
                    except Exception:
                        continue
                for b in seq:
                    page_img_regions.append({"mid_y": None, "bytes": b})
            
            # If we still have no images, try extracting all images from the page
            if not page_img_regions:
                try:
                    # Get all images from the page using fitz
                    image_list = doc[pidx].get_images()
                    for img_index, img in enumerate(image_list):
                        try:
                            xref = img[0]
                            pix = fitz.Pixmap(doc, xref)
                            if pix.n - pix.alpha < 4:
                                imgbytes = pix.tobytes("png")
                            else:
                                pix = fitz.Pixmap(fitz.csRGB, pix)
                                imgbytes = pix.tobytes("png")
                            page_img_regions.append({"mid_y": None, "bytes": imgbytes})
                        except Exception:
                            continue
                except Exception:
                    pass

            name_entries = []
            for idx, (text, top) in enumerate(lines):
                m = name_row.match(text)
                if m:
                    rec = m.groupdict()
                    rec['charges'] = []
                    j = idx + 1
                    while j < len(lines) and not name_row.match(lines[j][0]):
                        ln = lines[j][0].strip()
                        if ln:
                            # Skip address lines (start with numbers and contain street indicators)
                            if re.match(r'^\d+.*(AVE|ST|RD|DR|BLVD|WAY|CT|PL|LN|CIR)', ln, re.IGNORECASE):
                                j += 1
                                continue
                            # Skip "Charge Description" header
                            if ln.startswith("Charge Description"):
                                j += 1
                                continue
                            # Skip page numbers
                            if ln.startswith("Page ") and " of " in ln:
                                j += 1
                                continue
                            # Skip empty lines or just whitespace
                            if not ln or ln.isspace():
                                j += 1
                                continue
                            # Add actual charge lines (start with "State")
                            if ln.startswith("State "):
                                rec['charges'].append(ln)
                        j += 1
                    name_entries.append({"rec": rec, "top": top})

            if not name_entries:
                continue

            if all(r["mid_y"] is not None for r in page_img_regions):
                name_entries.sort(key=lambda x: x["top"])
                page_img_regions.sort(key=lambda x: x["mid_y"])
                
                # Create a list to track which images have been used
                used_images = set()
                
                for ne in name_entries:
                    # Find image closest to this name entry that hasn't been used
                    best_img = None
                    min_distance = float('inf')
                    best_img_index = -1
                    
                    for i, img_region in enumerate(page_img_regions):
                        if i in used_images:
                            continue
                        # Calculate distance between image center and name position
                        distance = abs(img_region["mid_y"] - ne["top"])
                        if distance < min_distance:
                            min_distance = distance
                            best_img = img_region
                            best_img_index = i
                    
                    # Mark this image as used
                    if best_img_index >= 0:
                        used_images.add(best_img_index)
                    
                    img_bytes = best_img["bytes"] if best_img else None
                    out.append((ne["rec"], img_bytes))
            else:
                imgs_seq = [r["bytes"] for r in page_img_regions]
                for i, ne in enumerate(name_entries):
                    img = imgs_seq[i] if i < len(imgs_seq) else None
                    out.append((ne["rec"], img))
    return out

def main():
    # Create database first
    create_database()
    
    if not os.path.isdir(SRC):
        print("Missing", SRC); return
    files = sorted([f for f in os.listdir(SRC) if f.lower().endswith(".pdf")])
    if not files:
        print("No PDFs in", SRC); return
    for f in files:
        path = os.path.join(SRC, f)
        print("Process", f)
        try:
            recs = extract_records(path)
            print("Records", len(recs))
            if recs:
                save_records_to_database(recs, f)
        except Exception as e:
            print("FAILED", f, e)
        # Don't move files since we're processing from archive
        print("Processed", f)

if __name__ == "__main__":
    main()
