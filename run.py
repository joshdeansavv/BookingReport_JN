#!/usr/bin/env python3
import os, io, shutil, re, json, requests
import fitz, pdfplumber
from PIL import Image

WEBHOOK = "https://discord.com/api/webhooks/1412169034106929257/_VTUSe1FnH-lg_XqfLaR2lH-fd6-PKU2Myu7LAKp7FdVKFALcj7zRVSBG87SWo3R_3uR"
SRC = "new"
DST = "archive"
GREY = 8421504

name_row = re.compile(
    r"^(?P<name>[A-Z ,'\-]+)\s+(?P<booked>\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}:\d{2}\s+[AP]M)\s+"
    r"(?P<dob>\d{1,2}/\d{1,2}/\d{4})\s+(?P<gender>[A-Z]+)\s+(?P<brought>.+)$"
)

def post_embed(record, image_bytes):
    desc = (
        f"Booking: {record['booked']}\nDOB: {record['dob']}\nGender: {record['gender']}\n"
        f"Arrestor: {record['brought']}\nCharges:\n" + ("\n".join(record['charges']) or "None")
    )
    embed = {"title": record['name'], "description": desc, "color": GREY}
    payload = {"embeds": [embed]}
    data = {"payload_json": json.dumps(payload)}
    files = {}
    if image_bytes:
        files["file"] = ("mug.png", image_bytes, "image/png")
        embed["thumbnail"] = {"url": "attachment://mug.png"}
        data = {"payload_json": json.dumps({"embeds": [embed]})}
    try:
        r = requests.post(WEBHOOK, data=data, files=files or None, timeout=30)
        print("POST", record['name'], getattr(r, "status_code", None))
    except Exception as e:
        print("POST ERROR", record.get("name"), e)

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
            for rec, img in recs:
                post_embed(rec, img)
        except Exception as e:
            print("FAILED", f, e)
        try:
            shutil.move(path, os.path.join(DST, f))
            print("Archived", f)
        except Exception as e:
            print("Archive move failed", f, e)

if __name__ == "__main__":
    main()