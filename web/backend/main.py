from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import sys
import os
from pathlib import Path
from PIL import Image

# Add root project dir to path so we can import scanner
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import scanner
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

@app.get("/api/image")
def get_local_image(path: str):
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path)

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
            with Image.open(p) as img:
                rotated = img.transpose(Image.Transpose.ROTATE_270)
                kwargs = {}
                for key in ["exif", "xmp", "icc_profile"]:
                    if key in img.info:
                        kwargs[key] = img.info[key]
                if img.format in ["JPEG", "MPO"]:
                    kwargs["quality"] = 95
                rotated.save(p, **kwargs)
            count += 1
        except Exception as e:
            print(f"Error rotating {p}: {e}")
    return {"status": "success", "rotated_count": count}

@app.post("/api/trash")
def trash_images(req: PathsAction):
    trashed = 0
    for p in req.paths:
        try:
            if os.path.exists(p):
                send2trash(p)
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
