from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
import io
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import sys
import os
import shutil
import time
import json
from pathlib import Path
from PIL import Image
Image.MAX_IMAGE_PIXELS = None

# Add root project dir to path so we can import scanner
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import scanner
import requests
try:
    from send2trash import send2trash
except ImportError:
    send2trash = os.remove

app = FastAPI(title="PicCurator Web API")

# Allow CORS for local frontend dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class SearchQuery(BaseModel):
    server_url: str
    api_key: str
    query: str
    limit: int = 250

class BaseQuery(BaseModel):
    server_url: str
    api_key: str

class PersonAssetsQuery(BaseQuery):
    person_id: str

class TagAction(BaseModel):
    paths: list[str]
    tag: str = ""
    action: str = ""
    description: str = None
    date: str = None

class PathsAction(BaseModel):
    paths: list[str]

@app.post("/api/search")
def search_immich(req: SearchQuery):
    success, result = scanner.immich_smart_search(req.server_url, req.api_key, req.query, req.limit)
    if not success:
        raise HTTPException(status_code=500, detail=str(result))
    return {"assets": result}

@app.get("/api/folders")
def get_folders():
    base_dir = "/mnt/backups/family_photos"
    folders = []
    if os.path.exists(base_dir):
        for root, dirs, files in os.walk(base_dir):
            rel_path = os.path.relpath(root, base_dir)
            if rel_path == ".":
                rel_path = ""
            folders.append(rel_path)
    return {"folders": sorted(folders)}

@app.get("/api/folder/images")
def get_folder_images(folder: str = ""):
    base_dir = "/mnt/backups/family_photos"
    target_dir = os.path.join(base_dir, folder)
    if not os.path.abspath(target_dir).startswith(os.path.abspath(base_dir)):
        raise HTTPException(status_code=400, detail="Invalid path")
    
    if not os.path.exists(target_dir):
        return {"assets": []}

    assets = []
    for f in os.listdir(target_dir):
        p = os.path.join(target_dir, f)
        if os.path.isfile(p) and f.lower().endswith(('.png', '.jpg', '.jpeg', '.tiff', '.tif', '.bmp', '.gif', '.webp')):
            assets.append({
                "id": p,
                "originalFileName": f,
                "originalPath": p,
                "isLocal": True
            })
    return {"assets": sorted(assets, key=lambda x: x['originalFileName'])}

class SplitRequest(BaseModel):
    path: str

@app.post("/api/split")
def split_image(req: SplitRequest):
    try:
        import cv2
        import numpy as np
        
        path = req.path
        if not os.path.exists(path):
            raise HTTPException(status_code=404, detail="File not found")
            
        img = cv2.imread(path)
        if img is None:
            raise HTTPException(status_code=400, detail="Could not read image")
            
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        # Invert so black regions are background and white regions are photos (if background is white)
        # Actually scanned pages are light, photos are dark.
        # Thresholding: anything darker than 200 becomes white (255) for contouring
        _, thresh = cv2.threshold(gray, 220, 255, cv2.THRESH_BINARY_INV)
        
        # Clean up noise
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel, iterations=3)
        dilated = cv2.dilate(closed, kernel, iterations=2)
        
        contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        min_area = img.shape[0] * img.shape[1] * 0.02 # At least 2% of image
        photo_rects = []
        for c in contours:
            area = cv2.contourArea(c)
            if area > min_area:
                x, y, w, h = cv2.boundingRect(c)
                photo_rects.append((x, y, w, h))
                
        if not photo_rects:
            raise HTTPException(status_code=400, detail="Could not detect distinct photos in the image.")
            
        # Crop using Pillow to retain metadata if any
        base_dir = os.path.dirname(path)
        filename = os.path.basename(path)
        name, ext = os.path.splitext(filename)
        
        saved_paths = []
        old_tags = scanner.read_image_tags(Path(path))
        
        with Image.open(path) as pil_img:
            # Sort rects top-to-bottom, left-to-right roughly
            photo_rects.sort(key=lambda r: (r[1] // 100, r[0]))
            
            for i, (x, y, w, h) in enumerate(photo_rects):
                cropped = pil_img.crop((x, y, x+w, y+h))
                new_path = os.path.join(base_dir, f"{name}_split{i+1}{ext}")
                
                kwargs = {}
                for key in ["exif", "xmp", "icc_profile"]:
                    if key in pil_img.info:
                        kwargs[key] = pil_img.info[key]
                if pil_img.format in ["JPEG", "MPO"]:
                    kwargs["quality"] = 95
                    
                cropped.save(new_path, **kwargs)
                
                if old_tags:
                    scanner.write_image_tags(Path(new_path), old_tags)
                    
                if not os.path.exists(new_path) or os.path.getsize(new_path) == 0:
                    raise RuntimeError(f"Failed to verify creation of split file at {new_path}")
                    
                saved_paths.append(new_path)
            
        # Optionally move original to recycle bin? Let frontend handle it if they want.
        return {"status": "success", "parts": saved_paths}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class CropAction(BaseModel):
    path: str
    x: float
    y: float
    width: float
    height: float

@app.post("/api/crop")
def manual_crop(req: CropAction):
    if not os.path.exists(req.path):
        raise HTTPException(status_code=404, detail="File not found")
    try:
        with Image.open(req.path) as img:
            left = int(img.width * req.x)
            top = int(img.height * req.y)
            right = int(img.width * (req.x + req.width))
            bottom = int(img.height * (req.y + req.height))
            
            # Bound checking
            left = max(0, min(left, img.width - 1))
            top = max(0, min(top, img.height - 1))
            right = max(left + 1, min(right, img.width))
            bottom = max(top + 1, min(bottom, img.height))
            
            if right <= left or bottom <= top:
                raise ValueError("Invalid crop dimensions")

            cropped = img.crop((left, top, right, bottom))
            
            base_dir = os.path.dirname(req.path)
            name, ext = os.path.splitext(os.path.basename(req.path))
            
            old_tags = scanner.read_image_tags(Path(req.path))
            
            counter = 1
            while True:
                new_path = os.path.join(base_dir, f"{name}_crop_{counter}{ext}")
                if not os.path.exists(new_path):
                    break
                counter += 1
                
            kwargs = {}
            for key in ["exif", "xmp", "icc_profile"]:
                if key in img.info:
                    kwargs[key] = img.info[key]
            if img.format in ["JPEG", "MPO"]:
                kwargs["quality"] = 95
                
            cropped.save(new_path, **kwargs)
            
            if old_tags:
                scanner.write_image_tags(Path(new_path), old_tags)
                
            if not os.path.exists(new_path) or os.path.getsize(new_path) == 0:
                raise RuntimeError(f"Failed to verify creation of new file at {new_path}")
                
            return {"status": "success", "new_path": new_path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/people")
def get_people(req: BaseQuery):
    success, result = scanner.immich_get_people(req.server_url, req.api_key)
    if not success:
        raise HTTPException(status_code=500, detail=str(result))
    return {"people": result}

@app.post("/api/people/assets")
def get_person_assets(req: PersonAssetsQuery):
    success, result = scanner.immich_get_person_assets(req.server_url, req.api_key, req.person_id)
    if not success:
        raise HTTPException(status_code=500, detail=str(result))
    return {"assets": result}

@app.post("/api/test-connection")
def test_connection(req: BaseQuery):
    base_url = req.server_url.strip().rstrip('/')
    if not base_url.startswith("http://") and not base_url.startswith("https://"):
        base_url = "http://" + base_url
    url = f"{base_url}/api/server-info/ping"
    headers = {"Accept": "application/json"}
    if req.api_key:
        headers["x-api-key"] = req.api_key.strip()
    try:
        resp = requests.get(url, headers=headers, timeout=5)
        resp.raise_for_status()
        return {"status": "success", "message": "✓ Connection Successful"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Connection failed: {str(e)}")

@app.get("/api/image")
def get_local_image(path: str, size: str = "large", t: str = None):
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="File not found")
        
    ext = os.path.splitext(path)[1].lower()
    
    # Browsers cannot display .tif/.tiff natively. 
    # Also, we should resize to preview if requested to speed up loading.
    if ext in ['.tif', '.tiff'] or size == "preview":
        import hashlib
        CACHE_DIR = "/mnt/backups/piccurator/cache"
        os.makedirs(CACHE_DIR, exist_ok=True)
        
        # Base the cache key on the file's ACTUAL modification time (mtime)
        # If the file is rotated on disk, its mtime changes, automatically busting the cache.
        mtime = str(os.path.getmtime(path))
        cache_key = hashlib.md5(f"{path}_{size}_{mtime}".encode()).hexdigest()
        cached_path = os.path.join(CACHE_DIR, f"{cache_key}.jpg")
        
        if os.path.exists(cached_path):
            return FileResponse(cached_path)
            
        try:
            with Image.open(path) as img:
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                
                # If preview, downscale it to max 800x800 while preserving aspect ratio
                if size == "preview":
                    img.thumbnail((800, 800))
                else:
                    # Capped at 1080p HD to save bandwidth and RAM on cheap phones
                    img.thumbnail((1920, 1920))
                    
                img.save(cached_path, format='JPEG', quality=85)
                return FileResponse(cached_path)
        except Exception as e:
            # If conversion fails, fallback to sending the raw file
            print(f"Failed to convert image {path}: {e}")
            return FileResponse(path)
            
    return FileResponse(path)

@app.get("/api/cache-size")
def get_cache_size():
    total_size = 0
    CACHE_DIR = "/mnt/backups/piccurator/cache"
    if os.path.exists(CACHE_DIR):
        for dirpath, _, filenames in os.walk(CACHE_DIR):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                if not os.path.islink(fp):
                    total_size += os.path.getsize(fp)
    return {"size_bytes": total_size}

@app.get("/api/metadata")
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

TAG_FILE_PATH = "/mnt/backups/piccurator/tags.json"
DEFAULT_TAGS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "default_tags.json")

def get_global_tags():
    try:
        if not os.path.exists(TAG_FILE_PATH):
            if os.path.exists(DEFAULT_TAGS_PATH):
                os.makedirs(os.path.dirname(TAG_FILE_PATH), exist_ok=True)
                shutil.copy(DEFAULT_TAGS_PATH, TAG_FILE_PATH)
            else:
                return {}
        with open(TAG_FILE_PATH, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading global tags: {e}")
        # Fallback to defaults if we can't read/write to the mount
        try:
            with open(DEFAULT_TAGS_PATH, "r") as f:
                return json.load(f)
        except:
            return {}

def save_global_tags(tags_data):
    os.makedirs(os.path.dirname(TAG_FILE_PATH), exist_ok=True)
    with open(TAG_FILE_PATH, "w") as f:
        json.dump(tags_data, f, indent=2)

@app.get("/api/tag-list")
def read_tag_list():
    return get_global_tags()

class TagListUpdate(BaseModel):
    category: str
    tag: str

@app.post("/api/tag-list")
def add_to_tag_list(req: TagListUpdate):
    tags_data = get_global_tags()
    cat = req.category.strip()
    tag = req.tag.strip()
    if not cat or not tag:
        raise HTTPException(status_code=400, detail="Category and tag required")
        
    if cat not in tags_data:
        tags_data[cat] = []
        
    if tag not in tags_data[cat]:
        tags_data[cat].append(tag)
        save_global_tags(tags_data)
        
    return {"status": "success", "tags": tags_data}

@app.post("/api/tag-list/full")
def save_full_tag_list(req: dict):
    save_global_tags(req)
    return {"status": "success", "tags": req}

class TagMergeAction(BaseModel):
    bad_tag: str
    good_tag: str

@app.post("/api/tags/merge")
def merge_tags(req: TagMergeAction):
    bad_tag = req.bad_tag.strip()
    good_tag = req.good_tag.strip()
    if not bad_tag or not good_tag:
        raise HTTPException(status_code=400, detail="Both bad_tag and good_tag are required")
        
    # Update global tags first
    tags_data = get_global_tags()
    global_modified = False
    
    # Check if good_tag already exists in ANY category
    # Strip whitespace to ensure we match even if the JSON has padded strings
    good_tag_exists_anywhere = False
    for cat, t_list in tags_data.items():
        if any(t.strip() == good_tag for t in t_list):
            good_tag_exists_anywhere = True
            break
            
    for cat, t_list in tags_data.items():
        if bad_tag in t_list:
            t_list.remove(bad_tag)
            if not good_tag_exists_anywhere:
                t_list.append(good_tag)
                good_tag_exists_anywhere = True
            global_modified = True
            
    if global_modified:
        save_global_tags(tags_data)

    # Scan and update files
    count = 0
    base_dir = "/mnt/backups/family_photos"
    if os.path.exists(base_dir):
        image_paths = scanner.collect_image_paths(base_dir)
        for p in image_paths:
            tags = scanner.read_image_tags(p)
            if bad_tag in tags:
                tags.remove(bad_tag)
                if good_tag not in tags:
                    tags.append(good_tag)
                if scanner.write_image_tags(p, tags):
                    count += 1
                    
    return {"status": "success", "modified_count": count, "tags": tags_data}

@app.post("/api/tags")
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

@app.post("/api/rotate")
def rotate_images(req: PathsAction):
    count = 0
    for p in req.paths:
        try:
            path_obj = Path(p)
            old_tags = scanner.read_image_tags(path_obj)
            
            with Image.open(p) as img:
                rotated = img.transpose(Image.Transpose.ROTATE_270)
                kwargs = {}
                for key in ["exif", "xmp", "icc_profile"]:
                    if key in img.info:
                        kwargs[key] = img.info[key]
                if img.format in ["JPEG", "MPO"]:
                    kwargs["quality"] = 95
                rotated.save(p, **kwargs)
                
            if old_tags:
                scanner.write_image_tags(path_obj, old_tags)
            count += 1
        except Exception as e:
            print(f"Error rotating {p}: {e}")
    return {"status": "success", "rotated_count": count}

@app.post("/api/trash")
def trash_images(req: PathsAction):
    trashed = 0
    recycle_dir = "/mnt/backups/recyclebin"
    os.makedirs(recycle_dir, exist_ok=True)
    errors = []
    for p in req.paths:
        try:
            if os.path.exists(p):
                basename = os.path.basename(p)
                dest = os.path.join(recycle_dir, basename)
                if os.path.exists(dest):
                    name, ext = os.path.splitext(basename)
                    dest = os.path.join(recycle_dir, f"{name}_{int(time.time())}{ext}")
                
                shutil.copy2(p, dest)
                os.remove(p)
                
                if os.path.exists(p):
                    raise Exception("File still exists after removal attempt.")
                
                trashed += 1
        except Exception as e:
            print(f"Error trashing {p}: {e}")
            errors.append(f"{p}: {str(e)}")
            
    if errors:
        raise HTTPException(status_code=500, detail=f"Failed to trash some images: {'; '.join(errors)}")
        
    return {"status": "success", "trashed_count": trashed}

@app.get("/api/untagged/count")
def get_untagged_count():
    base_dir = "/mnt/backups/family_photos"
    if not os.path.exists(base_dir):
        return {"count": 0}
        
    count = 0
    image_paths = scanner.collect_image_paths(base_dir)
    for p in image_paths:
        tags = scanner.read_image_tags(p)
        if not tags:
            count += 1
    return {"count": count}

@app.get("/api/untagged/images")
def get_untagged_images():
    base_dir = "/mnt/backups/family_photos"
    if not os.path.exists(base_dir):
        return {"assets": []}
        
    assets = []
    image_paths = scanner.collect_image_paths(base_dir)
    for p in image_paths:
        tags = scanner.read_image_tags(p)
        if not tags:
            assets.append({
                "id": str(p),
                "originalFileName": os.path.basename(str(p)),
                "originalPath": str(p),
                "isLocal": True
            })
    return {"assets": sorted(assets, key=lambda x: x['originalFileName'])}

# Serve React Frontend
frontend_build_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend", "dist")
if os.path.exists(frontend_build_path):
    app.mount("/", StaticFiles(directory=frontend_build_path, html=True), name="frontend")
else:
    @app.get("/")
    def read_root():
        return {"status": "ok", "message": "PicCurator Web API (Frontend build not found)"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
