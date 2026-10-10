import re

def patch_scanner():
    scanner_path = r"c:\Users\pmitchell\.gemini\antigravity\scratch\picCurator-Studio-Workspace\scanner.py"
    with open(scanner_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Make sure IptcImagePlugin is imported
    if "from PIL import Image" in content and "IptcImagePlugin" not in content:
        content = content.replace("from PIL import Image", "from PIL import Image, IptcImagePlugin")

    old_read_func = r"def read_image_metadata\(path: Path\) -> dict:.*?return metadata"
    
    new_read_func = r"""def read_image_metadata(path: Path) -> dict:
    metadata = {"tags": [], "description": "", "date": ""}
    if not path.exists(): return metadata
    tags = set()
    description = ""
    date = ""
    
    def decode_if_bytes(v):
        if isinstance(v, bytes):
            return v.decode("utf-8", errors="ignore").rstrip("\x00")
        return str(v).strip()

    try:
        with Image.open(path) as img:
            iptc = IptcImagePlugin.getiptcinfo(img) if hasattr(IptcImagePlugin, 'getiptcinfo') else None
            if iptc:
                if (2, 120) in iptc and not description:
                    val = iptc[(2, 120)]
                    description = decode_if_bytes(val[0]) if isinstance(val, list) and val else decode_if_bytes(val)
                if (2, 55) in iptc and not date:
                    val = iptc[(2, 55)]
                    date = decode_if_bytes(val[0]) if isinstance(val, list) and val else decode_if_bytes(val)

            exif = img.getexif()
            exif_ifd = exif.get_ifd(EXIF_IFD_POINTER)
            
            if not description:
                raw_xp_comment = exif.get(TAG_XP_COMMENT)
                if isinstance(raw_xp_comment, bytes):
                    description = raw_xp_comment.decode("utf-16le", errors="ignore").rstrip("\x00")
                elif raw_xp_comment:
                    description = str(raw_xp_comment).strip()
            
            if not description and TAG_USER_COMMENT in exif_ifd:
                user_comment = exif_ifd[TAG_USER_COMMENT]
                if isinstance(user_comment, bytes):
                    if user_comment.startswith(b"UNICODE\x00"):
                        description = user_comment[8:].decode("utf-16le", errors="ignore").rstrip("\x00")
                    elif user_comment.startswith(b"ASCII\x00\x00\x00"):
                        description = user_comment[8:].decode("ascii", errors="ignore").rstrip("\x00")
                    else:
                        description = user_comment.decode("utf-8", errors="ignore").rstrip("\x00")
                elif user_comment:
                    description = str(user_comment).strip()
                    
            if not description and TAG_IMAGE_DESC in exif:
                raw_desc = exif.get(TAG_IMAGE_DESC)
                if isinstance(raw_desc, bytes):
                    description = raw_desc.decode("utf-8", errors="ignore").rstrip("\x00")
                elif raw_desc:
                    description = str(raw_desc).strip()
            
            if not date:
                if TAG_DATETIME_ORIGINAL in exif_ifd:
                    date = decode_if_bytes(exif_ifd[TAG_DATETIME_ORIGINAL])
                elif TAG_CREATE_DATE in exif_ifd:
                    date = decode_if_bytes(exif_ifd[TAG_CREATE_DATE])
                elif TAG_MODIFY_DATE in exif:
                    date = decode_if_bytes(exif[TAG_MODIFY_DATE])
            
            raw_xp = exif.get(TAG_XP_KEYWORDS)
            if isinstance(raw_xp, bytes):
                decoded = raw_xp.decode("utf-16le", errors="ignore").rstrip("\x00")
                for t in decoded.split(";"):
                    t_clean = t.strip()
                    if t_clean: tags.add(t_clean)
            elif raw_xp:
                for t in str(raw_xp).split(";"):
                    t_clean = t.strip()
                    if t_clean: tags.add(t_clean)

            if TAG_IMAGE_DESC in exif:
                raw_desc = exif.get(TAG_IMAGE_DESC)
                if isinstance(raw_desc, bytes):
                    decoded = raw_desc.decode("utf-8", errors="ignore").rstrip("\x00")
                    for t in decoded.replace(";", ",").split(","):
                        t_clean = t.strip()
                        if t_clean: tags.add(t_clean)
                elif raw_desc:
                    for t in str(raw_desc).replace(";", ",").split(","):
                        t_clean = t.strip()
                        if t_clean: tags.add(t_clean)

            for xmp_key in ("xmp", "XML:com.adobe.xmp"):
                if xmp_key in img.info:
                    raw_xmp = img.info[xmp_key]
                    if isinstance(raw_xmp, bytes): raw_xmp = raw_xmp.decode("utf-8", errors="ignore")
                    if isinstance(raw_xmp, str):
                        for match in re.findall(r"<rdf:li[^>]*>(.*?)</rdf:li>", raw_xmp, re.IGNORECASE):
                            t_clean = match.strip()
                            if t_clean: tags.add(t_clean)
                        if not description:
                            desc_match = re.search(r"<dc:description>.*?<rdf:li[^>]*>(.*?)</rdf:li>.*?</dc:description>", raw_xmp, re.IGNORECASE | re.DOTALL)
                            if desc_match:
                                description = desc_match.group(1).strip()
                            else:
                                desc_match = re.search(r"dc:description=[\"'](.*?)[\"']", raw_xmp, re.IGNORECASE)
                                if desc_match: description = desc_match.group(1).strip()
                        if not date:
                            date_match = re.search(r"<photoshop:DateCreated>(.*?)</photoshop:DateCreated>", raw_xmp, re.IGNORECASE)
                            if date_match: 
                                date = date_match.group(1).strip()
                            else:
                                date_match = re.search(r"photoshop:DateCreated=[\"'](.*?)[\"']", raw_xmp, re.IGNORECASE)
                                if date_match: date = date_match.group(1).strip()
                                else:
                                    date_match = re.search(r"exif:DateTimeOriginal=[\"'](.*?)[\"']", raw_xmp, re.IGNORECASE)
                                    if date_match: date = date_match.group(1).strip()
                                    else:
                                        date_match = re.search(r"<exif:DateTimeOriginal>(.*?)</exif:DateTimeOriginal>", raw_xmp, re.IGNORECASE)
                                        if date_match: date = date_match.group(1).strip()
    except Exception as e:
        print(f"Error reading metadata from {path}: {e}")
        pass
    
    filtered_tags = [t for t in tags if t != description and t != ""]
    metadata["tags"] = sorted(filtered_tags)
    metadata["description"] = description
    metadata["date"] = date
    return metadata"""
    
    def repl(m): return new_read_func
    content = re.sub(old_read_func, repl, content, flags=re.MULTILINE|re.DOTALL)

    with open(scanner_path, "w", encoding="utf-8") as f:
        f.write(content)

patch_scanner()
print("Scanner patched for robust reading")
