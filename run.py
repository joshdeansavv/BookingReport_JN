#!/usr/bin/env python3
import os, io, shutil, re, json, requests, time
import fitz, pdfplumber
from PIL import Image

WEBHOOK = "https://discord.com/api/webhooks/1412189613895717006/dzrqjw254DWOeTO_LOupunCEQ541iBunVNe4i1ckjL-WAJdiktzz5ftJ8v1xmPu_XKxR"
SRC = "new"
DST = "archive"
GREY = 0x1f1f1f

# Discord rate limits: 30 messages per minute, 50 requests per second
MESSAGES_PER_MINUTE = 30
REQUESTS_PER_SECOND = 50
MIN_DELAY_BETWEEN_MESSAGES = 5  # TEMPORARY: 5 seconds between messages
MIN_DELAY_BETWEEN_REQUESTS = 1 / REQUESTS_PER_SECOND   # 0.02 seconds

last_message_time = 0
last_request_time = 0

name_row = re.compile(
    r"^(?P<name>[A-Z ,'\-]+)\s+(?P<booked>\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}:\d{2}\s+[AP]M)\s+"
    r"(?P<dob>\d{1,2}/\d{1,2}/\d{4})\s+(?P<gender>[A-Z]+)\s+(?P<brought>.+)$"
)

def rate_limit():
    """Ensure we don't exceed Discord's rate limits"""
    global last_message_time, last_request_time
    current_time = time.time()
    
    # Check message rate limit (30 per minute)
    time_since_last_message = current_time - last_message_time
    if time_since_last_message < MIN_DELAY_BETWEEN_MESSAGES:
        sleep_time = MIN_DELAY_BETWEEN_MESSAGES - time_since_last_message
        print(f"Rate limiting: sleeping {sleep_time:.1f}s")
        time.sleep(sleep_time)
    
    # Check request rate limit (50 per second)
    time_since_last_request = current_time - last_request_time
    if time_since_last_request < MIN_DELAY_BETWEEN_REQUESTS:
        sleep_time = MIN_DELAY_BETWEEN_REQUESTS - time_since_last_request
        time.sleep(sleep_time)
    
    last_message_time = time.time()
    last_request_time = time.time()

def post_embed(record, image_bytes):
    # Apply rate limiting before making the request
    rate_limit()
    
    desc = (
        f"**Booking:** {record['booked']}\n**DOB:** {record['dob']}\n**Gender:** {record['gender']}\n"
        f"**Arrestor:** {record['brought']}\n**Charges:**\n" + ("\n".join(record['charges']) or "None")
    )
    
    # Create embed with large thumbnail at top right
    embed = {"title": record['name'], "description": desc, "color": GREY}
    if image_bytes and image_bytes is not None:
        embed["thumbnail"] = {"url": "attachment://mug.png"}
    
    payload = {"embeds": [embed]}
    data = {"payload_json": json.dumps(payload)}
    files = {}
    if image_bytes and image_bytes is not None:
        files["file"] = ("mug.png", image_bytes, "image/png")
    
    try:
        r = requests.post(WEBHOOK, data=data, files=files or None, timeout=30)
        print("POST", record['name'], getattr(r, "status_code", None))
    except Exception as e:
        print("POST ERROR", record.get("name"), e)

def post_date_embed(filename):
    """Send a date embed to show which document is being processed"""
    # Apply rate limiting before making the request
    rate_limit()
    
    # Extract date from filename like "Mesa County Jail Records (3) 2025-08-28.pdf"
    import re
    date_match = re.search(r'(\d{4}-\d{2}-\d{2})', filename)
    if date_match:
        date_str = date_match.group(1)
        # Convert to friendly format
        from datetime import datetime
        try:
            date_obj = datetime.strptime(date_str, '%Y-%m-%d')
            friendly_date = date_obj.strftime('%A, %B %d, %Y')
        except:
            friendly_date = date_str
    else:
        friendly_date = "Unknown Date"
    
    embed = {
        "title": "📅 Processing Document",
        "description": f"**Date:** {friendly_date}\n**File:** {filename}",
        "color": 0x00ff00  # Green color for date embeds
    }
    
    payload = {"embeds": [embed]}
    data = {"payload_json": json.dumps(payload)}
    
    try:
        r = requests.post(WEBHOOK, data=data, timeout=30)
        print("DATE POST", friendly_date, getattr(r, "status_code", None))
    except Exception as e:
        print("DATE POST ERROR", e)

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
                        img_bytes = buf.getvalue()
                        
                        # Validate the image bytes before adding
                        if img_bytes and len(img_bytes) > 100:  # Basic validation
                            page_img_regions.append({"mid_y": (top + bottom) * 0.5, "bytes": img_bytes})
                        else:
                            # Add placeholder for invalid/broken image
                            page_img_regions.append({"mid_y": (top + bottom) * 0.5, "bytes": None})
                except Exception:
                    # Add placeholder for failed extraction to maintain alignment
                    # We need to estimate position for failed extractions
                    try:
                        x0 = int(im.get("x0", 0))
                        top = int(im.get("top", 0))
                        x1 = int(im.get("x1", 0))
                        bottom = int(im.get("bottom", 0))
                        if x1 > x0 and bottom > top:
                            page_img_regions.append({"mid_y": (top + bottom) * 0.5, "bytes": None})
                    except:
                        # If we can't even get position, skip this image entirely
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
                        # Validate the image bytes before adding
                        if imgbytes and len(imgbytes) > 100:  # Basic validation
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
                            # Validate the image bytes before adding
                            if imgbytes and len(imgbytes) > 100:  # Basic validation
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

            # Use optimal matching - find the best global assignment
            name_entries.sort(key=lambda x: x["top"])
            page_img_regions.sort(key=lambda x: x["mid_y"] if x["mid_y"] is not None else float('inf'))
            
            # Create distance matrix for all name-image pairs
            distances = []
            for i, ne in enumerate(name_entries):
                for j, img_region in enumerate(page_img_regions):
                    if img_region["mid_y"] is not None:
                        distance = abs(img_region["mid_y"] - ne["top"])
                    else:
                        distance = float('inf')
                    distances.append((distance, i, j))
            
            # Sort by distance to get optimal assignments
            distances.sort()
            
            # Track which names and images have been assigned
            assigned_names = set()
            assigned_images = set()
            
            # Assign images to names in order of best distance
            for distance, name_idx, img_idx in distances:
                if name_idx not in assigned_names and img_idx not in assigned_images:
                    if distance < 200:  # Only assign if reasonably close
                        assigned_names.add(name_idx)
                        assigned_images.add(img_idx)
            
            # Create results in original order
            for i, ne in enumerate(name_entries):
                if i in assigned_names:
                    # Find which image was assigned to this name
                    for distance, name_idx, img_idx in distances:
                        if name_idx == i and img_idx in assigned_images:
                            img_bytes = page_img_regions[img_idx]["bytes"]
                            break
                    else:
                        img_bytes = None
                else:
                    img_bytes = None
                
                out.append((ne["rec"], img_bytes))
    return out

def main():
    if not os.path.isdir(SRC):
        print("Missing", SRC); return
    files = sorted([f for f in os.listdir(SRC) if f.lower().endswith(".pdf")])
    if not files:
        print("No PDFs in", SRC); return
    
    for i, f in enumerate(files):
        path = os.path.join(SRC, f)
        print("Process", f)
        
        # Send date embed before processing each document
        post_date_embed(f)
        
        try:
            recs = extract_records(path)
            print("Records", len(recs))
            for rec, img in recs:
                post_embed(rec, img)
        except Exception as e:
            print("FAILED", f, e)
        try:
            shutil.move(path, os.path.join(DST, f))
            print("Archived", f)
        except Exception as e:
            print("Archive move failed", f, e)
        
        # TEMPORARY: 5 second delay between documents
        if i < len(files) - 1:  # Don't delay after the last document
            print("Waiting 5 seconds before next document...")
            time.sleep(5)

if __name__ == "__main__":
    main()