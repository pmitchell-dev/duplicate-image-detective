"""
scanner.py — Background duplicate image scanner for Duplicate Image Detective.

Uses perceptual hashing (pHash) to find visually identical images even if
they differ in file format, compression, or metadata.
"""
from __future__ import annotations

import os
import queue
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
        paths = []
        for dirpath, _dirs, filenames in os.walk(self.root_dir):
            for filename in filenames:
                if Path(filename).suffix.lower() in IMAGE_EXTENSIONS:
                    paths.append(Path(dirpath) / filename)
        return paths

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
