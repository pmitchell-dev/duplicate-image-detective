import re

def patch_scanner():
    scanner_path = r"c:\Users\pmitchell\.gemini\antigravity\scratch\picCurator-Studio-Workspace\scanner.py"
    with open(scanner_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 1. Update get_exiftool_metadata to include ImageDescription
    old_exiftool_read = r"res = subprocess\.run\(\n\s*\[\"exiftool\", \"-json\".*?\],\n\s*capture_output=True, text=True, check=True\n\s*\)"
    new_exiftool_read = """res = subprocess.run(
            ["exiftool", "-json", "-UserComment", "-XPComment", "-Description", "-ImageDescription", "-Caption-Abstract", "-ModifyDate", "-DateTimeOriginal", "-CreateDate", "-DateCreated", "-XPKeywords", "-Subject", "-HierarchicalSubject", "-TagsList", path],
            capture_output=True, text=True, check=True
        )"""
    content = re.sub(old_exiftool_read, new_exiftool_read, content, flags=re.MULTILINE|re.DOTALL)

    # 2. Update get_exiftool_metadata description extraction to include ImageDescription
    old_desc_extract = r"description = data\.get\(\"UserComment\"\).*?or \"\""
    new_desc_extract = """description = data.get("UserComment") or data.get("XPComment") or data.get("Description") or data.get("ImageDescription") or data.get("Caption-Abstract") or \"\""""
    content = re.sub(old_desc_extract, new_desc_extract, content, flags=re.MULTILINE)
    
    # 3. Add debug print if exiftool fails
    old_except = r"except Exception as e:\n\s*return None"
    new_except = """except Exception as e:
        print(f"ExifTool extraction failed for {path}: {e}")
        return None"""
    # Only replace the first occurrence (which is inside get_exiftool_metadata)
    content = content.replace("except Exception as e:\n        return None", new_except, 1)

    # 4. Update robust PIL fallback for TIFFs
    old_pil_read = r"exif = img\.getexif\(\)\n\s*exif_ifd = exif\.get_ifd\(EXIF_IFD_POINTER\)"
    new_pil_read = """exif = img.getexif()
            exif_ifd = exif.get_ifd(EXIF_IFD_POINTER)
            
            # TIFF fallback
            if hasattr(img, 'tag_v2') and img.format in ['TIFF', 'TIF']:
                for k, v in img.tag_v2.items():
                    if k not in exif:
                        exif[k] = v[0] if isinstance(v, tuple) and len(v) == 1 else v
                    # Many TIFFs store ExifIFD tags directly in the main IFD
                    if k not in exif_ifd and k in [TAG_DATETIME_ORIGINAL, TAG_CREATE_DATE, TAG_USER_COMMENT]:
                        exif_ifd[k] = v[0] if isinstance(v, tuple) and len(v) == 1 else v
"""
    content = content.replace("exif = img.getexif()\n            exif_ifd = exif.get_ifd(EXIF_IFD_POINTER)", new_pil_read)
    
    with open(scanner_path, "w", encoding="utf-8") as f:
        f.write(content)

patch_scanner()
print("Scanner patched for TIFF and ImageDescription")
