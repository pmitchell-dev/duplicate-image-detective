"""
scanner.py — Background duplicate image scanner for Duplicate Image Detective.

Uses perceptual hashing (pHash) to find visually identical images even if
they differ in file format, compression, or metadata.
"""
from __future__ import annotations

import os
import queue
import re
import threading
from pathlib import Path

import imagehash
from PIL import Image

# Supported image extensions (lower-case)
IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp",
    ".webp", ".tiff", ".tif",
}

# Maximum perceptual-hash distance to consider two images duplicates.
# 0  = bit-for-bit identical hash (only exact visual clones).
# ≤10 = catches re-saves / slight compression artefacts.
DEFAULT_HASH_THRESHOLD = 6


def collect_image_paths(root_dir: str | Path) -> list[Path]:
    """Recursively collect all supported image paths under root_dir."""
    paths = []
    for dirpath, _dirs, filenames in os.walk(root_dir):
        for filename in filenames:
            p = Path(dirpath) / filename
            if p.suffix.lower() in IMAGE_EXTENSIONS:
                paths.append(p)
    return sorted(paths)


def collect_images_by_folder(root_dir: str | Path) -> dict[Path, list[Path]]:
    """
    Recursively walk root_dir and group supported images by parent directory.
    Returns a dict mapping folder Path -> sorted list of image Paths.
    """
    folder_map: dict[Path, list[Path]] = {}
    for dirpath, _dirs, filenames in os.walk(root_dir):
        folder_path = Path(dirpath)
        imgs = []
        for filename in filenames:
            p = folder_path / filename
            if p.suffix.lower() in IMAGE_EXTENSIONS:
                imgs.append(p)
        if imgs:
            imgs.sort()
            folder_map[folder_path] = imgs
    return folder_map


TAG_XP_KEYWORDS  = 0x9C9E   # Windows XP/File Explorer Tags
TAG_IMAGE_DESC   = 0x010E   # Standard EXIF ImageDescription
TAG_USER_COMMENT = 0x9286   # EXIF UserComment


def parse_tag(tag: str) -> tuple[str, str]:
    """
    Parse a tag into (hierarchical_tag, flat_tag).
    Example: "People/Jane Doe" -> ("People/Jane Doe", "Jane Doe")
    Example: "Sunset" -> ("Sunset", "Sunset")
    """
    cleaned = tag.strip()
    if "/" in cleaned:
        parts = [p.strip() for p in cleaned.split("/") if p.strip()]
        hierarchical = "/".join(parts)
        flat = parts[-1]
        return hierarchical, flat
    return cleaned, cleaned


def build_immich_xmp_bytes(flat_tags: list[str], hierarchical_tags: list[str]) -> bytes:
    """
    Generate an XMP RDF/XML packet compatible with Immich, Adobe Lightroom,
    digiKam, and standard XMP readers.
    """
    dc_items = "".join(f"<rdf:li>{t}</rdf:li>" for t in flat_tags)
    lr_items = "".join(f"<rdf:li>{t}</rdf:li>" for t in hierarchical_tags)
    digi_items = "".join(f"<rdf:li>{t}</rdf:li>" for t in hierarchical_tags)

    xmp_str = f"""<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:dc="http://purl.org/dc/elements/1.1/"
    xmlns:lr="http://ns.adobe.com/lightroom/1.0/"
    xmlns:digiKam="http://www.digikam.org/ns/1.0/">
   <dc:subject>
    <rdf:Bag>
     {dc_items}
    </rdf:Bag>
   </dc:subject>
   <lr:HierarchicalSubject>
    <rdf:Bag>
     {lr_items}
    </rdf:Bag>
   </lr:HierarchicalSubject>
   <digiKam:TagsList>
    <rdf:Seq>
     {digi_items}
    </rdf:Seq>
   </digiKam:TagsList>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
<?xpacket end="w"?>"""
    return xmp_str.encode("utf-8")


def read_image_tags(path: Path) -> list[str]:
    """Read EXIF XPKeywords, ImageDescription, and XMP tags from an image file."""
    if not path.exists():
        return []
    tags = set()
    try:
        with Image.open(path) as img:
            exif = img.getexif()

            # 1. Read XPKeywords (Windows Tags)
            raw_xp = exif.get(TAG_XP_KEYWORDS)
            if isinstance(raw_xp, bytes):
                decoded = raw_xp.decode("utf-16le", errors="ignore").rstrip("\x00")
                for t in decoded.split(";"):
                    t_clean = t.strip()
                    if t_clean:
                        tags.add(t_clean)
            elif isinstance(raw_xp, str):
                for t in raw_xp.split(";"):
                    t_clean = t.strip()
                    if t_clean:
                        tags.add(t_clean)

            # 2. Read ImageDescription
            raw_desc = exif.get(TAG_IMAGE_DESC)
            if isinstance(raw_desc, str):
                for t in raw_desc.replace(";", ",").split(","):
                    t_clean = t.strip()
                    if t_clean:
                        tags.add(t_clean)

            # 3. Read XMP metadata if present
            for xmp_key in ("xmp", "XML:com.adobe.xmp"):
                if xmp_key in img.info:
                    raw_xmp = img.info[xmp_key]
                    if isinstance(raw_xmp, bytes):
                        raw_xmp = raw_xmp.decode("utf-8", errors="ignore")
                    if isinstance(raw_xmp, str):
                        for match in re.findall(r"<rdf:li>(.*?)</rdf:li>", raw_xmp, re.IGNORECASE):
                            t_clean = match.strip()
                            if t_clean:
                                tags.add(t_clean)
    except Exception:
        pass

    return sorted(tags)


def write_image_tags(path: Path, raw_tags: list[str]) -> bool:
    """
    Write full multi-platform metadata payload (Immich XMP + EXIF XPKeywords)
    to the target image file.
    """
    if not path.exists():
        return False

    hierarchical_list = []
    flat_list = []
    seen_h = set()
    seen_f = set()

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
    xmp_bytes = build_immich_xmp_bytes(flat_list, hierarchical_list) if flat_list else b""

    try:
        with Image.open(path) as img:
            exif = img.getexif()
            if flat_list:
                exif[TAG_XP_KEYWORDS] = xp_val
                exif[TAG_IMAGE_DESC] = desc_val
            else:
                exif.pop(TAG_XP_KEYWORDS, None)
                exif.pop(TAG_IMAGE_DESC, None)

            kwargs = {}
            if img.format in ["JPEG", "MPO"]:
                kwargs["quality"] = 95
                if xmp_bytes:
                    kwargs["xmp"] = xmp_bytes

            try:
                img.save(path, exif=exif.tobytes(), **kwargs)
            except Exception:
                kwargs.pop("xmp", None)
                img.save(path, exif=exif.tobytes(), **kwargs)
        return True
    except Exception as e:
        print(f"Error writing tags to {path}: {e}")
        return False


def scan_directory_keywords(root_dir: str | Path) -> set[str]:
    """Scan all images in root_dir tree and collect set of all existing keywords."""
    all_tags = set()
    paths = collect_image_paths(root_dir)
    for p in paths:
        tags = read_image_tags(p)
        all_tags.update(tags)
    return all_tags


class ScanStats:
    """Thread-safe scan progress counters."""

    def __init__(self):
        self._lock = threading.Lock()
        self.total_files = 0
        self.processed = 0
        self.pairs_found = 0

    def set_total(self, n: int):
        with self._lock:
            self.total_files = n

    def inc_processed(self):
        with self._lock:
            self.processed += 1

    def inc_pairs(self):
        with self._lock:
            self.pairs_found += 1

    def snapshot(self):
        with self._lock:
            return self.total_files, self.processed, self.pairs_found


# Sentinel placed in the queue when scanning is finished.
SCAN_DONE = object()


class DuplicateScanner:
    """
    Scans a directory tree for duplicate images using perceptual hashing.

    Algorithm
    ---------
    1. Walk the tree, collecting all image file paths.
    2. Compute phash for every image and store (hash_obj, path) pairs.
    3. Emit all unique (path_a, path_b) pairs where hash distance ≤ threshold.

    Results are placed in ``result_queue`` as 2-tuples of Path objects.
    A ``SCAN_DONE`` sentinel is appended when finished.
    """

    def __init__(
        self,
        root_dir: str,
        result_queue: "queue.Queue[object]",
        stats: ScanStats,
        hash_threshold: int = DEFAULT_HASH_THRESHOLD,
    ):
        self.root_dir = root_dir
        self.result_queue = result_queue
        self.stats = stats
        self.hash_threshold = hash_threshold
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    # ── Public API ────────────────────────────────────────────────────────

    def start(self):
        """Start the scan on a daemon background thread."""
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        """Signal the background thread to stop at the next checkpoint."""
        self._stop_event.set()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ── Internal ──────────────────────────────────────────────────────────

    def _run(self):
        try:
            image_paths = self._collect_image_paths()
            self.stats.set_total(len(image_paths))

            # Phase 1: compute hashes for all images
            hashed: list[tuple[imagehash.ImageHash, Path]] = []
            for path in image_paths:
                if self._stop_event.is_set():
                    return
                h = self._compute_hash(path)
                if h is not None:
                    hashed.append((h, path))
                self.stats.inc_processed()

            # Phase 2: emit all pairs within threshold distance
            if not self._stop_event.is_set():
                self._emit_pairs(hashed)
        finally:
            self.result_queue.put(SCAN_DONE)

    def _collect_image_paths(self) -> list[Path]:
        return collect_image_paths(self.root_dir)

    def _compute_hash(self, path: Path) -> imagehash.ImageHash | None:
        try:
            with Image.open(path) as img:
                return imagehash.phash(img.convert("RGB"))
        except Exception:
            return None

    def _emit_pairs(self, hashed: list[tuple[imagehash.ImageHash, Path]]):
        """
        Emit unique duplicate pairs.

        For threshold == 0 we use a dict (O(n)) grouping identical hash strings.
        For threshold  > 0 we do pairwise comparison (O(n²)) — acceptable for
        typical photo libraries (thousands of images, not millions).
        """
        if self.hash_threshold == 0:
            buckets: dict[str, list[Path]] = {}
            for h, p in hashed:
                buckets.setdefault(str(h), []).append(p)
            seen: set[tuple[str, str]] = set()
            for paths in buckets.values():
                for i, a in enumerate(paths):
                    for b in paths[i + 1:]:
                        if self._stop_event.is_set():
                            return
                        key = (min(str(a), str(b)), max(str(a), str(b)))
                        if key not in seen:
                            seen.add(key)
                            self.result_queue.put((a, b))
                            self.stats.inc_pairs()
        else:
            seen: set[tuple[str, str]] = set()
            for i in range(len(hashed)):
                if self._stop_event.is_set():
                    return
                hi, pi = hashed[i]
                for j in range(i + 1, len(hashed)):
                    hj, pj = hashed[j]
                    if hi - hj <= self.hash_threshold:
                        key = (min(str(pi), str(pj)), max(str(pi), str(pj)))
                        if key not in seen:
                            seen.add(key)
                            self.result_queue.put((pi, pj))
                            self.stats.inc_pairs()


# ─────────────────────────────────────────────────────────────────────────────
# Immich REST API Client Helpers
# ─────────────────────────────────────────────────────────────────────────────
import json
import mimetypes
import time
import urllib.error
import urllib.request


def _immich_base_url(server_url: str) -> str:
    url = server_url.strip().rstrip("/")
    if not url:
        return ""
    if not (url.startswith("http://") or url.startswith("https://")):
        url = "http://" + url
    if url.endswith("/api"):
        url = url[:-4]
    return url


def immich_request(server_url: str, api_key: str, endpoint: str, method: str = "GET", payload: dict | list | None = None) -> tuple[bool, int, any]:
    root_url = _immich_base_url(server_url)
    if not root_url:
        return False, 0, "Missing Server Address"
    
    if not endpoint.startswith("/"):
        endpoint = "/" + endpoint
    
    # Ensure /api prefix if not already present
    if not endpoint.startswith("/api/") and not endpoint.startswith("/api"):
        full_url = f"{root_url}/api{endpoint}"
    else:
        full_url = f"{root_url}{endpoint}"

    headers = {
        "Accept": "application/json",
        "User-Agent": "PicCuratorStudio/4.0",
    }
    if api_key.strip():
        headers["x-api-key"] = api_key.strip()

    data_bytes = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data_bytes = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(full_url, data=data_bytes, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
            res_json = json.loads(body) if body else {}
            return True, resp.status, res_json
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore") if hasattr(e, "read") else ""
        try:
            err_json = json.loads(body)
            msg = err_json.get("message") or err_json.get("error") or str(e)
        except Exception:
            msg = f"HTTP {e.code}: {e.reason}"
        return False, e.code, msg
    except urllib.error.URLError as e:
        return False, 0, f"Connection Error: {e.reason}"
    except Exception as e:
        return False, 0, str(e)


def immich_get_people(server_url: str, api_key: str) -> tuple[bool, list[dict] | str]:
    """Retrieve all recognized people from Immich."""
    endpoints = ["/people", "/person"]
    for ep in endpoints:
        ok, status, res = immich_request(server_url, api_key, ep)
        if ok:
            if isinstance(res, list):
                return True, res
            elif isinstance(res, dict) and "people" in res:
                return True, res["people"]
    return False, "Failed to retrieve people list from Immich."


def immich_get_person_assets(server_url: str, api_key: str, person_id: str) -> tuple[bool, list[dict] | str]:
    """Retrieve all assets associated with a specific person ID."""
    # Method 1: GET /people/{id}/assets or GET /person/{id}/assets
    endpoints = [f"/people/{person_id}/assets", f"/person/{person_id}/assets"]
    for ep in endpoints:
        ok, status, res = immich_request(server_url, api_key, ep)
        if ok and isinstance(res, list):
            return True, res
    
    # Method 2: POST /search/metadata with personIds filter
    ok, status, res = immich_request(server_url, api_key, "/search/metadata", method="POST", payload={"personIds": [person_id]})
    if ok:
        if isinstance(res, dict) and "assets" in res and "items" in res["assets"]:
            return True, res["assets"]["items"]
        elif isinstance(res, list):
            return True, res
        elif isinstance(res, dict) and "items" in res:
            return True, res["items"]
            
    return False, f"Could not fetch assets for person {person_id}."


def immich_get_tags(server_url: str, api_key: str) -> tuple[bool, list[dict] | str]:
    """Retrieve all tags from Immich."""
    ok, status, res = immich_request(server_url, api_key, "/tags")
    if ok and isinstance(res, list):
        return True, res
    return False, str(res)


def immich_create_tag(server_url: str, api_key: str, tag_name: str) -> tuple[bool, str]:
    """Create a new tag in Immich."""
    ok, status, res = immich_request(server_url, api_key, "/tags", method="POST", payload={"name": tag_name, "type": "USER"})
    if ok:
        return True, f"Tag '{tag_name}' created successfully."
    return False, str(res)


def immich_add_tag_to_asset(server_url: str, api_key: str, tag_id: str, asset_id: str) -> tuple[bool, str]:
    """Assign a tag to an asset."""
    ok, status, res = immich_request(server_url, api_key, f"/tags/{tag_id}/assets", method="PUT", payload={"ids": [asset_id]})
    if ok:
        return True, f"Tag applied to asset."
    return False, str(res)


def immich_get_albums(server_url: str, api_key: str) -> tuple[bool, list[dict] | str]:
    """Retrieve all albums from Immich."""
    ok, status, res = immich_request(server_url, api_key, "/albums")
    if ok and isinstance(res, list):
        return True, res
    return False, str(res)


def immich_create_album(server_url: str, api_key: str, album_name: str) -> tuple[bool, str]:
    """Create a new album in Immich."""
    ok, status, res = immich_request(server_url, api_key, "/albums", method="POST", payload={"albumName": album_name})
    if ok:
        return True, f"Album '{album_name}' created successfully."
    return False, str(res)


def immich_add_asset_to_album(server_url: str, api_key: str, album_id: str, asset_id: str) -> tuple[bool, str]:
    """Add an asset to an album."""
    ok, status, res = immich_request(server_url, api_key, f"/albums/{album_id}/assets", method="PUT", payload={"ids": [asset_id]})
    if ok:
        return True, "Asset added to album."
    return False, str(res)


def immich_get_asset_info(server_url: str, api_key: str, asset_id: str) -> tuple[bool, dict | str]:
    """Retrieve metadata for a specific asset by ID."""
    endpoints = [f"/assets/{asset_id}", f"/asset/info/{asset_id}"]
    for ep in endpoints:
        ok, status, res = immich_request(server_url, api_key, ep)
        if ok and isinstance(res, dict):
            return True, res
    return False, f"Asset ID {asset_id} not found."


def immich_get_recent_assets(server_url: str, api_key: str, limit: int = 30) -> tuple[bool, list[dict] | str]:
    """Fetch recent assets from Immich."""
    # Method 1: GET /assets
    ok, status, res = immich_request(server_url, api_key, "/assets")
    if ok and isinstance(res, list):
        return True, res[:limit]
    
    # Method 2: POST /search/metadata
    ok, status, res = immich_request(server_url, api_key, "/search/metadata", method="POST", payload={"take": limit})
    if ok:
        if isinstance(res, dict) and "assets" in res and "items" in res["assets"]:
            return True, res["assets"]["items"]
        elif isinstance(res, dict) and "items" in res:
            return True, res["items"]
            
    return False, "Could not fetch assets."

def immich_smart_search(server_url: str, api_key: str, query: str, limit: int = 250) -> tuple[bool, list[dict] | str]:
    """Search assets in Immich using the smart/AI search endpoint."""
    import urllib.parse
    q_enc = urllib.parse.quote(query)
    
    # Try GET /search/smart
    ok, status, res = immich_request(server_url, api_key, f"/search/smart?q={q_enc}&size={limit}")
    if ok:
        if isinstance(res, dict) and "assets" in res and "items" in res["assets"]:
            return True, res["assets"]["items"]
        elif isinstance(res, list):
            return True, res
        elif isinstance(res, dict) and "items" in res:
            return True, res["items"]
            
    # Try POST /search/smart
    ok, status, res = immich_request(server_url, api_key, "/search/smart", method="POST", payload={"query": query, "size": limit})
    if ok:
        if isinstance(res, dict) and "assets" in res and "items" in res["assets"]:
            return True, res["assets"]["items"]
        elif isinstance(res, list):
            return True, res
        elif isinstance(res, dict) and "items" in res:
            return True, res["items"]
            
    # Try POST /search/metadata as fallback
    ok, status, res = immich_request(server_url, api_key, "/search/metadata", method="POST", payload={"q": query, "withMetadata": True, "size": limit})
    if ok:
        if isinstance(res, dict) and "assets" in res and "items" in res["assets"]:
            return True, res["assets"]["items"]
        elif isinstance(res, list):
            return True, res
        elif isinstance(res, dict) and "items" in res:
            return True, res["items"]
            
    return False, "Could not perform smart search."


def immich_download_thumbnail(server_url: str, api_key: str, asset_id: str) -> bytes | None:
    """Download thumbnail image bytes for an asset."""
    root_url = _immich_base_url(server_url)
    if not root_url:
        return None

    endpoints = [
        f"{root_url}/api/assets/{asset_id}/thumbnail",
        f"{root_url}/api/asset/file/{asset_id}?isThumbnail=true",
        f"{root_url}/api/assets/{asset_id}/original",
    ]
    headers = {"User-Agent": "PicCuratorStudio/4.0"}
    if api_key.strip():
        headers["x-api-key"] = api_key.strip()

    for ep in endpoints:
        try:
            req = urllib.request.Request(ep, headers=headers)
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    return resp.read()
        except Exception:
            continue
    return None


def immich_upload_asset(server_url: str, api_key: str, file_path: str) -> tuple[bool, str]:
    """Upload a local image file to Immich via multipart/form-data POST."""
    root_url = _immich_base_url(server_url)
    if not root_url:
        return False, "Missing Server Address"

    path = Path(file_path)
    if not path.exists():
        return False, f"File not found: {file_path}"

    boundary = f"----PicCuratorBoundary{int(time.time()*1000)}"
    body_parts = []

    def add_field(name, value):
        body_parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode("utf-8"))

    # File metadata fields
    mtime = path.stat().st_mtime
    iso_time = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(mtime))

    add_field("deviceAssetId", f"{path.stem}-{int(time.time())}")
    add_field("deviceId", "PicCuratorStudio")
    add_field("fileCreatedAt", iso_time)
    add_field("fileModifiedAt", iso_time)
    add_field("isFavorite", "false")

    # File binary field
    mime_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
    file_header = f"--{boundary}\r\nContent-Disposition: form-data; name=\"assetData\"; filename=\"{path.name}\"\r\nContent-Type: {mime_type}\r\n\r\n".encode("utf-8")
    
    try:
        with open(path, "rb") as f:
            file_data = f.read()
    except Exception as e:
        return False, f"Failed to read file: {e}"

    file_footer = b"\r\n"
    end_boundary = f"--{boundary}--\r\n".encode("utf-8")

    full_body = b"".join(body_parts) + file_header + file_data + file_footer + end_boundary

    upload_url = f"{root_url}/api/assets"
    headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Accept": "application/json",
        "User-Agent": "PicCuratorStudio/4.0",
    }
    if api_key.strip():
        headers["x-api-key"] = api_key.strip()

    req = urllib.request.Request(upload_url, data=full_body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
            res_json = json.loads(body) if body else {}
            asset_id = res_json.get("id") or "uploaded"
            return True, f"Uploaded successfully! Asset ID: {asset_id}"
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore") if hasattr(e, "read") else ""
        try:
            err_json = json.loads(body)
            msg = err_json.get("message") or err_json.get("error") or str(e)
        except Exception:
            msg = f"HTTP {e.code}: {e.reason}"
        return False, msg
    except urllib.error.URLError as e:
        return False, f"Connection Failed: {e.reason}"
    except Exception as e:
        return False, str(e)

