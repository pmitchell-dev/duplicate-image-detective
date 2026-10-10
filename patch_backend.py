import os
import re

def patch_scanner():
    scanner_path = r"c:\Users\pmitchell\.gemini\antigravity\scratch\picCurator-Studio-Workspace\scanner.py"
    with open(scanner_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    new_tags = """TAG_XP_KEYWORDS  = 0x9C9E   # Windows XP/File Explorer Tags
TAG_XP_COMMENT   = 0x9C9C   # Windows XP Comment
TAG_IMAGE_DESC   = 0x010E   # Standard EXIF ImageDescription
TAG_MODIFY_DATE  = 0x0132   # ModifyDate
EXIF_IFD_POINTER = 0x8769

# ExifIFD tags
TAG_USER_COMMENT = 0x9286
TAG_DATETIME_ORIGINAL = 0x9003
TAG_CREATE_DATE = 0x9004
"""
    content = re.sub(
        r"TAG_XP_KEYWORDS  = 0x9C9E.*?\nTAG_IMAGE_DESC   = 0x010E.*?\nTAG_USER_COMMENT = 0x9286.*?\n",
        new_tags,
        content,
        flags=re.MULTILINE|re.DOTALL
    )

    old_build_xmp = r"def build_immich_xmp_bytes\(flat_tags: list\[str\], hierarchical_tags: list\[str\]\) -> bytes:.*?return xmp_str\.encode\(\"utf-8\"\)"
    
    # We will just write a function to construct it to avoid regex escape issues.
    new_build_xmp = r"""def build_immich_xmp_bytes(flat_tags: list[str], hierarchical_tags: list[str], description: str = "", date: str = "") -> bytes:
    dc_items = "".join(f"<rdf:li>{t}</rdf:li>" for t in flat_tags)
    lr_items = "".join(f"<rdf:li>{t}</rdf:li>" for t in hierarchical_tags)
    digi_items = "".join(f"<rdf:li>{t}</rdf:li>" for t in hierarchical_tags)

    desc_xml = f'<dc:description><rdf:Alt><rdf:li xml:lang="x-default">{description}</rdf:li></rdf:Alt></dc:description>' if description else ""
    date_xml = f"<photoshop:DateCreated>{date}</photoshop:DateCreated>" if date else ""

    xmp_str = f'<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>\n' \
'<x:xmpmeta xmlns:x="adobe:ns:meta/">\n' \
' <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n' \
'  <rdf:Description rdf:about=""\n' \
'    xmlns:dc="http://purl.org/dc/elements/1.1/"\n' \
'    xmlns:lr="http://ns.adobe.com/lightroom/1.0/"\n' \
'    xmlns:digiKam="http://www.digikam.org/ns/1.0/"\n' \
'    xmlns:photoshop="http://ns.adobe.com/photoshop/1.0/">\n' \
f'   {desc_xml}\n' \
f'   {date_xml}\n' \
'   <dc:subject>\n' \
'    <rdf:Bag>\n' \
f'     {dc_items}\n' \
'    </rdf:Bag>\n' \
'   </dc:subject>\n' \
'   <lr:HierarchicalSubject>\n' \
'    <rdf:Bag>\n' \
f'     {lr_items}\n' \
'    </rdf:Bag>\n' \
'   </lr:HierarchicalSubject>\n' \
'   <digiKam:TagsList>\n' \
'    <rdf:Seq>\n' \
f'     {digi_items}\n' \
'    </rdf:Seq>\n' \
'   </digiKam:TagsList>\n' \
'  </rdf:Description>\n' \
' </rdf:RDF>\n' \
'</x:xmpmeta>\n' \
'<?xpacket end="w"?>'
    return xmp_str.encode("utf-8")"""

    def repl(m):
        return new_build_xmp
    content = re.sub(old_build_xmp, repl, content, flags=re.MULTILINE|re.DOTALL)

    new_metadata_funcs = r"""

def read_image_metadata(path: Path) -> dict:
    metadata = {"tags": [], "description": "", "date": ""}
    if not path.exists(): return metadata
    tags = set()
    description = ""
    date = ""
    try:
        with Image.open(path) as img:
            exif = img.getexif()
            
            raw_xp_comment = exif.get(TAG_XP_COMMENT)
            if isinstance(raw_xp_comment, bytes):
                description = raw_xp_comment.decode("utf-16le", errors="ignore").rstrip("\x00")
            elif isinstance(raw_xp_comment, str):
                description = raw_xp_comment
            
            exif_ifd = exif.get_ifd(EXIF_IFD_POINTER)
            if not description and TAG_USER_COMMENT in exif_ifd:
                user_comment = exif_ifd[TAG_USER_COMMENT]
                if isinstance(user_comment, bytes) and user_comment.startswith(b"UNICODE\x00"):
                    description = user_comment[8:].decode("utf-16le", errors="ignore").rstrip("\x00")
                elif isinstance(user_comment, bytes) and user_comment.startswith(b"ASCII\x00\x00\x00"):
                    description = user_comment[8:].decode("ascii", errors="ignore").rstrip("\x00")
            
            if TAG_DATETIME_ORIGINAL in exif_ifd:
                date = exif_ifd[TAG_DATETIME_ORIGINAL]
            elif TAG_CREATE_DATE in exif_ifd:
                date = exif_ifd[TAG_CREATE_DATE]
            elif TAG_MODIFY_DATE in exif:
                date = exif[TAG_MODIFY_DATE]
            
            raw_xp = exif.get(TAG_XP_KEYWORDS)
            if isinstance(raw_xp, bytes):
                decoded = raw_xp.decode("utf-16le", errors="ignore").rstrip("\x00")
                for t in decoded.split(";"):
                    t_clean = t.strip()
                    if t_clean: tags.add(t_clean)
            elif isinstance(raw_xp, str):
                for t in raw_xp.split(";"):
                    t_clean = t.strip()
                    if t_clean: tags.add(t_clean)

            raw_desc = exif.get(TAG_IMAGE_DESC)
            if isinstance(raw_desc, str):
                for t in raw_desc.replace(";", ",").split(","):
                    t_clean = t.strip()
                    if t_clean: tags.add(t_clean)

            for xmp_key in ("xmp", "XML:com.adobe.xmp"):
                if xmp_key in img.info:
                    raw_xmp = img.info[xmp_key]
                    if isinstance(raw_xmp, bytes): raw_xmp = raw_xmp.decode("utf-8", errors="ignore")
                    if isinstance(raw_xmp, str):
                        for match in re.findall(r"<rdf:li>(.*?)</rdf:li>", raw_xmp, re.IGNORECASE):
                            t_clean = match.strip()
                            if t_clean: tags.add(t_clean)
                        if not description:
                            desc_match = re.search(r"<dc:description>.*?<rdf:li[^>]*>(.*?)</rdf:li>.*?</dc:description>", raw_xmp, re.IGNORECASE | re.DOTALL)
                            if desc_match: description = desc_match.group(1).strip()
                        if not date:
                            date_match = re.search(r"<photoshop:DateCreated>(.*?)</photoshop:DateCreated>", raw_xmp, re.IGNORECASE)
                            if date_match: date = date_match.group(1).strip()
    except Exception:
        pass
    
    metadata["tags"] = sorted(tags)
    metadata["description"] = description
    metadata["date"] = date
    return metadata

def write_image_metadata(path: Path, raw_tags: list[str], description: str = "", date: str = "") -> bool:
    if not path.exists(): return False
    hierarchical_list, flat_list, seen_h, seen_f = [], [], set(), set()
    for t in raw_tags:
        h, f = parse_tag(t)
        if h and h not in seen_h:
            seen_h.add(h)
            hierarchical_list.append(h)
        if f and f not in seen_f:
            seen_f.add(f)
            flat_list.append(f)
            
    xp_val = "; ".join(flat_list).encode("utf-16le")
    desc_val = ", ".join(flat_list)
    xmp_bytes = build_immich_xmp_bytes(flat_list, hierarchical_list, description, date)
    
    xp_comment = description.encode("utf-16le") if description else None
    user_comment = b"UNICODE\x00" + description.encode("utf-16le") if description else None
    
    try:
        with Image.open(path) as img:
            exif = img.getexif()
            
            if flat_list:
                exif[TAG_XP_KEYWORDS] = xp_val
                exif[TAG_IMAGE_DESC] = desc_val
            else:
                exif.pop(TAG_XP_KEYWORDS, None)
                exif.pop(TAG_IMAGE_DESC, None)
                
            if description:
                exif[TAG_XP_COMMENT] = xp_comment
            else:
                exif.pop(TAG_XP_COMMENT, None)
                
            if date:
                # User specifically requested date can be 4 digit year, which is fine
                exif[TAG_MODIFY_DATE] = date
            else:
                exif.pop(TAG_MODIFY_DATE, None)
                
            exif_ifd = exif.get_ifd(EXIF_IFD_POINTER)
            if description:
                exif_ifd[TAG_USER_COMMENT] = user_comment
            else:
                exif_ifd.pop(TAG_USER_COMMENT, None)
                
            if date:
                exif_ifd[TAG_DATETIME_ORIGINAL] = date
                exif_ifd[TAG_CREATE_DATE] = date
            else:
                exif_ifd.pop(TAG_DATETIME_ORIGINAL, None)
                exif_ifd.pop(TAG_CREATE_DATE, None)
                
            exif[EXIF_IFD_POINTER] = exif_ifd
            
            kwargs = {}
            if img.format in ["JPEG", "MPO"]:
                kwargs["quality"] = 95
                if xmp_bytes: kwargs["xmp"] = xmp_bytes
                
            try:
                img.save(path, exif=exif.tobytes(), **kwargs)
            except Exception:
                kwargs.pop("xmp", None)
                img.save(path, exif=exif.tobytes(), **kwargs)
        return True
    except Exception as e:
        print(f"Error writing metadata to {path}: {e}")
        return False
"""
    content += new_metadata_funcs

    with open(scanner_path, "w", encoding="utf-8") as f:
        f.write(content)

def patch_backend():
    main_path = r"c:\Users\pmitchell\.gemini\antigravity\scratch\picCurator-Studio-Workspace\web\backend\main.py"
    with open(main_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    old_tags_route = r"@app\.get\(\"/api/tags\"\)\s*def get_tags\(path: str\):.*?(?=@app\.get|TAG_FILE_PATH)"
    new_metadata_route = """@app.get("/api/metadata")
def get_metadata(path: str):
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="File not found")
    try:
        meta = scanner.read_image_metadata(Path(path))
        return {"status": "success", **meta}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
        
@app.get("/api/tags")
def get_tags(path: str):
    # Fallback to metadata
    return get_metadata(path)

"""
    def repl_tags(m):
        return new_metadata_route
    content = re.sub(old_tags_route, repl_tags, content, flags=re.MULTILINE|re.DOTALL)
    
    content = content.replace(
        "class TagAction(BaseModel):\n    paths: list[str]\n    tag: str\n    action: str # \"add\" or \"remove\"",
        "class TagAction(BaseModel):\n    paths: list[str]\n    tag: str = \"\"\n    action: str = \"\"\n    description: str = None\n    date: str = None"
    )
    
    old_manage_tags = r"@app\.post\(\"/api/tags\"\)\s*def manage_tags\(req: TagAction\):.*?(?=@app|def |class )"
    new_manage_tags = """@app.post("/api/tags")
def manage_tags(req: TagAction):
    count = 0
    for p in req.paths:
        if os.path.exists(p):
            meta = scanner.read_image_metadata(Path(p))
            tags = meta['tags']
            description = req.description if req.description is not None else meta['description']
            date = req.date if req.date is not None else meta['date']
            
            if req.tag and req.action:
                tag = req.tag.strip()
                if req.action == 'add' and tag not in tags:
                    tags.append(tag)
                elif req.action == 'remove' and tag in tags:
                    tags.remove(tag)
                    
            if scanner.write_image_metadata(Path(p), tags, description, date):
                count += 1
    return {"status": "success", "modified_count": count}

"""
    def repl_manage(m):
        return new_manage_tags
    content = re.sub(old_manage_tags, repl_manage, content, flags=re.MULTILINE|re.DOTALL)
    
    with open(main_path, "w", encoding="utf-8") as f:
        f.write(content)

patch_scanner()
patch_backend()
print("Scanner and Backend patched")
