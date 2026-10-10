import re

def patch_scanner():
    scanner_path = r"c:\Users\pmitchell\.gemini\antigravity\scratch\picCurator-Studio-Workspace\scanner.py"
    with open(scanner_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Make sure subprocess and json are imported
    if "import subprocess" not in content:
        content = content.replace("import os", "import os\nimport subprocess\nimport json")

    exiftool_funcs = """
def get_exiftool_metadata(path: str):
    try:
        res = subprocess.run(
            ["exiftool", "-json", "-UserComment", "-XPComment", "-Description", "-Caption-Abstract", "-ModifyDate", "-DateTimeOriginal", "-CreateDate", "-DateCreated", "-XPKeywords", "-Subject", "-HierarchicalSubject", "-TagsList", path],
            capture_output=True, text=True, check=True
        )
        data = json.loads(res.stdout)[0]
        
        description = data.get("UserComment") or data.get("XPComment") or data.get("Description") or data.get("Caption-Abstract") or ""
        date = data.get("DateTimeOriginal") or data.get("CreateDate") or data.get("ModifyDate") or data.get("DateCreated") or ""
        
        tags = set()
        for k in ["XPKeywords", "Subject", "HierarchicalSubject", "TagsList"]:
            v = data.get(k)
            if v:
                if isinstance(v, list):
                    for t in v: tags.add(str(t).strip())
                elif isinstance(v, str):
                    for t in v.split(";"): tags.add(t.strip())
        
        filtered_tags = sorted([t for t in tags if t != description and t != ""])
        return {"tags": filtered_tags, "description": str(description).strip(), "date": str(date).strip()}
    except Exception as e:
        return None

def write_exiftool_metadata(path: str, raw_tags: list[str], description: str, date: str):
    try:
        cmd = ["exiftool", "-overwrite_original", "-charset", "filename=utf8"]
        if description:
            cmd.extend([f"-UserComment={description}", f"-XPComment={description}", f"-Description={description}", f"-Caption-Abstract={description}"])
        else:
            cmd.extend(["-UserComment=", "-XPComment=", "-Description=", "-Caption-Abstract="])
            
        if date:
            cmd.extend([f"-ModifyDate={date}", f"-DateTimeOriginal={date}", f"-CreateDate={date}", f"-DateCreated={date}"])
        else:
            cmd.extend(["-ModifyDate=", "-DateTimeOriginal=", "-CreateDate=", "-DateCreated="])
            
        cmd.extend(["-XPKeywords=", "-Subject=", "-HierarchicalSubject=", "-TagsList="])
        if raw_tags:
            flat_list = []
            hier_list = []
            seen_h, seen_f = set(), set()
            for t in raw_tags:
                h, f = parse_tag(t)
                if h and h not in seen_h:
                    seen_h.add(h)
                    hier_list.append(h)
                if f and f not in seen_f:
                    seen_f.add(f)
                    flat_list.append(f)
            
            cmd.append(f"-XPKeywords={'; '.join(flat_list)}")
            for t in flat_list:
                cmd.append(f"-Subject={t}")
            for t in hier_list:
                cmd.append(f"-HierarchicalSubject={t}")
                cmd.append(f"-TagsList={t}")
                
        cmd.append(path)
        subprocess.run(cmd, capture_output=True, check=True)
        return True
    except Exception as e:
        return False
"""

    if "def get_exiftool_metadata" not in content:
        content = content.replace("def read_image_metadata", exiftool_funcs + "\ndef read_image_metadata")

    # Inject into read_image_metadata
    old_read_start = r"def read_image_metadata\(path: Path\) -> dict:\n\s*metadata = \{\"tags\": \[\], \"description\": \"\", \"date\": \"\"\}\n\s*if not path\.exists\(\): return metadata"
    new_read_start = """def read_image_metadata(path: Path) -> dict:
    metadata = {"tags": [], "description": "", "date": ""}
    if not path.exists(): return metadata
    
    exif_data = get_exiftool_metadata(str(path))
    if exif_data is not None:
        return exif_data
"""
    content = re.sub(old_read_start, new_read_start, content, flags=re.MULTILINE)

    # Inject into write_image_metadata
    old_write_start = r"def write_image_metadata\(path: Path, raw_tags: list\[str\], description: str = \"\", date: str = \"\"\) -> bool:\n\s*if not path\.exists\(\): return False"
    new_write_start = """def write_image_metadata(path: Path, raw_tags: list[str], description: str = "", date: str = "") -> bool:
    if not path.exists(): return False
    
    if write_exiftool_metadata(str(path), raw_tags, description, date):
        return True
"""
    content = re.sub(old_write_start, new_write_start, content, flags=re.MULTILINE)

    with open(scanner_path, "w", encoding="utf-8") as f:
        f.write(content)

patch_scanner()
print("Scanner patched with exiftool support")
