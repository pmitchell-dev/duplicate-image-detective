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
    tag: str
    action: str # "add" or "remove"

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
def get_local_image(path: str, size: str = "large"):
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="File not found")
        
    ext = os.path.splitext(path)[1].lower()
    
    # Browsers cannot display .tif/.tiff natively. 
    # Also, we should resize to preview if requested to speed up loading.
    if ext in ['.tif', '.tiff'] or size == "preview":
        try:
            with Image.open(path) as img:
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                
                # If preview, downscale it to max 800x800 while preserving aspect ratio
                if size == "preview":
                    img.thumbnail((800, 800))
                else:
                    # Even if large, resize it slightly if it's ridiculously massive (e.g. 10k pixels) just to prevent browser crash,
                    # but typically album pages are fine to serve as long as they're JPEGs.
                    img.thumbnail((3000, 3000))
                    
                buf = io.BytesIO()
                img.save(buf, format='JPEG', quality=85)
                buf.seek(0)
                return StreamingResponse(buf, media_type="image/jpeg")
        except Exception as e:
            # If conversion fails, fallback to sending the raw file
            print(f"Failed to convert image {path}: {e}")
            return FileResponse(path)
            
    return FileResponse(path)

@app.get("/api/tags")
def get_tags(path: str):
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="File not found")
    try:
        tags = scanner.read_image_tags(Path(path))
        return {"status": "success", "tags": tags}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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

@app.post("/api/tags")
def manage_tags(req: TagAction):
    count = 0
    cleaned = req.tag.strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="Empty tag")

    for p in req.paths:
        path_obj = Path(p)
        tags = scanner.read_image_tags(path_obj)
        existing_lower = {t.lower() for t in tags}
        modified = False

        if req.action == "add":
            if cleaned.lower() not in existing_lower:
                tags.append(cleaned)
                modified = True
        elif req.action == "remove":
            if cleaned.lower() in existing_lower:
                tags = [t for t in tags if t.lower() != cleaned.lower()]
                modified = True

        if modified:
            if scanner.write_image_tags(path_obj, tags):
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
    for p in req.paths:
        try:
            if os.path.exists(p):
                basename = os.path.basename(p)
                dest = os.path.join(recycle_dir, basename)
                if os.path.exists(dest):
                    name, ext = os.path.splitext(basename)
                    dest = os.path.join(recycle_dir, f"{name}_{int(time.time())}{ext}")
                shutil.move(p, dest)
                trashed += 1
        except Exception as e:
            print(f"Error trashing {p}: {e}")
    return {"status": "success", "trashed_count": trashed}

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
