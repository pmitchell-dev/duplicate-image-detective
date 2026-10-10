"""
scanner.py — Background duplicate image scanner for picCurator Studio.

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
TAG_XP_COMMENT   = 0x9C9C   # Windows XP Comment
TAG_IMAGE_DESC   = 0x010E   # Standard EXIF ImageDescription
TAG_MODIFY_DATE  = 0x0132   # ModifyDate
EXIF_IFD_POINTER = 0x8769

# ExifIFD tags
TAG_USER_COMMENT = 0x9286
TAG_DATETIME_ORIGINAL = 0x9003
TAG_CREATE_DATE = 0x9004


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


def build_immich_xmp_bytes(flat_tags: list[str], hierarchical_tags: list[str], description: str = "", date: str = "") -> bytes:
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
        use_ai_scan: bool = False,
        ai_detection_distance: float = 0.05,
    ):
        self.root_dir = root_dir
        self.result_queue = result_queue
        self.stats = stats
        self.hash_threshold = hash_threshold
        self.use_ai_scan = use_ai_scan
        self.ai_detection_distance = ai_detection_distance
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

            # Phase 1: compute hashes/embeddings for all images
            hashed_phash = []
            hashed_ai = []
            
            if self.use_ai_scan:
                import json
                cache_file = Path(self.root_dir) / ".piccurator_ai_cache.json"
                cache_data = {}
                if cache_file.exists():
                    try:
                        with open(cache_file, "r", encoding="utf-8") as f:
                            cache_data = json.load(f)
                    except Exception:
                        pass
                
                cache_updated = False
                
                for path in image_paths:
                    if self._stop_event.is_set():
                        # Try to save cache before exiting early
                        if cache_updated:
                            try:
                                with open(cache_file, "w", encoding="utf-8") as f:
                                    json.dump(cache_data, f)
                            except Exception:
                                pass
                        return
                    
                    try:
                        rel_path = path.relative_to(self.root_dir).as_posix()
                        mtime = path.stat().st_mtime
                    except Exception:
                        self.stats.inc_processed()
                        continue
                        
                    if rel_path in cache_data and cache_data[rel_path].get("mtime") == mtime:
                        emb = cache_data[rel_path].get("vector")
                    else:
                        emb = self._compute_ai_embedding(path)
                        if emb is not None:
                            cache_data[rel_path] = {"mtime": mtime, "vector": emb}
                            cache_updated = True
                            
                    if emb is not None:
                        hashed_ai.append((emb, path))
                        
                    self.stats.inc_processed()
                    
                # Save cache at the end of the run
                if cache_updated:
                    try:
                        with open(cache_file, "w", encoding="utf-8") as f:
                            json.dump(cache_data, f)
                    except Exception:
                        pass
            else:
                for path in image_paths:
                    if self._stop_event.is_set():
                        return
                    h = self._compute_hash(path)
                    if h is not None:
                        hashed_phash.append((h, path))
                    self.stats.inc_processed()

            # Phase 2: emit all pairs within threshold distance
            if not self._stop_event.is_set():
                if self.use_ai_scan:
                    self._emit_ai_pairs(hashed_ai)
                else:
                    self._emit_pairs(hashed_phash)
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
        Emit clusters of duplicate paths.
        """
        if self.hash_threshold == 0:
            buckets: dict[str, list[Path]] = {}
            for h, p in hashed:
                buckets.setdefault(str(h), []).append(p)
            for paths in buckets.values():
                if len(paths) > 1:
                    if self._stop_event.is_set():
                        return
                    self.result_queue.put(paths)
                    self.stats.inc_pairs(len(paths) - 1)
        else:
            parent = {i: i for i in range(len(hashed))}
            def find(i):
                if parent[i] == i:
                    return i
                parent[i] = find(parent[i])
                return parent[i]
            def union(i, j):
                root_i = find(i)
                root_j = find(j)
                if root_i != root_j:
                    parent[root_i] = root_j

            for i in range(len(hashed)):
                if self._stop_event.is_set():
                    return
                hi, pi = hashed[i]
                for j in range(i + 1, len(hashed)):
                    hj, pj = hashed[j]
                    if hi - hj <= self.hash_threshold:
                        union(i, j)
            
            groups = {}
            for i in range(len(hashed)):
                root = find(i)
                groups.setdefault(root, []).append(hashed[i][1])
            
            for paths in groups.values():
                if len(paths) > 1:
                    self.result_queue.put(paths)
                    self.stats.inc_pairs(len(paths) - 1)

    def _compute_ai_embedding(self, path: Path) -> list[float] | None:
        import mimetypes
        import time
        import urllib.request
        import json
        import io
        from PIL import Image

        boundary = f"----PicCuratorAIBoundary{int(time.time()*1000)}"
        entries_json = json.dumps({"clip": {"visual": {"modelName": "ViT-B-32__openai"}}})
        
        body_parts = []
        body_parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"entries\"\r\n\r\n{entries_json}\r\n".encode("utf-8"))
        
        # Open the image, convert to RGB (strips alpha/16-bit), and downscale to 512x512.
        # This guarantees TIFF compatibility and reduces 50MB files to 50KB for fast networking.
        try:
            with Image.open(path) as img:
                img = img.convert("RGB")
                img.thumbnail((512, 512), Image.Resampling.LANCZOS)
                img_io = io.BytesIO()
                img.save(img_io, format="JPEG", quality=85)
                file_data = img_io.getvalue()
        except Exception:
            return None
            
        file_header = f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"image.jpg\"\r\nContent-Type: image/jpeg\r\n\r\n".encode("utf-8")
        file_footer = b"\r\n"
        end_boundary = f"--{boundary}--\r\n".encode("utf-8")
        full_body = b"".join(body_parts) + file_header + file_data + file_footer + end_boundary
        
        headers = {
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Accept": "application/json",
            "User-Agent": "PicCuratorStudio/4.0",
        }
        
        req = urllib.request.Request("http://localhost:3003/predict", data=full_body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read().decode("utf-8", errors="ignore")
                res_json = json.loads(body)
                def _find_list(d):
                    if isinstance(d, list):
                        return d
                    if isinstance(d, dict):
                        for v in d.values():
                            res = _find_list(v)
                            if res is not None:
                                return res
                    return None
                
                emb = _find_list(res_json)
                if emb and isinstance(emb, list) and len(emb) > 10:
                    # Pre-normalize the vector to make comparison O(N) fast without square roots
                    norm = sum(x * x for x in emb) ** 0.5
                    if norm == 0: return emb
                    return [x / norm for x in emb]
                return None
        except Exception as e:
            return None

    def _emit_ai_pairs(self, hashed_ai: list[tuple[list[float], Path]]):
        def cosine_sim(a, b):
            # Since vectors are pre-normalized, cosine similarity is just the dot product
            return sum(x * y for x, y in zip(a, b))
            
        sim_threshold = 1.0 - self.ai_detection_distance

        parent = {i: i for i in range(len(hashed_ai))}
        def find(i):
            if parent[i] == i:
                return i
            parent[i] = find(parent[i])
            return parent[i]
        def union(i, j):
            root_i = find(i)
            root_j = find(j)
            if root_i != root_j:
                parent[root_i] = root_j

        for i in range(len(hashed_ai)):
            if self._stop_event.is_set():
                return
            embi, pi = hashed_ai[i]
            for j in range(i + 1, len(hashed_ai)):
                embj, pj = hashed_ai[j]
                if cosine_sim(embi, embj) >= sim_threshold:
                    union(i, j)

        groups = {}
        for i in range(len(hashed_ai)):
            root = find(i)
            groups.setdefault(root, []).append(hashed_ai[i][1])
            
        for paths in groups.values():
            if len(paths) > 1:
                self.result_queue.put(paths)
                self.stats.inc_pairs(len(paths) - 1)


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

def immich_get_duplicates(server_url: str, api_key: str) -> tuple[bool, list[dict] | str]:
    """Retrieve duplicate asset groups from Immich."""
    endpoints = ["/duplicates"]
    for ep in endpoints:
        ok, status, res = immich_request(server_url, api_key, ep)
        if ok:
            if isinstance(res, list):
                return True, res
            elif isinstance(res, dict) and "duplicates" in res:
                return True, res["duplicates"]
    return False, "Failed to retrieve duplicates from Immich."


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
    
    all_assets = []
    page = 1
    size = limit if limit > 0 else 250
    working_method = None
    
    while True:
        current_assets = []
        ok = False
        res = None
        
        # Try GET /search/smart
        if working_method is None or working_method == "get_smart":
            ok, status, res = immich_request(server_url, api_key, f"/search/smart?q={q_enc}&size={size}&page={page}")
            if ok:
                working_method = "get_smart"
                
        # Try POST /search/smart
        if not ok and (working_method is None or working_method == "post_smart"):
            ok, status, res = immich_request(server_url, api_key, "/search/smart", method="POST", payload={"query": query, "size": size, "page": page})
            if ok:
                working_method = "post_smart"
                
        # Try POST /search/metadata as fallback
        if not ok and (working_method is None or working_method == "post_metadata"):
            ok, status, res = immich_request(server_url, api_key, "/search/metadata", method="POST", payload={"q": query, "withMetadata": True, "size": size, "page": page})
            if ok:
                working_method = "post_metadata"
                
        if not ok:
            if page == 1:
                return False, "Could not perform smart search."
            else:
                break
                
        # Parse results
        if isinstance(res, dict) and "assets" in res and "items" in res["assets"]:
            current_assets = res["assets"]["items"]
        elif isinstance(res, list):
            current_assets = res
        elif isinstance(res, dict) and "items" in res:
            current_assets = res["items"]
            
        if not current_assets:
            break
            
        all_assets.extend(current_assets)
        
        if len(current_assets) < size:
            break
            
        page += 1
        
    return True, all_assets


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
