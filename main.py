"""
main.py — Duplicate Image Detective
A Tkinter application for finding and managing near-duplicate images.
"""
from __future__ import annotations

import json
import os
import queue
import sys
import threading
import tkinter as tk
import urllib.error
import urllib.request
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageDraw, ImageTk

from scanner import (
    SCAN_DONE,
    DuplicateScanner,
    ScanStats,
    collect_image_paths,
    collect_images_by_folder,
    read_image_tags,
    write_image_tags,
    scan_directory_keywords,
    immich_get_people,
    immich_get_person_assets,
    immich_get_tags,
    immich_create_tag,
    immich_add_tag_to_asset,
    immich_get_albums,
    immich_create_album,
    immich_add_asset_to_album,
    immich_get_asset_info,
    immich_get_recent_assets,
    immich_download_thumbnail,
    immich_upload_asset,
)


def test_immich_connection(server_url: str, api_key: str) -> tuple[bool, str]:
    """
    Test connectivity to an Immich server instance with robust multi-endpoint probing.
    Returns (success: bool, message: str).
    """
    raw_url = server_url.strip().rstrip("/")
    if not raw_url:
        return False, "Server Address is required."
    if not (raw_url.startswith("http://") or raw_url.startswith("https://")):
        raw_url = "http://" + raw_url

    # Standardize root_url (strip trailing /api if user included it in base address)
    if raw_url.endswith("/api"):
        root_url = raw_url[:-4]
    else:
        root_url = raw_url

    key = api_key.strip()

    # User Auth endpoints to attempt if key is present (plural /users/me is standard in Immich)
    user_endpoints = [
        f"{root_url}/api/users/me",
        f"{root_url}/users/me",
        f"{root_url}/api/user/me",
    ]

    # Server Info / Ping endpoints
    ping_endpoints = [
        f"{root_url}/api/server/ping",
        f"{root_url}/api/server-info/ping",
        f"{root_url}/api/server/version",
        f"{root_url}/api/server/about",
        f"{root_url}/server/ping",
        f"{root_url}/server/version",
    ]

    def make_request(target_url: str) -> tuple[int, dict]:
        req = urllib.request.Request(target_url)
        if key:
            req.add_header("x-api-key", key)
        req.add_header("Accept", "application/json")
        req.add_header("User-Agent", "PicCuratorStudio/5.0")
        with urllib.request.urlopen(req, timeout=6) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
            try:
                data = json.loads(body) if body else {}
            except Exception:
                data = {}
            return resp.status, data

    # 1. If key is provided, try authenticating via user profile endpoints first
    if key:
        for endpoint in user_endpoints:
            try:
                status, data = make_request(endpoint)
                if isinstance(data, dict):
                    user_name = data.get("name") or data.get("email") or data.get("userEmail")
                    if user_name:
                        return True, f"Connected! Authenticated as '{user_name}'."
                    elif "id" in data or "email" in data:
                        return True, "Connected! API key validated successfully."
                return True, "Connected! Immich session verified."
            except urllib.error.HTTPError as e:
                if e.code in (401, 403):
                    return False, f"HTTP {e.code}: Invalid API Key or Unauthorized."
                # 404 means this endpoint format didn't match, continue probing alternative formats
                continue
            except urllib.error.URLError as e:
                return False, f"Connection Failed: {e.reason}"
            except Exception as e:
                return False, f"Error: {e}"

    # 2. Try ping / version endpoints (works with or without API key)
    for endpoint in ping_endpoints:
        try:
            status, data = make_request(endpoint)
            if isinstance(data, dict):
                if data.get("res") == "pong":
                    return True, "Server Connected (Ping OK)."
                if "version" in data:
                    return True, f"Server Reachable (Immich {data['version']})."
                if "major" in data:
                    ver = f"{data.get('major', 1)}.{data.get('minor', 0)}.{data.get('patch', 0)}"
                    return True, f"Server Reachable (Immich v{ver})."
            return True, "Server Connected (HTTP 200)."
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                return False, f"HTTP {e.code}: Unauthorized."
            continue
        except urllib.error.URLError as e:
            return False, f"Connection Failed: {e.reason}"
        except Exception:
            continue

    return False, "HTTP 404: Endpoint not found. Check server address."


def get_app_dir() -> Path:
    """Return directory containing the executable or main script."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


def get_immich_config_file() -> Path:
    """Return path to immich_config.json located beside the executable/script."""
    return get_app_dir() / "immich_config.json"

# ─────────────────────────────────────────────────────────────────────────────
# Constants / palette
# ─────────────────────────────────────────────────────────────────────────────
# Nord-inspired palette (comfortable, balanced)
BG_DARK      = "#2e3440"   # Polar Night (darkest)
BG_PANEL     = "#3b4252"   # Polar Night (darker)
BG_CARD      = "#434c5e"   # Polar Night (dark)
ACCENT_BLUE  = "#88c0d0"   # Frost (cyan/blue)
ACCENT_GREEN = "#a3be8c"   # Aurora (green)
ACCENT_RED   = "#bf616a"   # Aurora (red)
ACCENT_AMBER = "#d08770"   # Aurora (orange)
TEXT_MAIN    = "#eceff4"   # Snow Storm (lightest)
TEXT_DIM     = "#d8dee9"   # Snow Storm (light)
FONT_FAMILY  = "Segoe UI"

# Action button colors (harmonious with Nord)
COLOR_KEEP       = "#5e81ac"   # Nord Blue (frost deep)
COLOR_TRASH      = "#d08770"   # Nord Orange (aurora)
COLOR_BOTH_KEEP  = "#81a1c1"   # Nord Blue (frost lighter)
COLOR_BOTH_TRASH = "#bf616a"   # Nord Red (aurora)
COLOR_PERM_DEL   = "#4c566a"   # Polar Night (lighter grey)

HASH_THRESHOLD  = 6           # ≤6 bits difference → duplicate
POLL_MS         = 200         # UI queue-poll interval (ms)
FLASH_MS        = 450         # ms the green flash shows before images advance
PREVIEW_SIZE    = (460, 520)  # max canvas size (px)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers: file operations & formatting
# ─────────────────────────────────────────────────────────────────────────────
def send_to_trash(path: Path) -> bool:
    """Returns True on success, False if the file was already gone."""
    if not path.exists():
        return False
    try:
        import send2trash
        send2trash.send2trash(str(path))
        return True
    except Exception as e:
        messagebox.showerror("Trash Error", f"Could not recycle:\n{path}\n\n{e}")
        return False


def delete_permanent(path: Path) -> bool:
    """Permanently deletes a file. Returns True on success."""
    if not path.exists():
        return False
    try:
        path.unlink()
        return True
    except Exception as e:
        messagebox.showerror("Delete Error", f"Could not delete:\n{path}\n\n{e}")
        return False


def format_file_size(size_bytes: int) -> str:
    """Return a human-readable file size string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.2f} MB"


# ─────────────────────────────────────────────────────────────────────────────
# Image panel helper
def _create_arrow_photo(direction: str, hovered: bool = False) -> ImageTk.PhotoImage:
    """Generate a rounded semi-transparent dark pill with a crisp arrow chevron for on-canvas navigation."""
    w, h = 48, 64
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    bg_color = (15, 23, 42, 205) if hovered else (15, 23, 42, 120)
    draw.rounded_rectangle([0, 0, w - 1, h - 1], radius=14, fill=bg_color)

    arrow_color = (255, 255, 255, 255) if hovered else (240, 243, 248, 200)
    if direction == "left":
        points = [(w // 2 + 5, 18), (w // 2 - 5, h // 2), (w // 2 + 5, h - 18)]
    else:
        points = [(w // 2 - 5, 18), (w // 2 + 5, h // 2), (w // 2 - 5, h - 18)]

    draw.line([points[0], points[1], points[2]], fill=arrow_color, width=4)
    return ImageTk.PhotoImage(img)


# ─────────────────────────────────────────────────────────────────────────────
class ImagePanel(tk.Frame):
    """A framed canvas that displays a scaled image with scroll-wheel zoom."""

    ZOOM_STEP = 1.15   # multiply zoom by this per scroll tick
    ZOOM_MIN  = 0.05   # never zoom out further than 5 % of original
    ZOOM_MAX  = 12.0   # cap at 12×

    def __init__(
        self,
        master,
        label_text: str,
        rotate_hotkey: str = "",
        preview_size: tuple[int, int] = PREVIEW_SIZE,
        on_prev: Callable[[], None] | None = None,
        on_next: Callable[[], None] | None = None,
        **kwargs,
    ):
        super().__init__(master, bg=BG_PANEL, **kwargs)
        self.preview_size = preview_size
        self._photo   = None   # ImageTk reference (prevent GC)
        self._orig    = None   # original PIL.Image (full resolution)
        self._zoom    = 1.0    # current zoom factor
        self._pan_x   = 0.0   # image-origin x in canvas pixels
        self._pan_y   = 0.0   # image-origin y in canvas pixels

        self.on_prev = on_prev
        self.on_next = on_next
        self._hover_prev = False
        self._hover_next = False

        if self.on_prev and self.on_next:
            self._img_prev_norm = _create_arrow_photo("left", False)
            self._img_prev_hov  = _create_arrow_photo("left", True)
            self._img_next_norm = _create_arrow_photo("right", False)
            self._img_next_hov  = _create_arrow_photo("right", True)

        # Header label
        tk.Label(
            self,
            text=label_text,
            font=(FONT_FAMILY, 11, "bold"),
            bg=BG_PANEL,
            fg=ACCENT_GREEN,
        ).pack(pady=(8, 2))

        # Canvas
        self.canvas = tk.Canvas(
            self,
            width=self.preview_size[0],
            height=self.preview_size[1],
            bg=BG_CARD,
            highlightthickness=1,
            highlightbackground=BG_CARD,
            relief="flat",
        )
        self.canvas.pack(padx=15, pady=8)

        # Scroll-zoom binding (Windows: MouseWheel)
        self.canvas.bind("<MouseWheel>", self._on_scroll)
        # Also catch Linux / X11 buttons 4 & 5 in case
        self.canvas.bind("<Button-4>", self._on_scroll)
        self.canvas.bind("<Button-5>", self._on_scroll)

        # Filename label
        self.lbl_filename = tk.Label(
            self,
            text="—",
            font=(FONT_FAMILY, 9, "bold"),
            bg=BG_PANEL,
            fg=TEXT_MAIN,
            wraplength=self.preview_size[0],
        )
        self.lbl_filename.pack(pady=(2, 0))

        # Full path label
        self.lbl_path = tk.Label(
            self,
            text="",
            font=(FONT_FAMILY, 8),
            bg=BG_PANEL,
            fg=TEXT_DIM,
            wraplength=self.preview_size[0],
        )
        self.lbl_path.pack(pady=(0, 6))

        # Rotate button
        self.btn_rotate = tk.Button(
            self,
            text=f"↻ ({rotate_hotkey})" if rotate_hotkey else "↻",
            font=(FONT_FAMILY, 12, "bold"),
            bg=BG_PANEL,
            fg=TEXT_MAIN,
            relief="flat",
            cursor="hand2",
            command=self.rotate_image,
        )
        self.btn_rotate.pack(pady=(0, 6))
        self.btn_rotate.bind("<Enter>", lambda e: self.btn_rotate.config(fg=ACCENT_BLUE))
        self.btn_rotate.bind("<Leave>", lambda e: self.btn_rotate.config(fg=TEXT_MAIN))

        # Match count label
        self.lbl_match_count = tk.Label(
            self,
            text="",
            font=(FONT_FAMILY, 9, "bold"),
            bg=BG_PANEL,
            fg=ACCENT_AMBER,
            wraplength=self.preview_size[0],
        )
        self.lbl_match_count.pack(pady=(0, 2))

        self._path = None

    # ── Public API ────────────────────────────────────────────────────────

    def load_image(self, path: Path):
        """Load *path* and display it at fit-zoom; enables scroll-wheel zoom."""
        try:
            self._path = path
            img = Image.open(path).convert("RGB")
            self._orig  = img
            self._zoom  = self._calc_fit_zoom()
            self._pan_x, self._pan_y = self._calc_centered_pan()
            self._render()
            self.lbl_filename.config(text=path.name)
            self.lbl_path.config(text=str(path))
        except Exception as e:
            self.clear()
            self.canvas.create_text(
                self.preview_size[0] // 2, self.preview_size[1] // 2,
                text=f"⚠ Cannot load image\n{path.name}\n{e}",
                fill=ACCENT_RED,
                font=(FONT_FAMILY, 10),
                justify="center",
            )

    def clear(self):
        """Reset to an empty state."""
        self.canvas.delete("all")
        self._photo = None
        self._orig  = None
        self._path = None
        self.lbl_filename.config(text="—")
        self.lbl_path.config(text="")
        self.lbl_match_count.config(text="")

    def flash_green(self, duration_ms: int = 750):
        """Briefly flash the canvas background green to confirm the keep choice."""
        self.canvas.config(bg="#3d7a52", highlightbackground="#3d7a52")
        self.after(duration_ms, lambda: self.canvas.config(bg=BG_CARD, highlightbackground=BG_CARD))

    def show_placeholder(self, text: str):
        """Show a centred text message; clears any loaded image."""
        self._orig = None
        self._path = None
        self.canvas.delete("all")
        self._photo = None
        self.canvas.create_text(
            self.preview_size[0] // 2, self.preview_size[1] // 2,
            text=text,
            fill=TEXT_DIM,
            font=(FONT_FAMILY, 12),
            justify="center",
            width=self.preview_size[0] - 20,
        )
        self.lbl_filename.config(text="—")
        self.lbl_path.config(text="")
        self.lbl_match_count.config(text="")

    def rotate_image(self):
        """Rotate the current image 90 degrees clockwise and save it."""
        if getattr(self, '_path', None) is None:
            return
            
        try:
            # Re-open original file to avoid saving over with lower quality or stripped metadata
            with Image.open(self._path) as img:
                rotated = img.transpose(Image.Transpose.ROTATE_270)
                kwargs = {}
                if "exif" in img.info:
                    kwargs["exif"] = img.info["exif"]
                if img.format in ["JPEG", "MPO"]:
                    kwargs["quality"] = 95
                rotated.save(self._path, **kwargs)
                
            # Re-load image into UI
            self.load_image(self._path)
        except Exception as e:
            messagebox.showerror("Rotate Error", f"Could not rotate image:\n{self._path}\n\n{e}")

    # ── Zoom / render internals ───────────────────────────────────────────

    def _calc_fit_zoom(self) -> float:
        """Zoom level that makes the image fill the canvas without distortion."""
        if self._orig is None:
            return 1.0
        iw, ih = self._orig.size
        cw, ch = self.preview_size
        return min(cw / iw, ch / ih)

    def _calc_centered_pan(self) -> tuple[float, float]:
        """Pan offset that centres the image at the current zoom."""
        if self._orig is None:
            return 0.0, 0.0
        iw, ih = self._orig.size
        cw, ch = self.preview_size
        return (cw - iw * self._zoom) / 2.0, (ch - ih * self._zoom) / 2.0

    def _clamp_pan(self):
        """
        Prevent the image from being panned fully off-screen.
        At least MARGIN pixels of the image must remain visible.
        """
        if self._orig is None:
            return
        MARGIN = 30
        iw, ih  = self._orig.size
        cw, ch  = self.preview_size
        zoomed_w = iw * self._zoom
        zoomed_h = ih * self._zoom
        self._pan_x = max(MARGIN - zoomed_w, min(self._pan_x, cw - MARGIN))
        self._pan_y = max(MARGIN - zoomed_h, min(self._pan_y, ch - MARGIN))

    def _render(self):
        """
        Crop the original image to the visible canvas region and scale it
        to the canvas size for display.  This keeps memory usage low at
        high zoom levels and avoids creating huge PhotoImages.
        """
        if self._orig is None:
            return

        iw, ih = self._orig.size
        cw, ch = self.preview_size
        z = self._zoom
        px, py = self._pan_x, self._pan_y

        # Source rect in original image pixels (clamped to image bounds)
        src_x1 = max(0.0, -px / z)
        src_y1 = max(0.0, -py / z)
        src_x2 = min(float(iw), (cw - px) / z)
        src_y2 = min(float(ih), (ch - py) / z)

        if src_x2 <= src_x1 or src_y2 <= src_y1:
            return  # image entirely off-screen

        # Destination size on canvas (integer pixels)
        dst_w = max(1, round((src_x2 - src_x1) * z))
        dst_h = max(1, round((src_y2 - src_y1) * z))

        # Crop original then resize to dst — NEAREST is fast at high zoom
        resamp = Image.NEAREST if z >= 3.0 else Image.LANCZOS
        tile = self._orig.crop((src_x1, src_y1, src_x2, src_y2))
        tile = tile.resize((dst_w, dst_h), resamp)

        self._photo = ImageTk.PhotoImage(tile)
        self.canvas.delete("all")
        # draw_x/y = where the visible tile starts on the canvas
        draw_x = max(0, round(px))
        draw_y = max(0, round(py))
        self.canvas.create_image(draw_x, draw_y, anchor="nw", image=self._photo)

        # Draw translucent navigation arrow overlays if callbacks are provided
        if self.on_prev and self.on_next:
            cy = ch // 2
            img_p = self._img_prev_hov if self._hover_prev else self._img_prev_norm
            img_n = self._img_next_hov if self._hover_next else self._img_next_norm

            self.canvas.create_image(32, cy, anchor="center", image=img_p, tags="btn_prev")
            self.canvas.create_image(cw - 32, cy, anchor="center", image=img_n, tags="btn_next")

            self.canvas.tag_bind("btn_prev", "<Button-1>", lambda e: self._on_arrow_click("prev"))
            self.canvas.tag_bind("btn_prev", "<Enter>", lambda e: self._on_arrow_hover("prev", True))
            self.canvas.tag_bind("btn_prev", "<Leave>", lambda e: self._on_arrow_hover("prev", False))

            self.canvas.tag_bind("btn_next", "<Button-1>", lambda e: self._on_arrow_click("next"))
            self.canvas.tag_bind("btn_next", "<Enter>", lambda e: self._on_arrow_hover("next", True))
            self.canvas.tag_bind("btn_next", "<Leave>", lambda e: self._on_arrow_hover("next", False))

    def _on_arrow_hover(self, which: str, is_hover: bool):
        if which == "prev":
            if self._hover_prev == is_hover:
                return
            self._hover_prev = is_hover
            img = self._img_prev_hov if is_hover else self._img_prev_norm
            try:
                self.canvas.itemconfig("btn_prev", image=img)
            except Exception:
                pass
        else:
            if self._hover_next == is_hover:
                return
            self._hover_next = is_hover
            img = self._img_next_hov if is_hover else self._img_next_norm
            try:
                self.canvas.itemconfig("btn_next", image=img)
            except Exception:
                pass

        any_hover = self._hover_prev or self._hover_next
        self.canvas.config(cursor="hand2" if any_hover else "")

    def _on_arrow_click(self, which: str):
        if which == "prev" and self.on_prev:
            self.on_prev()
        elif which == "next" and self.on_next:
            self.on_next()

    def _on_scroll(self, event):
        """Zoom in/out centred on the current mouse position."""
        if self._orig is None:
            return

        # Determine direction (Windows: event.delta; Linux: event.num)
        if hasattr(event, "delta") and event.delta:
            direction = 1 if event.delta > 0 else -1
        elif event.num == 4:
            direction = 1
        elif event.num == 5:
            direction = -1
        else:
            return

        old_zoom  = self._zoom
        new_zoom  = old_zoom * (self.ZOOM_STEP ** direction)
        fit_zoom  = self._calc_fit_zoom()
        new_zoom  = max(fit_zoom * 0.98, min(new_zoom, self.ZOOM_MAX))

        if abs(new_zoom - old_zoom) < 1e-6:
            return

        # Cursor position on canvas
        cx, cy = event.x, event.y

        # The image-space point under the cursor must stay under the cursor.
        # img_x = (cx - pan_x) / zoom  =>  pan_x_new = cx - img_x * new_zoom
        img_x = (cx - self._pan_x) / old_zoom
        img_y = (cy - self._pan_y) / old_zoom

        self._zoom  = new_zoom
        self._pan_x = cx - img_x * new_zoom
        self._pan_y = cy - img_y * new_zoom
        self._clamp_pan()
        self._render()


# ─────────────────────────────────────────────────────────────────────────────
# Main application window
# ─────────────────────────────────────────────────────────────────────────────
class ChopImageDialog(tk.Toplevel):
    def __init__(self, parent, image_path: Path, on_success):
        super().__init__(parent)
        self.title("Chop Image - Drag to draw rectangles")
        self.geometry("1000x800")
        self.configure(bg=BG_DARK)
        self.image_path = image_path
        self.on_success = on_success
        self.rects = []
        self.current_rect = None
        self.start_x = None
        self.start_y = None
        
        try:
            self.orig_image = Image.open(image_path)
            # Ensure orientation is preserved if possible
            if hasattr(self.orig_image, '_getexif'):
                self.orig_image = self._apply_exif_orientation(self.orig_image)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open image:\n{e}", parent=self)
            self.destroy()
            return
            
        # UI Setup
        top_bar = tk.Frame(self, bg=BG_DARK, height=50)
        top_bar.pack(fill="x", pady=5)
        
        btn_save = tk.Button(top_bar, text="✂ Save Chops", command=self.save_chops, bg=COLOR_BOTH_KEEP, fg="white", font=(FONT_FAMILY, 10, "bold"))
        btn_save.pack(side="left", padx=10)
        
        btn_clear = tk.Button(top_bar, text="Clear Last", command=self.clear_last, bg=COLOR_TRASH, fg="white", font=(FONT_FAMILY, 10))
        btn_clear.pack(side="left", padx=10)

        btn_clear_all = tk.Button(top_bar, text="Clear All", command=self.clear_all, bg=COLOR_TRASH, fg="white", font=(FONT_FAMILY, 10))
        btn_clear_all.pack(side="left", padx=10)
        
        lbl_hint = tk.Label(top_bar, text="Draw rectangles around the areas to extract. Each rectangle will become a new image.", bg=BG_DARK, fg=TEXT_DIM, font=(FONT_FAMILY, 9))
        lbl_hint.pack(side="left", padx=15)
        
        self.canvas = tk.Canvas(self, bg=BG_DARK_ALT, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, padx=10, pady=10)
        
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.bind("<Configure>", self.on_resize)
        
        self.tk_img = None
        self.scale_factor = 1.0
        self.img_x = 0
        self.img_y = 0
        
        # After initial size is set, display image
        self.after(200, self.update_image_display)

    def _apply_exif_orientation(self, img: Image.Image) -> Image.Image:
        try:
            exif = img._getexif()
            if exif:
                orientation = exif.get(274)
                if orientation == 3: img = img.rotate(180, expand=True)
                elif orientation == 6: img = img.rotate(270, expand=True)
                elif orientation == 8: img = img.rotate(90, expand=True)
        except:
            pass
        return img

    def on_resize(self, event):
        pass # Optional: debounce resize to redraw

    def update_image_display(self):
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        if cw < 10 or ch < 10:
            self.after(100, self.update_image_display)
            return
            
        ow, oh = self.orig_image.size
        ratio = min(cw / ow, ch / oh)
        self.scale_factor = ratio
        
        nw, nh = int(ow * ratio), int(oh * ratio)
        if nw == 0 or nh == 0:
            return
            
        try:
            resample_filter = Image.Resampling.LANCZOS
        except AttributeError:
            resample_filter = Image.LANCZOS
            
        resized = self.orig_image.resize((nw, nh), resample_filter)
        self.tk_img = ImageTk.PhotoImage(resized)
        
        self.img_x = (cw - nw) // 2
        self.img_y = (ch - nh) // 2
        
        self.canvas.delete("all")
        self.canvas.create_image(self.img_x, self.img_y, anchor="nw", image=self.tk_img)
        self.redraw_rects()

    def redraw_rects(self):
        # Clear existing
        self.canvas.delete("rect")
        for x0, y0, x1, y1 in self.rects:
            sx0 = self.img_x + x0 * self.scale_factor
            sy0 = self.img_y + y0 * self.scale_factor
            sx1 = self.img_x + x1 * self.scale_factor
            sy1 = self.img_y + y1 * self.scale_factor
            self.canvas.create_rectangle(sx0, sy0, sx1, sy1, outline=ACCENT_GREEN, width=3, tags="rect")
            
    def on_press(self, event):
        self.start_x = event.x
        self.start_y = event.y
        self.current_rect = self.canvas.create_rectangle(self.start_x, self.start_y, self.start_x, self.start_y, outline="red", width=2)
        
    def on_drag(self, event):
        if self.current_rect:
            self.canvas.coords(self.current_rect, self.start_x, self.start_y, event.x, event.y)
            
    def on_release(self, event):
        if self.current_rect:
            x0, y0, x1, y1 = self.start_x, self.start_y, event.x, event.y
            x0, x1 = sorted([x0, x1])
            y0, y1 = sorted([y0, y1])
            
            # Convert to original image coordinates
            ox0 = max(0, int((x0 - self.img_x) / self.scale_factor))
            oy0 = max(0, int((y0 - self.img_y) / self.scale_factor))
            ox1 = min(self.orig_image.width, int((x1 - self.img_x) / self.scale_factor))
            oy1 = min(self.orig_image.height, int((y1 - self.img_y) / self.scale_factor))
            
            # Only add if area is significant
            if ox1 - ox0 > 10 and oy1 - oy0 > 10:
                self.rects.append((ox0, oy0, ox1, oy1))
                
            self.canvas.delete(self.current_rect)
            self.current_rect = None
            self.redraw_rects()

    def clear_last(self):
        if self.rects:
            self.rects.pop()
            self.redraw_rects()
            
    def clear_all(self):
        self.rects.clear()
        self.redraw_rects()
        
    def save_chops(self):
        if not self.rects:
            messagebox.showinfo("No Chops", "Please draw at least one rectangle to chop the image.", parent=self)
            return
        
        new_files = []
        for i, (x0, y0, x1, y1) in enumerate(self.rects):
            crop = self.orig_image.crop((x0, y0, x1, y1))
            name = f"{self.image_path.stem}_chop_{i+1}{self.image_path.suffix}"
            out_path = self.image_path.parent / name
            
            # Avoid overwriting existing chops if multiple chops are done from the same original
            counter = 1
            while out_path.exists():
                name = f"{self.image_path.stem}_chop_{i+1}_{counter}{self.image_path.suffix}"
                out_path = self.image_path.parent / name
                counter += 1
                
            try:
                info = self.orig_image.info
                crop.save(out_path, **info)
            except:
                crop.save(out_path)
            new_files.append(out_path)
            
        self.on_success(new_files)
        self.destroy()

class DuplicateDetectiveApp(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title("PicCurator Studio — Detective, Viewer & Tag Manager")
        self.configure(bg=BG_DARK)
        self.minsize(1200, 720)
        self.resizable(True, True)

        # Mode state
        self._current_mode = "duplicates"  # "duplicates" | "folder_viewer"

        # Duplicate scanner internal state
        self._scan_queue: queue.Queue = queue.Queue()
        self._stats = ScanStats()
        self._match_counts: dict[Path, int] = {}
        self._scanner: DuplicateScanner | None = None
        self._pending_pairs: list[tuple[Path, Path]] = []
        self._current_pair: tuple[Path, Path] | None = None
        self._scan_running = False
        self._scan_done = False
        self._pair_index = 0  # displayed pair counter

        # Image viewer internal state
        self._fv_root_dir: Path | None = None
        self._fv_folders: dict[Path, list[Path]] = {}
        self._fv_folder_list: list[Path] = []
        self._fv_all_images: list[Path] = []
        self._fv_active_images: list[Path] = []
        self._fv_index: int = 0
        self._known_keywords: set[str] = set()
        self._fv_current_tags: list[str] = []

        # Mass Edit internal state
        self._me_root_dir: Path | None = None
        self._me_folders: dict[Path, list[Path]] = {}
        self._me_folder_list: list[Path] = []
        self._me_all_images: list[Path] = []
        self._me_active_images: list[Path] = []
        self._me_selected_indices: set[int] = set()
        self._me_last_clicked_index: int | None = None
        self._me_thumb_cache: dict[Path, ImageTk.PhotoImage] = {}
        self._me_tile_widgets: list[dict] = []

        # Immich internal state
        self.var_immich_url = tk.StringVar(value="http://localhost:2283")
        self.var_immich_key = tk.StringVar(value="")
        self.var_immich_status = tk.StringVar(value="Ready to test communication")
        self.var_immich_asset_id = tk.StringVar()
        self.var_immich_new_tag = tk.StringVar()
        self.var_immich_tag_target_asset = tk.StringVar()
        self.var_immich_new_album = tk.StringVar()
        self.var_immich_album_target_asset = tk.StringVar()
        self.var_immich_upload_file_path = tk.StringVar()
        self.var_immich_upload_status = tk.StringVar(value="No file selected")
        self.var_immich_person_filter = tk.StringVar()
        self.var_immich_local_path = tk.StringVar()
        self.var_immich_server_prefix = tk.StringVar(value="/mnt/backups/family_photos")
        self._immich_selected_person_id: str | None = None
        self._immich_selected_person_name: str | None = None
        self._immich_people_cache: list[dict] = []
        self._immich_thumb_cache: dict[str, ImageTk.PhotoImage] = {}

        # Immich query count StringVars
        self.var_immich_assets_count = tk.StringVar(value="Total found: 0 asset(s)")
        self.var_immich_tags_count = tk.StringVar(value="Total found: 0 tag(s)")
        self.var_immich_albums_count = tk.StringVar(value="Total found: 0 album(s)")
        self.var_immich_people_count = tk.StringVar(value="Total found: 0 person(s)")
        self.var_immich_person_assets_count = tk.StringVar(value="Total found: 0 asset(s)")

        # Load persisted Immich config if present (immich_config.json)
        self._load_immich_config()

        # Save config automatically whenever connection or path fields change
        self.var_immich_url.trace_add("write", lambda *args: self._save_immich_config())
        self.var_immich_key.trace_add("write", lambda *args: self._save_immich_config())
        self.var_immich_local_path.trace_add("write", lambda *args: self._save_immich_config())
        self.var_immich_server_prefix.trace_add("write", lambda *args: self._save_immich_config())

        self._build_ui()
        self._set_review_state(active=False)

        # Bind hotkeys
        self.bind("<Key>", self._on_key_press)

    def _load_immich_config(self):
        cfg_file = get_immich_config_file()
        if cfg_file.exists():
            try:
                with open(cfg_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        url = data.get("url") or data.get("server_url")
                        key = data.get("api_key") or data.get("key")
                        loc_p = data.get("local_path") or data.get("local_root")
                        srv_p = data.get("server_prefix") or data.get("server_path")
                        if url:
                            self.var_immich_url.set(url)
                        if key:
                            self.var_immich_key.set(key)
                        if loc_p:
                            self.var_immich_local_path.set(loc_p)
                        if srv_p:
                            self.var_immich_server_prefix.set(srv_p)
                        saved_tags = data.get("saved_tags")
                        if isinstance(saved_tags, list):
                            for tag in saved_tags:
                                if isinstance(tag, str) and tag.strip():
                                    self._known_keywords.add(tag.strip())
            except Exception:
                pass

    def _save_immich_config(self):
        cfg_file = get_immich_config_file()
        try:
            payload = {
                "url": self.var_immich_url.get().strip(),
                "api_key": self.var_immich_key.get().strip(),
                "local_path": self.var_immich_local_path.get().strip(),
                "server_prefix": self.var_immich_server_prefix.get().strip(),
                "saved_tags": sorted(list(self._known_keywords)),
            }
            with open(cfg_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
        except Exception:
            pass

    def _scan_known_keywords(self, root_path: Path | str):
        """Scan directory in background thread to populate auto-completion keyword index."""
        def _bg_scan():
            try:
                kw = scan_directory_keywords(root_path)
                if kw:
                    self._known_keywords.update(kw)
                    self.after(0, self._save_immich_config)
                    self.after(0, self._fv_refresh_known_keywords_ui)
                    self.after(0, self._me_refresh_sidebar_ui)
            except Exception:
                pass
        threading.Thread(target=_bg_scan, daemon=True).start()

    # ── UI construction ────────────────────────────────────────────────────
    def _build_ui(self):
        self._build_topbar()
        self._build_main_area()
        self._build_statusbar()

    def _build_topbar(self):
        bar = tk.Frame(self, bg=BG_PANEL, pady=10)
        bar.pack(fill="x", side="top")

        # Mode selector buttons
        mode_frame = tk.Frame(bar, bg=BG_PANEL)
        mode_frame.pack(side="left", padx=(16, 12))

        self._btn_mode_dup = tk.Button(
            mode_frame,
            text="🔍 Duplicate Scanner",
            font=(FONT_FAMILY, 9, "bold"),
            relief="flat",
            cursor="hand2",
            padx=12,
            pady=6,
            command=lambda: self._switch_mode("duplicates"),
        )
        self._btn_mode_dup.pack(side="left", padx=(0, 4))

        self._btn_mode_fv = tk.Button(
            mode_frame,
            text="🖼️ Image Viewer",
            font=(FONT_FAMILY, 9, "bold"),
            relief="flat",
            cursor="hand2",
            padx=12,
            pady=6,
            command=lambda: self._switch_mode("folder_viewer"),
        )
        self._btn_mode_fv.pack(side="left", padx=(0, 4))

        self._btn_mode_me = tk.Button(
            mode_frame,
            text="🏷️ Mass Edit",
            font=(FONT_FAMILY, 9, "bold"),
            relief="flat",
            cursor="hand2",
            padx=12,
            pady=6,
            command=lambda: self._switch_mode("mass_edit"),
        )
        self._btn_mode_me.pack(side="left", padx=(0, 4))

        self._btn_mode_immich = tk.Button(
            mode_frame,
            text="⚡ Immich",
            font=(FONT_FAMILY, 9, "bold"),
            relief="flat",
            cursor="hand2",
            padx=12,
            pady=6,
            command=lambda: self._switch_mode("immich"),
        )
        self._btn_mode_immich.pack(side="left")

        # ── 1. Directory Header Controls (Visible in Duplicates/FolderViewer/MassEdit)
        self._frame_dir_controls = tk.Frame(bar, bg=BG_PANEL)
        self._frame_dir_controls.pack(side="left", fill="x", expand=True)

        tk.Label(
            self._frame_dir_controls,
            text="📁 Directory:",
            font=(FONT_FAMILY, 10, "bold"),
            bg=BG_PANEL,
            fg=ACCENT_GREEN,
        ).pack(side="left", padx=(4, 4))

        self.var_dir = tk.StringVar(value="No directory selected")
        tk.Label(
            self._frame_dir_controls,
            textvariable=self.var_dir,
            font=(FONT_FAMILY, 10),
            bg=BG_PANEL,
            fg=TEXT_MAIN,
            anchor="w",
        ).pack(side="left", fill="x", expand=True)

        self._btn_browse = self._make_button(
            self._frame_dir_controls, "Browse…", self._on_browse,
            fg=BG_DARK, bg=ACCENT_GREEN,
        )
        self._btn_browse.pack(side="right", padx=16)

        self._btn_scan = self._make_button(
            self._frame_dir_controls, "▶  Start Scan", self._on_start_scan,
            fg=BG_DARK, bg=ACCENT_BLUE,
        )
        self._btn_scan.pack(side="right", padx=(0, 6))
        self._btn_scan.config(state="disabled")

        # ── 2. Immich Connection Header Controls (Replaces Directory in Immich mode)
        self._frame_immich_header_controls = tk.Frame(bar, bg=BG_PANEL)
        # Packed dynamically when Immich mode is selected

        tk.Label(
            self._frame_immich_header_controls,
            text="Address:",
            font=(FONT_FAMILY, 9, "bold"),
            bg=BG_PANEL,
            fg=ACCENT_BLUE,
        ).pack(side="left", padx=(4, 4))

        self.entry_immich_url = tk.Entry(
            self._frame_immich_header_controls,
            textvariable=self.var_immich_url,
            font=(FONT_FAMILY, 9),
            bg=BG_CARD,
            fg=TEXT_MAIN,
            insertbackground=TEXT_MAIN,
            relief="flat",
            width=24,
        )
        self.entry_immich_url.pack(side="left", padx=(0, 10), ipady=3)

        tk.Label(
            self._frame_immich_header_controls,
            text="API Key:",
            font=(FONT_FAMILY, 9, "bold"),
            bg=BG_PANEL,
            fg=ACCENT_BLUE,
        ).pack(side="left", padx=(0, 4))

        self.entry_immich_key = tk.Entry(
            self._frame_immich_header_controls,
            textvariable=self.var_immich_key,
            font=(FONT_FAMILY, 9),
            bg=BG_CARD,
            fg=TEXT_MAIN,
            insertbackground=TEXT_MAIN,
            relief="flat",
            show="•",
            width=20,
        )
        self.entry_immich_key.pack(side="left", padx=(0, 10), ipady=3)

        self._btn_immich_test = self._make_button(
            self._frame_immich_header_controls,
            "⚡ Test Communication",
            self._on_immich_test_click,
            fg=BG_DARK,
            bg=ACCENT_BLUE,
        )
        self._btn_immich_test.pack(side="left", padx=(0, 10))

        self.lbl_immich_top_status = tk.Label(
            self._frame_immich_header_controls,
            textvariable=self.var_immich_status,
            font=(FONT_FAMILY, 9, "bold"),
            bg=BG_PANEL,
            fg=ACCENT_AMBER,
            anchor="w",
        )
        self.lbl_immich_top_status.pack(side="left", padx=(0, 10))

        self._update_mode_buttons()

    def _update_mode_buttons(self):
        if self._current_mode == "duplicates":
            self._btn_mode_dup.config(bg=ACCENT_BLUE, fg=BG_DARK)
            self._btn_mode_fv.config(bg=BG_CARD, fg=TEXT_MAIN)
            self._btn_mode_me.config(bg=BG_CARD, fg=TEXT_MAIN)
            self._btn_mode_immich.config(bg=BG_CARD, fg=TEXT_MAIN)

            self._frame_immich_header_controls.pack_forget()
            self._frame_dir_controls.pack(side="left", fill="x", expand=True)
            self._btn_scan.pack(side="right", padx=(0, 6))

        elif self._current_mode == "folder_viewer":
            self._btn_mode_fv.config(bg=ACCENT_BLUE, fg=BG_DARK)
            self._btn_mode_dup.config(bg=BG_CARD, fg=TEXT_MAIN)
            self._btn_mode_me.config(bg=BG_CARD, fg=TEXT_MAIN)
            self._btn_mode_immich.config(bg=BG_CARD, fg=TEXT_MAIN)

            self._frame_immich_header_controls.pack_forget()
            self._frame_dir_controls.pack(side="left", fill="x", expand=True)
            self._btn_scan.pack_forget()

        elif self._current_mode == "mass_edit":
            self._btn_mode_me.config(bg=ACCENT_BLUE, fg=BG_DARK)
            self._btn_mode_dup.config(bg=BG_CARD, fg=TEXT_MAIN)
            self._btn_mode_fv.config(bg=BG_CARD, fg=TEXT_MAIN)
            self._btn_mode_immich.config(bg=BG_CARD, fg=TEXT_MAIN)

            self._frame_immich_header_controls.pack_forget()
            self._frame_dir_controls.pack(side="left", fill="x", expand=True)
            self._btn_scan.pack_forget()

        else:  # "immich"
            self._btn_mode_immich.config(bg=ACCENT_BLUE, fg=BG_DARK)
            self._btn_mode_dup.config(bg=BG_CARD, fg=TEXT_MAIN)
            self._btn_mode_fv.config(bg=BG_CARD, fg=TEXT_MAIN)
            self._btn_mode_me.config(bg=BG_CARD, fg=TEXT_MAIN)

            self._frame_dir_controls.pack_forget()
            self._frame_immich_header_controls.pack(side="left", fill="x", expand=True)

    def _switch_mode(self, mode: str):
        if self._current_mode == mode:
            return
        self._current_mode = mode
        self._update_mode_buttons()

        dir_path = self.var_dir.get()
        has_dir = bool(dir_path and dir_path != "No directory selected" and os.path.isdir(dir_path))

        if mode == "duplicates":
            self._frame_fv_area.pack_forget()
            self._frame_me_area.pack_forget()
            self._frame_immich_area.pack_forget()
            self._frame_dup_area.pack(fill="both", expand=True, padx=20, pady=15)
            self._update_status("Switched to Duplicate Scanner mode.")
        elif mode == "folder_viewer":
            self._frame_dup_area.pack_forget()
            self._frame_me_area.pack_forget()
            self._frame_immich_area.pack_forget()
            self._frame_fv_area.pack(fill="both", expand=True, padx=20, pady=15)
            if has_dir:
                if self._fv_root_dir != Path(dir_path):
                    self._fv_load_directory(dir_path)
            else:
                self.panel_fv.show_placeholder("Please select a valid directory to browse images.")
                self.lbl_fv_counter.config(text="")
                self._fv_update_info_labels(None)
            self._update_status("Switched to Image Viewer mode.")
        elif mode == "mass_edit":
            self._frame_dup_area.pack_forget()
            self._frame_fv_area.pack_forget()
            self._frame_immich_area.pack_forget()
            self._frame_me_area.pack(fill="both", expand=True, padx=20, pady=15)
            if has_dir:
                if self._me_root_dir != Path(dir_path):
                    self._me_load_directory(dir_path)
            else:
                self._me_render_grid()
            self._update_status("Switched to Mass Edit mode.")
        else:  # "immich"
            self._frame_dup_area.pack_forget()
            self._frame_fv_area.pack_forget()
            self._frame_me_area.pack_forget()
            self._frame_immich_area.pack(fill="both", expand=True, padx=20, pady=15)
            self._update_status("Switched to Immich Integration mode.")

    def _build_main_area(self):
        self._main_container = tk.Frame(self, bg=BG_DARK)
        self._main_container.pack(fill="both", expand=True)

        # ── 1. Duplicate Scanner Area ─────────────────────
        self._frame_dup_area = tk.Frame(self._main_container, bg=BG_DARK)
        self._frame_dup_area.columnconfigure(0, weight=3)
        self._frame_dup_area.columnconfigure(1, weight=2)
        self._frame_dup_area.columnconfigure(2, weight=3)
        self._frame_dup_area.rowconfigure(0, weight=1)

        self.panel_left  = ImagePanel(self._frame_dup_area, "◀  Image 1", rotate_hotkey="Q")
        self.panel_left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))

        self._build_action_panel(self._frame_dup_area)

        self.panel_right = ImagePanel(self._frame_dup_area, "Image 2  ▶", rotate_hotkey="E")
        self.panel_right.grid(row=0, column=2, sticky="nsew", padx=(6, 0))

        self._frame_dup_area.pack(fill="both", expand=True, padx=20, pady=15)

        # ── 2. Image Viewer Area ─────────────────────────
        self._frame_fv_area = tk.Frame(self._main_container, bg=BG_DARK)
        self._build_folder_viewer_area(self._frame_fv_area)

        # ── 3. Mass Edit Area ─────────────────────────────
        self._frame_me_area = tk.Frame(self._main_container, bg=BG_DARK)
        self._build_mass_edit_area(self._frame_me_area)

        # ── 4. Immich Integration Area ────────────────────
        self._frame_immich_area = tk.Frame(self._main_container, bg=BG_DARK)
        self._build_immich_area(self._frame_immich_area)

    def _build_action_panel(self, parent):
        frame = tk.Frame(parent, bg=BG_PANEL, padx=16, pady=20)
        frame.grid(row=0, column=1, sticky="nsew")

        tk.Label(
            frame,
            text="Actions",
            font=(FONT_FAMILY, 13, "bold"),
            bg=BG_PANEL,
            fg=ACCENT_GREEN,
        ).pack(pady=(8, 4))

        # Pair counter
        self.lbl_pair_counter = tk.Label(
            frame,
            text="",
            font=(FONT_FAMILY, 9),
            bg=BG_PANEL,
            fg=TEXT_DIM,
        )
        self.lbl_pair_counter.pack(pady=(0, 10))

        self._action_buttons: list[tk.Button] = []

        # ── Keep Both — full-width green ─────────────────────
        btn_kb = self._make_button(
            frame, "✅  Keep Both (W)", self._act_keep_both,
            fg="#ffffff", bg=COLOR_BOTH_KEEP,
        )
        btn_kb.pack(fill="x", padx=12, pady=(0, 8))
        self._action_buttons.append(btn_kb)

        # ── Keep Left (A) — full-width green ─────────────────
        btn_kl = self._make_button(
            frame, "✅  Keep (A)\n◄ Image 1", self._act_keep_left,
            fg="#ffffff", bg=COLOR_KEEP,
        )
        btn_kl.pack(fill="x", padx=12, pady=8)
        self._action_buttons.append(btn_kl)

        # ── Keep Right (D) — full-width green ────────────────
        btn_kr = self._make_button(
            frame, "✅  Keep (D)\nImage 2 ►", self._act_keep_right,
            fg="#ffffff", bg=COLOR_KEEP,
        )
        btn_kr.pack(fill="x", padx=12, pady=8)
        self._action_buttons.append(btn_kr)

        # ── Trash Both — full-width amber ──────────────────
        btn_tb = self._make_button(
            frame, "🗑  Trash Both (S)", self._act_trash_both,
            fg="#ffffff", bg=COLOR_BOTH_TRASH,
        )
        btn_tb.pack(fill="x", padx=12, pady=(8, 0))
        self._action_buttons.append(btn_tb)

        # ── Separator ────────────────────────────────────
        tk.Frame(frame, bg=TEXT_DIM, height=1).pack(fill="x", pady=20)

        tk.Label(
            frame,
            text="☠  Permanent Delete (no Recycle Bin)",
            font=(FONT_FAMILY, 8),
            bg=BG_PANEL,
            fg=TEXT_DIM,
        ).pack()

        # ── Permanent delete — side-by-side ─────────────────
        del_row = tk.Frame(frame, bg=BG_PANEL)
        del_row.pack(fill="x", pady=(4, 0))

        btn_dl = self._make_button(
            del_row, "☠  Delete\n◄ Image 1", self._act_del_left,
            fg="#ffffff", bg=COLOR_PERM_DEL,
        )
        btn_dl.pack(side="left", fill="both", expand=True, padx=(12, 4))
        self._action_buttons.append(btn_dl)

        btn_dr = self._make_button(
            del_row, "☠  Delete\nImage 2 ►", self._act_del_right,
            fg="#ffffff", bg=COLOR_PERM_DEL,
        )
        btn_dr.pack(side="right", fill="both", expand=True, padx=(4, 12))
        self._action_buttons.append(btn_dr)

        # ── Similarity badge ─────────────────────────────────
        tk.Frame(frame, bg=TEXT_DIM, height=1).pack(fill="x", pady=20)
        self.lbl_similarity = tk.Label(
            frame,
            text="",
            font=(FONT_FAMILY, 10, "bold"),
            bg=BG_PANEL,
            fg=ACCENT_AMBER,
            wraplength=200,
            justify="center",
        )
        self.lbl_similarity.pack()

    def _build_folder_viewer_area(self, parent: tk.Frame):
        # Top bar inside Image Viewer area
        top_bar = tk.Frame(parent, bg=BG_PANEL, padx=12, pady=8)
        top_bar.pack(fill="x", side="top", pady=(0, 10))

        tk.Label(
            top_bar,
            text="📁 Target Subfolder:",
            font=(FONT_FAMILY, 9, "bold"),
            bg=BG_PANEL,
            fg=ACCENT_GREEN,
        ).pack(side="left", padx=(4, 8))

        self._combo_fv_folders = ttk.Combobox(
            top_bar,
            state="readonly",
            font=(FONT_FAMILY, 9),
            width=50,
        )
        self._combo_fv_folders.pack(side="left", padx=(0, 15))
        self._combo_fv_folders.bind("<<ComboboxSelected>>", self._fv_on_folder_change)

        self.lbl_fv_counter = tk.Label(
            top_bar,
            text="",
            font=(FONT_FAMILY, 10, "bold"),
            bg=BG_PANEL,
            fg=ACCENT_AMBER,
        )
        self.lbl_fv_counter.pack(side="left", padx=10)

        # Image Viewer Main Grid
        content = tk.Frame(parent, bg=BG_DARK)
        content.pack(fill="both", expand=True)
        content.columnconfigure(0, weight=3)
        content.columnconfigure(1, weight=2)
        content.rowconfigure(0, weight=1)

        # Single Image Panel
        self.panel_fv = ImagePanel(
            content,
            "🖼  Image Viewer",
            rotate_hotkey="R",
            preview_size=(620, 500),
            on_prev=self._fv_prev,
            on_next=self._fv_next,
        )
        self.panel_fv.grid(row=0, column=0, sticky="nsew", padx=(0, 6))

        # Sidebar Frame with Canvas scrollbar for smooth responsiveness
        sidebar_container = tk.Frame(content, bg=BG_PANEL)
        sidebar_container.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        sidebar_canvas = tk.Canvas(sidebar_container, bg=BG_PANEL, highlightthickness=0)
        sidebar_scrollbar = ttk.Scrollbar(sidebar_container, orient="vertical", command=sidebar_canvas.yview)

        sidebar = tk.Frame(sidebar_canvas, bg=BG_PANEL, padx=12, pady=12)
        sidebar.bind(
            "<Configure>",
            lambda e: sidebar_canvas.configure(scrollregion=sidebar_canvas.bbox("all"))
        )

        canvas_win = sidebar_canvas.create_window((0, 0), window=sidebar, anchor="nw")
        sidebar_canvas.bind("<Configure>", lambda e: sidebar_canvas.itemconfig(canvas_win, width=e.width))
        sidebar_canvas.configure(yscrollcommand=sidebar_scrollbar.set)

        sidebar_canvas.pack(side="left", fill="both", expand=True)
        sidebar_scrollbar.pack(side="right", fill="y")

        tk.Label(
            sidebar,
            text="Image Actions & Details",
            font=(FONT_FAMILY, 12, "bold"),
            bg=BG_PANEL,
            fg=ACCENT_GREEN,
        ).pack(anchor="w", pady=(0, 8))

        # Details Card
        card = tk.Frame(sidebar, bg=BG_CARD, padx=12, pady=10)
        card.pack(fill="x", pady=(0, 10))

        self.lbl_fv_info_filename = tk.Label(
            card, text="Filename: —", font=(FONT_FAMILY, 9, "bold"),
            bg=BG_CARD, fg=TEXT_MAIN, anchor="w", justify="left", wraplength=280
        )
        self.lbl_fv_info_filename.pack(fill="x", pady=2)

        self.lbl_fv_info_folder = tk.Label(
            card, text="Folder: —", font=(FONT_FAMILY, 8),
            bg=BG_CARD, fg=TEXT_DIM, anchor="w", justify="left", wraplength=280
        )
        self.lbl_fv_info_folder.pack(fill="x", pady=2)

        self.lbl_fv_info_dims = tk.Label(
            card, text="Dimensions: —", font=(FONT_FAMILY, 8),
            bg=BG_CARD, fg=TEXT_DIM, anchor="w", justify="left"
        )
        self.lbl_fv_info_dims.pack(fill="x", pady=2)

        self.lbl_fv_info_size = tk.Label(
            card, text="File Size: —", font=(FONT_FAMILY, 8),
            bg=BG_CARD, fg=TEXT_DIM, anchor="w", justify="left"
        )
        self.lbl_fv_info_size.pack(fill="x", pady=2)



        # Chop row
        btn_chop = self._make_button(
            sidebar, "✂  Chop Image (C)", self._fv_chop,
            fg="#ffffff", bg=ACCENT_BLUE
        )
        btn_chop.pack(fill="x", pady=(0, 10))

        # Rotate row
        btn_rot = self._make_button(
            sidebar, "↻  Rotate 90° Clockwise (R)", self._fv_rotate,
            fg="#ffffff", bg=COLOR_BOTH_KEEP
        )
        btn_rot.pack(fill="x", pady=(0, 10))

        # ── INLINE TAG & KEYWORD MANAGER CARD ─────────────────────
        card_tags = tk.Frame(sidebar, bg=BG_CARD, padx=12, pady=10)
        card_tags.pack(fill="x", pady=(0, 10))

        tags_hdr = tk.Frame(card_tags, bg=BG_CARD)
        tags_hdr.pack(fill="x", pady=(0, 6))

        tk.Label(
            tags_hdr,
            text="🏷️ Keywords & Tags (Immich/EXIF/XMP)",
            font=(FONT_FAMILY, 9, "bold"),
            bg=BG_CARD,
            fg=ACCENT_BLUE,
        ).pack(side="left")

        btn_clear_tags = tk.Button(
            tags_hdr,
            text="Clear All",
            font=(FONT_FAMILY, 7, "bold"),
            bg=BG_CARD,
            fg=ACCENT_RED,
            activebackground=BG_CARD,
            activeforeground=ACCENT_RED,
            relief="flat",
            cursor="hand2",
            command=self._fv_clear_all_tags,
        )
        btn_clear_tags.pack(side="right")

        # Active tag pills frame
        self.frame_fv_active_tags = tk.Frame(card_tags, bg=BG_CARD)
        self.frame_fv_active_tags.pack(fill="x", pady=(0, 8))

        # Tag entry row
        entry_row = tk.Frame(card_tags, bg=BG_CARD)
        entry_row.pack(fill="x", pady=(0, 4))

        self.var_fv_tag_entry = tk.StringVar()
        self.entry_fv_tag = tk.Entry(
            entry_row,
            textvariable=self.var_fv_tag_entry,
            font=(FONT_FAMILY, 9),
            bg=BG_PANEL,
            fg=TEXT_MAIN,
            insertbackground=TEXT_MAIN,
            relief="flat",
        )
        self.entry_fv_tag.pack(side="left", fill="x", expand=True, padx=(0, 6), ipady=4)
        self.entry_fv_tag.bind("<KeyRelease>", self._fv_on_tag_entry_changed)
        self.entry_fv_tag.bind("<Return>", lambda e: self._fv_add_current_tag())
        self.entry_fv_tag.bind("<Escape>", lambda e: self._fv_hide_tag_suggestions())

        btn_add_tag = tk.Button(
            entry_row,
            text="+ Add (T)",
            font=(FONT_FAMILY, 8, "bold"),
            bg=ACCENT_BLUE,
            fg=BG_DARK,
            relief="flat",
            cursor="hand2",
            padx=8,
            pady=2,
            command=self._fv_add_current_tag,
        )
        btn_add_tag.pack(side="right")

        # Suggestions frame / Listbox
        self.frame_fv_suggestions = tk.Frame(card_tags, bg=BG_CARD)
        # hidden by default

        self.listbox_fv_suggestions = tk.Listbox(
            self.frame_fv_suggestions,
            font=(FONT_FAMILY, 8),
            bg=BG_PANEL,
            fg=TEXT_MAIN,
            selectbackground=ACCENT_BLUE,
            selectforeground=BG_DARK,
            height=4,
            relief="flat",
            highlightthickness=0,
        )
        self.listbox_fv_suggestions.pack(fill="x", expand=True)
        self.listbox_fv_suggestions.bind("<<ListboxSelect>>", self._fv_on_tag_suggestion_clicked)
        self.listbox_fv_suggestions.bind("<Return>", self._fv_on_tag_suggestion_clicked)

        # Quick directory tags frame
        self.frame_fv_known_keywords_container = tk.Frame(card_tags, bg=BG_CARD)
        self.frame_fv_known_keywords_container.pack(fill="x", pady=(6, 0))

        tk.Label(
            self.frame_fv_known_keywords_container,
            text="Universal App Tags:",
            font=(FONT_FAMILY, 8, "bold"),
            bg=BG_CARD,
            fg=TEXT_DIM,
        ).pack(anchor="w", pady=(0, 4))

        self.frame_fv_known_keywords = tk.Frame(self.frame_fv_known_keywords_container, bg=BG_CARD)
        self.frame_fv_known_keywords.pack(fill="x")

        # Separator & Single Delete button at bottom away from everything
        tk.Frame(sidebar, bg=TEXT_DIM, height=1).pack(fill="x", pady=(15, 12))

        btn_trash = self._make_button(
            sidebar, "🗑  Send to Trash (Del)", self._fv_trash,
            fg="#ffffff", bg=COLOR_TRASH
        )
        btn_trash.pack(fill="x")

    def _build_statusbar(self):
        bar = tk.Frame(self, bg=BG_PANEL, pady=4)
        bar.pack(fill="x", side="bottom")

        self.lbl_status = tk.Label(
            bar,
            text="Ready — choose a directory and select a mode.",
            font=(FONT_FAMILY, 9),
            bg=BG_PANEL,
            fg=TEXT_DIM,
            anchor="w",
        )
        self.lbl_status.pack(side="left", padx=16)

        self.progress_var = tk.IntVar(value=0)
        self.progressbar = ttk.Progressbar(
            bar,
            variable=self.progress_var,
            maximum=100,
            length=200,
            mode="determinate",
            style="Accent.Horizontal.TProgressbar",
        )
        self.progressbar.pack(side="right", padx=12)

        self.lbl_progress = tk.Label(
            bar,
            text="",
            font=(FONT_FAMILY, 9),
            bg=BG_PANEL,
            fg=TEXT_DIM,
        )
        self.lbl_progress.pack(side="right", padx=(0, 4))

        # Style the progressbar & combobox
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(
            "Accent.Horizontal.TProgressbar",
            troughcolor=BG_CARD,
            bordercolor=BG_CARD,
            background=ACCENT_BLUE,
            lightcolor=ACCENT_BLUE,
            darkcolor=ACCENT_BLUE,
        )
        style.configure(
            "TCombobox",
            fieldbackground=BG_CARD,
            background=BG_PANEL,
            foreground=TEXT_MAIN,
            darkcolor=BG_CARD,
            lightcolor=BG_CARD,
        )

    # ── Button factory ──────────────────────────────────────────────────────
    @staticmethod
    def _make_button(parent, text, command, fg=TEXT_MAIN, bg=BG_CARD, width=None):
        kw = dict(font=(FONT_FAMILY, 9, "bold"), relief="flat", cursor="hand2",
                  activebackground=BG_DARK, fg=fg, bg=bg,
                   padx=16, pady=12, command=command)
        if width:
            kw["width"] = width
        btn = tk.Button(parent, text=text, **kw)
        btn.bind("<Enter>", lambda e: btn.config(bg=_lighten(bg)))
        btn.bind("<Leave>", lambda e: btn.config(bg=bg))
        return btn

    # ── Event handlers ──────────────────────────────────────────────────────
    def _on_browse(self):
        path = filedialog.askdirectory(title="Select image directory")
        if path:
            self.var_dir.set(path)
            self._btn_scan.config(state="normal")
            self._scan_known_keywords(path)
            if self._current_mode == "folder_viewer":
                self._fv_load_directory(path)
                self._update_status("Directory selected. Loaded images in Image Viewer.")
            elif self._current_mode == "mass_edit":
                self._me_load_directory(path)
                self._update_status("Directory selected. Loaded images in Mass Edit mode.")
            else:
                self._update_status("Directory selected. Click 'Start Scan' to begin duplicate scan.")

    def _on_start_scan(self):
        if self._scan_running:
            return
        root_dir = self.var_dir.get()
        if not root_dir or not os.path.isdir(root_dir):
            messagebox.showwarning("No Directory", "Please select a valid directory first.")
            return

        # Reset state
        self._match_counts.clear()
        self._pending_pairs.clear()
        self._current_pair = None
        self._scan_done = False
        self._scan_running = True
        self._pair_index = 0
        self.panel_left.show_placeholder("Scanning…\nPlease wait.")
        self.panel_right.show_placeholder("Scanning…\nPlease wait.")
        self.lbl_pair_counter.config(text="")
        self.lbl_similarity.config(text="")
        self._set_review_state(active=False)
        self._btn_scan.config(state="disabled")
        self._btn_browse.config(state="disabled")
        self.progress_var.set(0)

        # Fresh queue + stats
        self._scan_queue = queue.Queue()
        self._stats = ScanStats()

        self._scanner = DuplicateScanner(
            root_dir=root_dir,
            result_queue=self._scan_queue,
            stats=self._stats,
            hash_threshold=HASH_THRESHOLD,
        )
        self._scanner.start()
        self._update_status("🔍  Scanning…")
        self.after(POLL_MS, self._poll_queue)

    # ── Queue polling (called by Tk event loop) ─────────────────────────────
    def _poll_queue(self):
        # Drain all available items
        try:
            while True:
                item = self._scan_queue.get_nowait()
                if item is SCAN_DONE:
                    self._scan_running = False
                    self._scan_done = True
                    self._on_scan_finished()
                    return  # stop polling
                else:
                    a, b = item
                    self._match_counts[a] = self._match_counts.get(a, 0) + 1
                    self._match_counts[b] = self._match_counts.get(b, 0) + 1
                    self._pending_pairs.append(item)
                    # Load pair immediately if none being shown
                    if self._current_pair is None:
                        self._load_next_pair()
        except queue.Empty:
            pass

        # Update progress
        total, processed, pairs = self._stats.snapshot()
        if total > 0:
            pct = int(processed / total * 100)
            self.progress_var.set(pct)
            self.lbl_progress.config(text=f"{processed}/{total}")
            self._update_status(
                f"🔍  Scanning… {processed}/{total} files  |  {pairs} duplicate pair(s) found so far"
            )

        # Schedule next poll
        self.after(POLL_MS, self._poll_queue)

    def _on_scan_finished(self):
        total, _, pairs = self._stats.snapshot()
        self.progress_var.set(100)
        self.lbl_progress.config(text=f"{total}/{total}")
        self._btn_browse.config(state="normal")
        self._btn_scan.config(state="normal")

        if self._current_pair is None:
            if not self._pending_pairs:
                self._show_complete_state("No duplicate images found in the selected directory.")
            else:
                self._load_next_pair()
        else:
            self._update_status(
                f"Scan complete — {pairs} pair(s) found. Reviewing…"
            )

    # ── Pair management ─────────────────────────────────────────────────────
    def _purge_deleted(self, *paths: Path):
        """
        Remove any pending pairs that reference one of the given (just-deleted)
        paths so we never try to load a file that no longer exists.
        """
        deleted = {str(p) for p in paths}
        self._pending_pairs = [
            (a, b) for a, b in self._pending_pairs
            if str(a) not in deleted and str(b) not in deleted
        ]

    def _load_next_pair(self):
        # Skip over pairs where either file has been deleted elsewhere.
        while self._pending_pairs:
            candidate = self._pending_pairs[0]
            if candidate[0].exists() and candidate[1].exists():
                break  # good pair — use it
            # One or both files are already gone; silently discard this pair.
            self._pending_pairs.pop(0)

        if not self._pending_pairs:
            if self._scan_done:
                self._show_complete_state()
            else:
                # Scan still running; wait for more results
                self._current_pair = None
                self.panel_left.show_placeholder("Scanning for more\nduplicates…")
                self.panel_right.show_placeholder("Scanning for more\nduplicates…")
                self._set_review_state(active=False)
            return

        pair = self._pending_pairs.pop(0)
        self._current_pair = pair
        self._pair_index += 1
        left_path, right_path = pair

        self.panel_left.load_image(left_path)
        self.panel_right.load_image(right_path)

        # Update match counts
        count_left = self._match_counts.get(left_path, 1)
        count_right = self._match_counts.get(right_path, 1)
        self.panel_left.lbl_match_count.config(text=f"Matched with {count_left} picture(s) total")
        self.panel_right.lbl_match_count.config(text=f"Matched with {count_right} picture(s) total")

        # Compute and show similarity
        sim_text = self._similarity_label(left_path, right_path)
        self.lbl_similarity.config(text=sim_text)

        self.lbl_pair_counter.config(text=f"Pair {self._pair_index}")
        self._set_review_state(active=True)

        self._update_status(
            f"Reviewing pair {self._pair_index}  |  {len(self._pending_pairs)} pair(s) remaining in queue"
        )

    def _show_complete_state(self, msg: str = ""):
        self._current_pair = None
        self._set_review_state(active=False)
        if not msg:
            msg = (
                f"✅  All done!\n{self._pair_index} pair(s) reviewed.\n\n"
                "No more duplicates found."
            )
        self.panel_left.show_placeholder(msg)
        self.panel_right.show_placeholder(msg)
        self.lbl_pair_counter.config(text="")
        self.lbl_similarity.config(text="")
        self._update_status(f"Scan complete — {self._pair_index} pair(s) reviewed.")
        self.progress_var.set(100)

    # ── Image Viewer Logic ────────────────────────────────────────────────
    def _fv_load_directory(self, root_dir_str: str):
        root_path = Path(root_dir_str)
        self._fv_root_dir = root_path
        self._scan_known_keywords(root_path)
        self._fv_folders = collect_images_by_folder(root_path)
        self._fv_all_images = collect_image_paths(root_path)

        combo_options = [f"[All Folders] ({len(self._fv_all_images)} images)"]
        self._fv_folder_list = sorted(self._fv_folders.keys(), key=lambda p: str(p.relative_to(root_path)))
        for folder_path in self._fv_folder_list:
            try:
                rel_str = str(folder_path.relative_to(root_path))
            except ValueError:
                rel_str = str(folder_path)
            if rel_str == ".":
                rel_str = "[Root Directory]"
            count = len(self._fv_folders[folder_path])
            combo_options.append(f"📁 {rel_str} ({count} images)")

        self._combo_fv_folders["values"] = combo_options
        if combo_options:
            self._combo_fv_folders.current(0)

        self._fv_active_images = list(self._fv_all_images)
        self._fv_index = 0
        self._fv_show_current()

    def _fv_on_folder_change(self, event=None):
        sel_idx = self._combo_fv_folders.current()
        if sel_idx <= 0:
            self._fv_active_images = list(self._fv_all_images)
        else:
            folder_path = self._fv_folder_list[sel_idx - 1]
            self._fv_active_images = list(self._fv_folders.get(folder_path, []))

        self._fv_index = 0
        self._fv_show_current()

    def _fv_show_current(self):
        # Clean out any files that no longer exist
        self._fv_active_images = [p for p in self._fv_active_images if p.exists()]

        if not self._fv_active_images:
            self.panel_fv.show_placeholder("No images found in selected folder.")
            self.lbl_fv_counter.config(text="0 of 0")
            self._fv_update_info_labels(None)
            return

        if self._fv_index < 0:
            self._fv_index = 0
        elif self._fv_index >= len(self._fv_active_images):
            self._fv_index = len(self._fv_active_images) - 1

        path = self._fv_active_images[self._fv_index]
        self.panel_fv.load_image(path)
        self.lbl_fv_counter.config(
            text=f"Image {self._fv_index + 1} of {len(self._fv_active_images)}"
        )
        self._fv_update_info_labels(path)
        self._update_status(
            f"Image Viewer: Image {self._fv_index + 1}/{len(self._fv_active_images)} — {path.name}"
        )

    def _fv_update_info_labels(self, path: Path | None):
        if path is None or not path.exists():
            self.lbl_fv_info_filename.config(text="Filename: —")
            self.lbl_fv_info_folder.config(text="Folder: —")
            self.lbl_fv_info_dims.config(text="Dimensions: —")
            self.lbl_fv_info_size.config(text="File Size: —")
            self._fv_current_tags = []
            self._fv_refresh_active_tags_ui()
            self._fv_refresh_known_keywords_ui()
            return

        self.lbl_fv_info_filename.config(text=f"Filename: {path.name}")
        if self._fv_root_dir and path.is_relative_to(self._fv_root_dir):
            rel_folder = path.parent.relative_to(self._fv_root_dir)
            folder_text = str(rel_folder) if str(rel_folder) != "." else "[Root Directory]"
        else:
            folder_text = str(path.parent)
        self.lbl_fv_info_folder.config(text=f"Folder: {folder_text}")

        try:
            sz = path.stat().st_size
            self.lbl_fv_info_size.config(text=f"File Size: {format_file_size(sz)}")
        except Exception:
            self.lbl_fv_info_size.config(text="File Size: Unknown")

        try:
            with Image.open(path) as img:
                w, h = img.size
                self.lbl_fv_info_dims.config(text=f"Dimensions: {w} × {h} px")
        except Exception:
            self.lbl_fv_info_dims.config(text="Dimensions: Unknown")

        try:
            self._fv_current_tags = read_image_tags(path)
            new_tags_found = False
            for t in self._fv_current_tags:
                if t not in self._known_keywords:
                    self._known_keywords.add(t)
                    new_tags_found = True
            if new_tags_found:
                self._save_immich_config()
        except Exception:
            self._fv_current_tags = []

        self._fv_refresh_active_tags_ui()
        self._fv_refresh_known_keywords_ui()

    # ── Inline Tag Manager Handlers ─────────────────────────────────────────
    def _fv_refresh_active_tags_ui(self):
        """Redraw tag pill buttons in self.frame_fv_active_tags."""
        for widget in self.frame_fv_active_tags.winfo_children():
            widget.destroy()

        if not self._fv_current_tags:
            lbl = tk.Label(
                self.frame_fv_active_tags,
                text="(No tags set on image)",
                font=(FONT_FAMILY, 8, "italic"),
                bg=BG_CARD,
                fg=TEXT_DIM,
            )
            lbl.pack(anchor="w")
            return

        # Container for tag pills
        chips_frame = tk.Frame(self.frame_fv_active_tags, bg=BG_CARD)
        chips_frame.pack(fill="x")

        for tag in self._fv_current_tags:
            pill = tk.Frame(chips_frame, bg=COLOR_KEEP, padx=6, pady=2)
            pill.pack(side="left", padx=2, pady=2)

            lbl_t = tk.Label(
                pill,
                text=tag,
                font=(FONT_FAMILY, 8, "bold"),
                bg=COLOR_KEEP,
                fg="#ffffff",
            )
            lbl_t.pack(side="left", padx=(0, 4))

            btn_x = tk.Label(
                pill,
                text="✕",
                font=(FONT_FAMILY, 8, "bold"),
                bg=COLOR_KEEP,
                fg=ACCENT_AMBER,
                cursor="hand2",
            )
            btn_x.pack(side="right")
            btn_x.bind("<Button-1>", lambda e, t=tag: self._fv_remove_tag(t))

    def _fv_refresh_known_keywords_ui(self):
        """Redraw universal app keyword chips in self.frame_fv_known_keywords."""
        for widget in self.frame_fv_known_keywords.winfo_children():
            widget.destroy()

        available = sorted(list(self._known_keywords))
        if not available:
            lbl = tk.Label(
                self.frame_fv_known_keywords,
                text="(No universal tags saved yet)",
                font=(FONT_FAMILY, 8, "italic"),
                bg=BG_CARD,
                fg=TEXT_DIM,
            )
            lbl.pack(anchor="w")
            return

        current_row = tk.Frame(self.frame_fv_known_keywords, bg=BG_CARD)
        current_row.pack(fill="x", pady=1)
        current_char_count = 0

        for kw in available:
            chip_text = f"+ {kw}"
            chip_len = len(chip_text) + 2
            if current_char_count > 0 and current_char_count + chip_len > 28:
                current_row = tk.Frame(self.frame_fv_known_keywords, bg=BG_CARD)
                current_row.pack(fill="x", pady=1)
                current_char_count = 0

            btn = tk.Button(
                current_row,
                text=chip_text,
                font=(FONT_FAMILY, 7, "bold"),
                bg=BG_PANEL,
                fg=ACCENT_GREEN,
                activebackground=ACCENT_BLUE,
                activeforeground=BG_DARK,
                relief="flat",
                cursor="hand2",
                padx=4,
                pady=1,
                command=lambda t=kw: self._fv_add_tag(t),
            )
            btn.pack(side="left", padx=2, pady=2)
            current_char_count += chip_len

    def _fv_add_tag(self, tag: str):
        cleaned = tag.strip()
        if not cleaned or not self._fv_active_images or self._fv_index >= len(self._fv_active_images):
            return

        path = self._fv_active_images[self._fv_index]
        existing_lower = {t.lower() for t in self._fv_current_tags}
        if cleaned.lower() not in existing_lower:
            self._fv_current_tags.append(cleaned)
            self._known_keywords.add(cleaned)
            self._save_immich_config()
            success = write_image_tags(path, self._fv_current_tags)
            self._fv_refresh_active_tags_ui()
            self._fv_refresh_known_keywords_ui()
            self.var_fv_tag_entry.set("")
            self._fv_hide_tag_suggestions()
            if success:
                self._update_status(f"Saved tag '{cleaned}' to {path.name}")
        else:
            self.var_fv_tag_entry.set("")
            self._fv_hide_tag_suggestions()
            self._update_status(f"Image {path.name} already has tag '{cleaned}'.")

    def _fv_remove_tag(self, tag: str):
        if not self._fv_active_images or self._fv_index >= len(self._fv_active_images):
            return

        path = self._fv_active_images[self._fv_index]
        if tag in self._fv_current_tags:
            self._fv_current_tags.remove(tag)
            success = write_image_tags(path, self._fv_current_tags)
            self._fv_refresh_active_tags_ui()
            self._fv_refresh_known_keywords_ui()
            if success:
                self._update_status(f"Removed tag '{tag}' from {path.name}")

    def _fv_clear_all_tags(self):
        if not self._fv_active_images or self._fv_index >= len(self._fv_active_images):
            return
        if not self._fv_current_tags:
            return

        path = self._fv_active_images[self._fv_index]
        self._fv_current_tags.clear()
        write_image_tags(path, [])
        self._fv_refresh_active_tags_ui()
        self._fv_refresh_known_keywords_ui()
        self._update_status(f"Cleared all tags from {path.name}")

    def _fv_add_current_tag(self):
        val = self.var_fv_tag_entry.get().strip()
        if val:
            self._fv_add_tag(val)

    def _fv_on_tag_entry_changed(self, event=None):
        val = self.var_fv_tag_entry.get().strip().lower()
        if not val:
            self._fv_hide_tag_suggestions()
            return

        matches = [kw for kw in sorted(self._known_keywords) if val in kw.lower() and kw not in self._fv_current_tags]
        if not matches:
            self._fv_hide_tag_suggestions()
            return

        self.listbox_fv_suggestions.delete(0, tk.END)
        for kw in matches[:6]:
            self.listbox_fv_suggestions.insert(tk.END, kw)

        self.frame_fv_suggestions.pack(fill="x", pady=(4, 0))

    def _fv_hide_tag_suggestions(self):
        self.frame_fv_suggestions.pack_forget()

    def _fv_on_tag_suggestion_clicked(self, event=None):
        try:
            sel = self.listbox_fv_suggestions.curselection()
            if sel:
                kw = self.listbox_fv_suggestions.get(sel[0])
                self._fv_add_tag(kw)
        except Exception:
            pass

    def _fv_next(self):
        if self._fv_active_images:
            self._fv_index = (self._fv_index + 1) % len(self._fv_active_images)
            self._fv_show_current()

    def _fv_prev(self):
        if self._fv_active_images:
            self._fv_index = (self._fv_index - 1) % len(self._fv_active_images)
            self._fv_show_current()

    def _fv_first(self):
        if self._fv_active_images:
            self._fv_index = 0
            self._fv_show_current()

    def _fv_last(self):
        if self._fv_active_images:
            self._fv_index = len(self._fv_active_images) - 1
            self._fv_show_current()

    def _fv_chop(self):
        if not self._fv_active_images:
            return
        path = self._fv_active_images[self._fv_index]
        
        def on_chop_success(new_files):
            # Insert the new files immediately after the current image
            for i, new_path in enumerate(new_files):
                self._fv_active_images.insert(self._fv_index + 1 + i, new_path)
            messagebox.showinfo("Chop Success", f"Successfully extracted {len(new_files)} image(s).")
            # Update folder list UI if necessary (just refresh current view)
            self._fv_show_current()
            
        ChopImageDialog(self, path, on_chop_success)

    def _fv_rotate(self):
        if not self._fv_active_images:
            return
        self.panel_fv.rotate_image()
        path = self._fv_active_images[self._fv_index]
        self._fv_update_info_labels(path)

    def _fv_trash(self):
        if not self._fv_active_images or self._fv_index >= len(self._fv_active_images):
            return
        path = self._fv_active_images[self._fv_index]
        if messagebox.askyesno(
            "Confirm Delete",
            f"Are you sure you want to send this image to the Recycle Bin?\n\n{path.name}",
            icon="warning",
        ):
            self.panel_fv.flash_green()
            if send_to_trash(path):
                self._purge_deleted(path)
                self._fv_remove_path(path)
                self._fv_show_current()

    def _fv_remove_path(self, path: Path):
        if path in self._fv_all_images:
            self._fv_all_images.remove(path)
        if path in self._fv_active_images:
            self._fv_active_images.remove(path)
        folder = path.parent
        if folder in self._fv_folders and path in self._fv_folders[folder]:
            self._fv_folders[folder].remove(path)
            if not self._fv_folders[folder]:
                del self._fv_folders[folder]

    # ── Mass Edit Mode Implementation ───────────────────────────────────────
    def _build_mass_edit_area(self, parent: tk.Frame):
        top_bar = tk.Frame(parent, bg=BG_PANEL, padx=12, pady=8)
        top_bar.pack(fill="x", side="top", pady=(0, 10))

        tk.Label(
            top_bar,
            text="📁 Target Subfolder:",
            font=(FONT_FAMILY, 9, "bold"),
            bg=BG_PANEL,
            fg=ACCENT_GREEN,
        ).pack(side="left", padx=(4, 8))

        self._combo_me_folders = ttk.Combobox(
            top_bar,
            state="readonly",
            font=(FONT_FAMILY, 9),
            width=45,
        )
        self._combo_me_folders.pack(side="left", padx=(0, 15))
        self._combo_me_folders.bind("<<ComboboxSelected>>", self._me_on_folder_change)

        self.lbl_me_counter = tk.Label(
            top_bar,
            text="Selected: 0 images",
            font=(FONT_FAMILY, 10, "bold"),
            bg=BG_PANEL,
            fg=ACCENT_AMBER,
        )
        self.lbl_me_counter.pack(side="left", padx=10)

        # Quick selection buttons
        btn_desel = self._make_button(top_bar, "Deselect All", self._me_deselect_all, fg=TEXT_MAIN, bg=BG_CARD)
        btn_desel.pack(side="right", padx=(4, 0))

        btn_selall = self._make_button(top_bar, "Select All (Ctrl+A)", self._me_select_all, fg=TEXT_MAIN, bg=BG_CARD)
        btn_selall.pack(side="right", padx=4)

        # Main Grid Area (Thumbnail Grid + Mass Sidebar)
        content = tk.Frame(parent, bg=BG_DARK)
        content.pack(fill="both", expand=True)
        content.columnconfigure(0, weight=3)
        content.columnconfigure(1, weight=2)
        content.rowconfigure(0, weight=1)

        # Left Column: Scrollable Thumbnail Grid
        grid_container = tk.Frame(content, bg=BG_DARK)
        grid_container.grid(row=0, column=0, sticky="nsew", padx=(0, 6))

        self.me_grid_canvas = tk.Canvas(grid_container, bg=BG_DARK, highlightthickness=0)
        grid_scrollbar = ttk.Scrollbar(grid_container, orient="vertical", command=self.me_grid_canvas.yview)

        self.me_grid_frame = tk.Frame(self.me_grid_canvas, bg=BG_DARK)
        self.me_grid_frame.bind(
            "<Configure>",
            lambda e: self.me_grid_canvas.configure(scrollregion=self.me_grid_canvas.bbox("all"))
        )

        canvas_win = self.me_grid_canvas.create_window((0, 0), window=self.me_grid_frame, anchor="nw")
        self.me_grid_canvas.bind("<Configure>", lambda e: self.me_grid_canvas.itemconfig(canvas_win, width=e.width))
        self.me_grid_canvas.configure(yscrollcommand=grid_scrollbar.set)

        self.me_grid_canvas.pack(side="left", fill="both", expand=True)
        grid_scrollbar.pack(side="right", fill="y")

        self.me_grid_canvas.bind("<MouseWheel>", lambda e: self.me_grid_canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        # Right Column: Mass Edit Sidebar
        sidebar_container = tk.Frame(content, bg=BG_PANEL)
        sidebar_container.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        sb_canvas = tk.Canvas(sidebar_container, bg=BG_PANEL, highlightthickness=0)
        sb_scrollbar = ttk.Scrollbar(sidebar_container, orient="vertical", command=sb_canvas.yview)

        sidebar = tk.Frame(sb_canvas, bg=BG_PANEL, padx=12, pady=12)
        sidebar.bind(
            "<Configure>",
            lambda e: sb_canvas.configure(scrollregion=sb_canvas.bbox("all"))
        )
        sb_win = sb_canvas.create_window((0, 0), window=sidebar, anchor="nw")
        sb_canvas.bind("<Configure>", lambda e: sb_canvas.itemconfig(sb_win, width=e.width))
        sb_canvas.configure(yscrollcommand=sb_scrollbar.set)

        sb_canvas.pack(side="left", fill="both", expand=True)
        sb_scrollbar.pack(side="right", fill="y")

        tk.Label(
            sidebar,
            text="Mass Edit Actions & Tags",
            font=(FONT_FAMILY, 12, "bold"),
            bg=BG_PANEL,
            fg=ACCENT_GREEN,
        ).pack(anchor="w", pady=(0, 8))

        # Mass Operations Card
        card_op = tk.Frame(sidebar, bg=BG_CARD, padx=12, pady=10)
        card_op.pack(fill="x", pady=(0, 10))

        self.lbl_me_selection_status = tk.Label(
            card_op,
            text="0 images selected",
            font=(FONT_FAMILY, 10, "bold"),
            bg=BG_CARD,
            fg=ACCENT_AMBER,
            anchor="w",
        )
        self.lbl_me_selection_status.pack(fill="x", pady=(0, 8))

        btn_mass_rot = self._make_button(
            card_op,
            "↻  Rotate All Highlighted 90° (R)",
            self._me_rotate_selected,
            fg="#ffffff",
            bg=COLOR_BOTH_KEEP,
        )
        btn_mass_rot.pack(fill="x", pady=(0, 6))

        # ── MASS TAG MANAGER CARD ─────────────────────
        card_tags = tk.Frame(sidebar, bg=BG_CARD, padx=12, pady=10)
        card_tags.pack(fill="x", pady=(0, 10))

        tags_hdr = tk.Frame(card_tags, bg=BG_CARD)
        tags_hdr.pack(fill="x", pady=(0, 6))

        tk.Label(
            tags_hdr,
            text="🏷️ Shared Tags across Highlighted",
            font=(FONT_FAMILY, 9, "bold"),
            bg=BG_CARD,
            fg=ACCENT_BLUE,
        ).pack(side="left")

        btn_clear_common = tk.Button(
            tags_hdr,
            text="Clear Common",
            font=(FONT_FAMILY, 7, "bold"),
            bg=BG_CARD,
            fg=ACCENT_RED,
            activebackground=BG_CARD,
            activeforeground=ACCENT_RED,
            relief="flat",
            cursor="hand2",
            command=self._me_clear_common_tags,
        )
        btn_clear_common.pack(side="right")

        # Active common tag pills frame
        self.frame_me_active_tags = tk.Frame(card_tags, bg=BG_CARD)
        self.frame_me_active_tags.pack(fill="x", pady=(0, 8))

        # Tag entry row (Add tag to all selected)
        entry_row = tk.Frame(card_tags, bg=BG_CARD)
        entry_row.pack(fill="x", pady=(0, 4))

        self.var_me_tag_entry = tk.StringVar()
        self.entry_me_tag = tk.Entry(
            entry_row,
            textvariable=self.var_me_tag_entry,
            font=(FONT_FAMILY, 9),
            bg=BG_PANEL,
            fg=TEXT_MAIN,
            insertbackground=TEXT_MAIN,
            relief="flat",
        )
        self.entry_me_tag.pack(side="left", fill="x", expand=True, padx=(0, 6), ipady=4)
        self.entry_me_tag.bind("<KeyRelease>", self._me_on_tag_entry_changed)
        self.entry_me_tag.bind("<Return>", lambda e: self._me_add_current_tag())
        self.entry_me_tag.bind("<Escape>", lambda e: self._me_hide_tag_suggestions())

        btn_add_tag_all = tk.Button(
            entry_row,
            text="+ Add to All",
            font=(FONT_FAMILY, 8, "bold"),
            bg=ACCENT_BLUE,
            fg=BG_DARK,
            relief="flat",
            cursor="hand2",
            padx=8,
            pady=2,
            command=self._me_add_current_tag,
        )
        btn_add_tag_all.pack(side="right")

        # Suggestions listbox for mass edit
        self.frame_me_suggestions = tk.Frame(card_tags, bg=BG_CARD)
        self.listbox_me_suggestions = tk.Listbox(
            self.frame_me_suggestions,
            font=(FONT_FAMILY, 8),
            bg=BG_PANEL,
            fg=TEXT_MAIN,
            selectbackground=ACCENT_BLUE,
            selectforeground=BG_DARK,
            height=4,
            relief="flat",
            highlightthickness=0,
        )
        self.listbox_me_suggestions.pack(fill="x", expand=True)
        self.listbox_me_suggestions.bind("<<ListboxSelect>>", self._me_on_tag_suggestion_clicked)

        # Quick directory tags frame
        self.frame_me_known_keywords_container = tk.Frame(card_tags, bg=BG_CARD)
        self.frame_me_known_keywords_container.pack(fill="x", pady=(6, 0))

        tk.Label(
            self.frame_me_known_keywords_container,
            text="Universal App Tags:",
            font=(FONT_FAMILY, 8, "bold"),
            bg=BG_CARD,
            fg=TEXT_DIM,
        ).pack(anchor="w", pady=(0, 4))

        self.frame_me_known_keywords = tk.Frame(self.frame_me_known_keywords_container, bg=BG_CARD)
        self.frame_me_known_keywords.pack(fill="x")

        # Separator & Mass Trash button at bottom
        tk.Frame(sidebar, bg=TEXT_DIM, height=1).pack(fill="x", pady=(15, 12))

        btn_mass_trash = self._make_button(
            sidebar, "🗑  Send Highlighted to Trash (Del)", self._me_trash_selected,
            fg="#ffffff", bg=COLOR_TRASH
        )
        btn_mass_trash.pack(fill="x")

    def _me_load_directory(self, root_dir_str: str):
        root_path = Path(root_dir_str)
        self._me_root_dir = root_path
        self._scan_known_keywords(root_path)
        self._me_folders = collect_images_by_folder(root_path)
        self._me_all_images = collect_image_paths(root_path)

        combo_options = [f"[All Folders] ({len(self._me_all_images)} images)"]
        self._me_folder_list = sorted(self._me_folders.keys(), key=lambda p: str(p.relative_to(root_path)))
        for folder_path in self._me_folder_list:
            try:
                rel_str = str(folder_path.relative_to(root_path))
            except ValueError:
                rel_str = str(folder_path)
            if rel_str == ".":
                rel_str = "[Root Directory]"
            count = len(self._me_folders[folder_path])
            combo_options.append(f"📁 {rel_str} ({count} images)")

        self._combo_me_folders["values"] = combo_options
        if combo_options:
            self._combo_me_folders.current(0)

        self._me_active_images = list(self._me_all_images)
        self._me_selected_indices.clear()
        self._me_last_clicked_index = None
        self._me_render_grid()

    def _me_on_folder_change(self, event=None):
        sel_idx = self._combo_me_folders.current()
        if sel_idx <= 0:
            self._me_active_images = list(self._me_all_images)
        else:
            folder_path = self._me_folder_list[sel_idx - 1]
            self._me_active_images = list(self._me_folders.get(folder_path, []))

        self._me_selected_indices.clear()
        self._me_last_clicked_index = None
        self._me_render_grid()

    def _me_get_thumbnail(self, path: Path) -> ImageTk.PhotoImage | None:
        """Cache and return a 110x110 PhotoImage thumbnail."""
        if path in self._me_thumb_cache:
            return self._me_thumb_cache[path]
        try:
            with Image.open(path) as img:
                img_copy = img.copy()
                img_copy.thumbnail((110, 110), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(img_copy)
                self._me_thumb_cache[path] = photo
                return photo
        except Exception:
            return None

    def _me_render_grid(self):
        """Render thumbnail grid showing 5 rows visible with vertical scroll."""
        for widget in self.me_grid_frame.winfo_children():
            widget.destroy()

        self._me_tile_widgets.clear()
        self._me_active_images = [p for p in self._me_active_images if p.exists()]

        if not self._me_active_images:
            lbl = tk.Label(
                self.me_grid_frame,
                text="No images found in selected folder.",
                font=(FONT_FAMILY, 12),
                bg=BG_DARK,
                fg=TEXT_DIM,
            )
            lbl.pack(pady=40)
            self._me_refresh_sidebar_ui()
            return

        COLS = 5
        for col_idx in range(COLS):
            self.me_grid_frame.columnconfigure(col_idx, weight=1, minsize=120)

        for i, path in enumerate(self._me_active_images):
            r = i // COLS
            c = i % COLS

            is_selected = i in self._me_selected_indices
            cell_bg = ACCENT_BLUE if is_selected else BG_CARD
            border_c = "#ffffff" if is_selected else BG_PANEL

            tile = tk.Frame(
                self.me_grid_frame,
                bg=cell_bg,
                padx=4,
                pady=4,
                highlightthickness=2,
                highlightbackground=border_c,
            )
            tile.grid(row=r, column=c, padx=5, pady=5, sticky="nsew")

            thumb = self._me_get_thumbnail(path)
            if thumb:
                lbl_img = tk.Label(tile, image=thumb, bg=cell_bg)
            else:
                lbl_img = tk.Label(tile, text="⚠ Error", font=(FONT_FAMILY, 8), bg=cell_bg, fg=ACCENT_RED)
            lbl_img.pack(pady=(2, 2))

            fg_txt = BG_DARK if is_selected else TEXT_MAIN
            lbl_name = tk.Label(
                tile,
                text=path.name,
                font=(FONT_FAMILY, 8, "bold" if is_selected else "normal"),
                bg=cell_bg,
                fg=fg_txt,
                wraplength=105,
                justify="center",
            )
            lbl_name.pack(pady=(0, 2))

            # Bind click events on tile and child widgets for multi-select and double-click to open in Image Viewer
            for widget in (tile, lbl_img, lbl_name):
                widget.bind("<Button-1>", lambda e, idx=i: self._me_on_tile_clicked(idx, e))
                widget.bind("<Double-Button-1>", lambda e, idx=i: self._me_on_tile_double_clicked(idx, e))
                widget.bind("<MouseWheel>", lambda e: self.me_grid_canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

            self._me_tile_widgets.append({
                "tile": tile,
                "lbl_img": lbl_img,
                "lbl_name": lbl_name,
                "path": path,
            })

        self._me_refresh_sidebar_ui()

    def _me_on_tile_clicked(self, idx: int, event):
        state = event.state
        ctrl_pressed = bool(state & 0x0004) or (getattr(event, "keysym", "") in ('Control_L', 'Control_R'))
        shift_pressed = bool(state & 0x0001) or (getattr(event, "keysym", "") in ('Shift_L', 'Shift_R'))

        if shift_pressed and self._me_last_clicked_index is not None:
            start = min(self._me_last_clicked_index, idx)
            end = max(self._me_last_clicked_index, idx)
            for i in range(start, end + 1):
                self._me_selected_indices.add(i)
        elif ctrl_pressed:
            if idx in self._me_selected_indices:
                self._me_selected_indices.remove(idx)
            else:
                self._me_selected_indices.add(idx)
            self._me_last_clicked_index = idx
        else:
            self._me_selected_indices = {idx}
            self._me_last_clicked_index = idx

        self._me_update_tile_selection_styles()
        self._me_refresh_sidebar_ui()

    def _me_on_tile_double_clicked(self, idx: int, event=None):
        """Auto open double-clicked image from Mass Edit in Image Viewer."""
        if idx < 0 or idx >= len(self._me_active_images):
            return

        target_path = self._me_active_images[idx]
        if not target_path.exists():
            return

        # 1. Prevent _switch_mode from re-scanning a large directory synchronously
        dir_path = self.var_dir.get()
        if dir_path and dir_path != "No directory selected" and os.path.isdir(dir_path):
            self._fv_root_dir = Path(dir_path)
        else:
            self._fv_root_dir = getattr(self, "_me_root_dir", None)

        # 2. Switch mode to Image Viewer FIRST so frame is packed & UI is visible
        self._switch_mode("folder_viewer")

        # 3. Mirror the exact state from Mass Edit into Image Viewer so work can continue seamlessly
        self._fv_all_images = list(self._me_all_images)
        self._fv_active_images = list(self._me_active_images)
        self._fv_folders = getattr(self, "_me_folders", {}).copy()
        self._fv_folder_list = getattr(self, "_me_folder_list", []).copy()

        if hasattr(self, "_combo_fv_folders") and hasattr(self, "_combo_me_folders"):
            self._combo_fv_folders["values"] = self._combo_me_folders["values"]
            if self._combo_me_folders["values"]:
                try:
                    self._combo_fv_folders.current(self._combo_me_folders.current())
                except Exception:
                    pass

        # 4. Set the viewer to the exact image that was double-clicked
        try:
            self._fv_index = self._fv_active_images.index(target_path)
        except ValueError:
            self._fv_index = 0

        # 5. Refresh layout geometry and display the image
        self.update_idletasks()
        self._fv_show_current()
        self._update_status(f"Opened {target_path.name} in Image Viewer.")

    def _me_select_all(self):
        self._me_selected_indices = set(range(len(self._me_active_images)))
        self._me_update_tile_selection_styles()
        self._me_refresh_sidebar_ui()

    def _me_deselect_all(self):
        self._me_selected_indices.clear()
        self._me_last_clicked_index = None
        self._me_update_tile_selection_styles()
        self._me_refresh_sidebar_ui()

    def _me_update_tile_selection_styles(self):
        """Update tile colors and borders dynamically without full grid rebuild."""
        for i, item in enumerate(self._me_tile_widgets):
            is_selected = i in self._me_selected_indices
            cell_bg = ACCENT_BLUE if is_selected else BG_CARD
            border_c = "#ffffff" if is_selected else BG_PANEL
            fg_txt = BG_DARK if is_selected else TEXT_MAIN

            item["tile"].config(bg=cell_bg, highlightbackground=border_c)
            item["lbl_img"].config(bg=cell_bg)
            item["lbl_name"].config(bg=cell_bg, fg=fg_txt, font=(FONT_FAMILY, 8, "bold" if is_selected else "normal"))

    def _me_refresh_sidebar_ui(self):
        num_sel = len(self._me_selected_indices)
        total = len(self._me_active_images)
        self.lbl_me_counter.config(text=f"Selected: {num_sel} of {total} images")
        self.lbl_me_selection_status.config(text=f"{num_sel} image(s) selected")

        # 1. Update Active Common Tags UI
        for w in self.frame_me_active_tags.winfo_children():
            w.destroy()

        if num_sel == 0:
            lbl = tk.Label(
                self.frame_me_active_tags,
                text="(No images highlighted — click or Shift/Ctrl click images)",
                font=(FONT_FAMILY, 8, "italic"),
                bg=BG_CARD,
                fg=TEXT_DIM,
            )
            lbl.pack(anchor="w")
        else:
            selected_paths = [self._me_active_images[i] for i in self._me_selected_indices if i < len(self._me_active_images)]
            tag_sets = []
            for p in selected_paths:
                try:
                    tag_sets.append(set(read_image_tags(p)))
                except Exception:
                    tag_sets.append(set())

            if tag_sets:
                common_tags = sorted(list(set.intersection(*tag_sets)))
            else:
                common_tags = []

            if common_tags:
                chips_frame = tk.Frame(self.frame_me_active_tags, bg=BG_CARD)
                chips_frame.pack(fill="x")

                for tag in common_tags:
                    pill = tk.Frame(chips_frame, bg=COLOR_KEEP, padx=6, pady=2)
                    pill.pack(side="left", padx=2, pady=2)

                    lbl_t = tk.Label(
                        pill,
                        text=tag,
                        font=(FONT_FAMILY, 8, "bold"),
                        bg=COLOR_KEEP,
                        fg="#ffffff",
                    )
                    lbl_t.pack(side="left", padx=(0, 4))

                    btn_x = tk.Label(
                        pill,
                        text="✕",
                        font=(FONT_FAMILY, 8, "bold"),
                        bg=COLOR_KEEP,
                        fg=ACCENT_AMBER,
                        cursor="hand2",
                    )
                    btn_x.pack(side="right")
                    btn_x.bind("<Button-1>", lambda e, t=tag: self._me_remove_common_tag(t))
            else:
                lbl = tk.Label(
                    self.frame_me_active_tags,
                    text="(Selected images have no identical tags in common)",
                    font=(FONT_FAMILY, 8, "italic"),
                    bg=BG_CARD,
                    fg=ACCENT_AMBER,
                    wraplength=260,
                    justify="left",
                )
                lbl.pack(anchor="w")

        # 2. Update Universal App Keywords Chips UI
        for w in self.frame_me_known_keywords.winfo_children():
            w.destroy()

        available = sorted(list(self._known_keywords))
        if not available:
            lbl = tk.Label(
                self.frame_me_known_keywords,
                text="(No universal tags saved yet)",
                font=(FONT_FAMILY, 8, "italic"),
                bg=BG_CARD,
                fg=TEXT_DIM,
            )
            lbl.pack(anchor="w")
        else:
            current_row = tk.Frame(self.frame_me_known_keywords, bg=BG_CARD)
            current_row.pack(fill="x", pady=1)
            current_char_count = 0

            for kw in available:
                chip_text = f"+ {kw}"
                chip_len = len(chip_text) + 2
                if current_char_count > 0 and current_char_count + chip_len > 28:
                    current_row = tk.Frame(self.frame_me_known_keywords, bg=BG_CARD)
                    current_row.pack(fill="x", pady=1)
                    current_char_count = 0

                btn = tk.Button(
                    current_row,
                    text=chip_text,
                    font=(FONT_FAMILY, 7, "bold"),
                    bg=BG_PANEL,
                    fg=ACCENT_GREEN,
                    activebackground=ACCENT_BLUE,
                    activeforeground=BG_DARK,
                    relief="flat",
                    cursor="hand2",
                    padx=4,
                    pady=1,
                    command=lambda t=kw: self._me_add_tag_to_selected(t),
                )
                btn.pack(side="left", padx=2, pady=2)
                current_char_count += chip_len

    def _me_add_tag_to_selected(self, tag: str):
        cleaned = tag.strip()
        if not cleaned or not self._me_selected_indices:
            return

        self._known_keywords.add(cleaned)
        self._save_immich_config()
        selected_paths = [self._me_active_images[i] for i in self._me_selected_indices if i < len(self._me_active_images)]

        count = 0
        already_had_count = 0
        for p in selected_paths:
            tags = read_image_tags(p)
            existing_lower = {t.lower() for t in tags}
            if cleaned.lower() not in existing_lower:
                tags.append(cleaned)
                if write_image_tags(p, tags):
                    count += 1
            else:
                already_had_count += 1

        self.var_me_tag_entry.set("")
        self._me_hide_tag_suggestions()
        self._me_refresh_sidebar_ui()
        if already_had_count > 0:
            self._update_status(f"Added tag '{cleaned}' to {count} image(s) ({already_had_count} already had this tag).")
        else:
            self._update_status(f"Added tag '{cleaned}' to {count} selected image(s).")

    def _me_remove_common_tag(self, tag: str):
        if not self._me_selected_indices:
            return

        selected_paths = [self._me_active_images[i] for i in self._me_selected_indices if i < len(self._me_active_images)]
        for p in selected_paths:
            tags = read_image_tags(p)
            if tag in tags:
                tags.remove(tag)
                write_image_tags(p, tags)

        self._me_refresh_sidebar_ui()
        self._update_status(f"Removed tag '{tag}' from {len(selected_paths)} selected image(s).")

    def _me_clear_common_tags(self):
        if not self._me_selected_indices:
            return

        selected_paths = [self._me_active_images[i] for i in self._me_selected_indices if i < len(self._me_active_images)]
        for p in selected_paths:
            write_image_tags(p, [])

        self._me_refresh_sidebar_ui()
        self._update_status(f"Cleared all tags from {len(selected_paths)} selected image(s).")

    def _me_add_current_tag(self):
        val = self.var_me_tag_entry.get().strip()
        if val:
            self._me_add_tag_to_selected(val)

    def _me_on_tag_entry_changed(self, event=None):
        val = self.var_me_tag_entry.get().strip().lower()
        if not val:
            self._me_hide_tag_suggestions()
            return

        matches = [kw for kw in sorted(self._known_keywords) if val in kw.lower()]
        if not matches:
            self._me_hide_tag_suggestions()
            return

        self.listbox_me_suggestions.delete(0, tk.END)
        for kw in matches[:6]:
            self.listbox_me_suggestions.insert(tk.END, kw)

        self.frame_me_suggestions.pack(fill="x", pady=(4, 0))

    def _me_hide_tag_suggestions(self):
        self.frame_me_suggestions.pack_forget()

    def _me_on_tag_suggestion_clicked(self, event=None):
        try:
            sel = self.listbox_me_suggestions.curselection()
            if sel:
                kw = self.listbox_me_suggestions.get(sel[0])
                self._me_add_tag_to_selected(kw)
        except Exception:
            pass

    def _me_rotate_selected(self):
        if not self._me_selected_indices:
            messagebox.showinfo("No Selection", "Please highlight images to rotate.")
            return

        selected_paths = [self._me_active_images[i] for i in self._me_selected_indices if i < len(self._me_active_images)]
        count = 0
        for p in selected_paths:
            try:
                with Image.open(p) as img:
                    rotated = img.transpose(Image.Transpose.ROTATE_270)
                    kwargs = {}
                    if "exif" in img.info:
                        kwargs["exif"] = img.info["exif"]
                    if img.format in ["JPEG", "MPO"]:
                        kwargs["quality"] = 95
                    rotated.save(p, **kwargs)

                self._me_thumb_cache.pop(p, None)
                count += 1
            except Exception as e:
                print(f"Error rotating {p}: {e}")

        self._me_render_grid()
        self._update_status(f"Rotated {count} selected image(s) 90° clockwise.")

    def _me_trash_selected(self):
        if not self._me_selected_indices:
            messagebox.showinfo("No Selection", "Please highlight images to send to Trash.")
            return

        selected_paths = [self._me_active_images[i] for i in self._me_selected_indices if i < len(self._me_active_images)]
        if messagebox.askyesno(
            "Confirm Mass Delete",
            f"Are you sure you want to send {len(selected_paths)} highlighted image(s) to the Recycle Bin?",
            icon="warning",
        ):
            trashed = 0
            for p in selected_paths:
                if send_to_trash(p):
                    self._purge_deleted(p)
                    self._fv_remove_path(p)
                    self._me_thumb_cache.pop(p, None)
                    trashed += 1

            self._me_selected_indices.clear()
            self._me_last_clicked_index = None
            self._me_active_images = [p for p in self._me_active_images if p.exists()]
            self._me_render_grid()
            self._update_status(f"Sent {trashed} image(s) to the Recycle Bin.")

    # ── Immich Integration Mode Implementation ──────────────────────────────
    def _build_immich_area(self, parent: tk.Frame):
        content = tk.Frame(parent, bg=BG_DARK)
        content.pack(fill="both", expand=True, padx=20, pady=15)

        # Header Title Card
        title_card = tk.Frame(content, bg=BG_PANEL, padx=16, pady=12)
        title_card.pack(fill="x", pady=(0, 10))

        tk.Label(
            title_card,
            text="⚡ Immich Cloud & Server Workspace",
            font=(FONT_FAMILY, 13, "bold"),
            bg=BG_PANEL,
            fg=ACCENT_BLUE,
        ).pack(anchor="w", pady=(0, 2))

        tk.Label(
            title_card,
            text="Query asset metadata, manage tags and albums, upload images, and find photos by recognized face IDs directly from your Immich server.",
            font=(FONT_FAMILY, 9),
            bg=BG_PANEL,
            fg=TEXT_DIM,
            wraplength=950,
            justify="left",
        ).pack(anchor="w")

        # Sub-Navigation Bar for 4 Capabilities
        nav_bar = tk.Frame(content, bg=BG_DARK)
        nav_bar.pack(fill="x", pady=(0, 10))

        self._immich_sub_buttons = {}

        modes = [
            ("asset_info", "🔍 Asset Info & Metadata"),
            ("tags_albums", "🏷️ Tags & Albums"),
            ("upload", "📤 Upload Image"),
            ("people", "👤 Face & People Finder"),
        ]

        for mode_key, mode_label in modes:
            btn = self._make_button(
                nav_bar,
                mode_label,
                lambda m=mode_key: self._switch_immich_sub_mode(m),
                fg=TEXT_MAIN,
                bg=BG_CARD,
            )
            btn.pack(side="left", padx=(0, 8))
            self._immich_sub_buttons[mode_key] = btn

        # Container for the 4 Sub-Panels
        self._immich_sub_container = tk.Frame(content, bg=BG_DARK)
        self._immich_sub_container.pack(fill="both", expand=True)

        self._immich_sub_frames = {}

        # 1. Asset Info & Metadata Frame
        f_asset = tk.Frame(self._immich_sub_container, bg=BG_DARK)
        self._immich_sub_frames["asset_info"] = f_asset
        self._build_immich_sub_asset_info(f_asset)

        # 2. Tags & Albums Frame
        f_tags = tk.Frame(self._immich_sub_container, bg=BG_DARK)
        self._immich_sub_frames["tags_albums"] = f_tags
        self._build_immich_sub_tags_albums(f_tags)

        # 3. Upload Image Frame
        f_upload = tk.Frame(self._immich_sub_container, bg=BG_DARK)
        self._immich_sub_frames["upload"] = f_upload
        self._build_immich_sub_upload(f_upload)

        # 4. Face & People Finder Frame
        f_people = tk.Frame(self._immich_sub_container, bg=BG_DARK)
        self._immich_sub_frames["people"] = f_people
        self._build_immich_sub_people(f_people)

        # Default sub-mode
        self._switch_immich_sub_mode("asset_info")

    def _switch_immich_sub_mode(self, selected_mode: str):
        for mode_key, btn in self._immich_sub_buttons.items():
            if mode_key == selected_mode:
                btn.config(bg=ACCENT_BLUE, fg=BG_DARK)
            else:
                btn.config(bg=BG_CARD, fg=TEXT_MAIN)

        for mode_key, frame in self._immich_sub_frames.items():
            if mode_key == selected_mode:
                frame.pack(fill="both", expand=True)
            else:
                frame.pack_forget()

    # ── 1. Asset Info & Metadata Sub-Tab ─────────────────────────────
    def _build_immich_sub_asset_info(self, parent: tk.Frame):
        top_bar = tk.Frame(parent, bg=BG_CARD, padx=12, pady=10)
        top_bar.pack(fill="x", pady=(0, 10))

        tk.Label(top_bar, text="Asset ID:", font=(FONT_FAMILY, 9, "bold"), bg=BG_CARD, fg=TEXT_MAIN).pack(side="left", padx=(0, 6))
        e_asset = tk.Entry(top_bar, textvariable=self.var_immich_asset_id, font=(FONT_FAMILY, 9), bg=BG_PANEL, fg=TEXT_MAIN, insertbackground=TEXT_MAIN, relief="flat", width=36)
        e_asset.pack(side="left", padx=(0, 10), ipady=3)

        btn_fetch = self._make_button(top_bar, "🔍 Fetch Metadata", self._on_immich_fetch_asset, fg=BG_DARK, bg=ACCENT_BLUE)
        btn_fetch.pack(side="left", padx=(0, 8))

        btn_recent = self._make_button(top_bar, "📋 Load Recent Assets", self._on_immich_load_recent_assets, fg=TEXT_MAIN, bg=BG_PANEL)
        btn_recent.pack(side="left")

        body = tk.Frame(parent, bg=BG_DARK)
        body.pack(fill="both", expand=True)

        # Left: Asset List Treeview
        left_frame = tk.Frame(body, bg=BG_CARD, padx=10, pady=10)
        left_frame.pack(side="left", fill="both", expand=True, padx=(0, 6))

        tk.Label(left_frame, text="Asset Library List", font=(FONT_FAMILY, 10, "bold"), bg=BG_CARD, fg=ACCENT_GREEN).pack(anchor="w", pady=(0, 6))

        cols = ("filename", "id", "created")
        self.tree_immich_assets = ttk.Treeview(left_frame, columns=cols, show="headings", height=12)
        self.tree_immich_assets.heading("filename", text="Filename")
        self.tree_immich_assets.heading("id", text="Asset ID")
        self.tree_immich_assets.heading("created", text="Created At")

        self.tree_immich_assets.column("filename", width=180)
        self.tree_immich_assets.column("id", width=160)
        self.tree_immich_assets.column("created", width=140)

        sb = ttk.Scrollbar(left_frame, orient="vertical", command=self.tree_immich_assets.yview)
        self.tree_immich_assets.configure(yscrollcommand=sb.set)

        self.tree_immich_assets.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        tk.Label(
            left_frame,
            textvariable=self.var_immich_assets_count,
            font=(FONT_FAMILY, 9, "bold"),
            bg=BG_CARD,
            fg=ACCENT_GREEN,
            anchor="w",
        ).pack(anchor="w", pady=(6, 0))

        self.tree_immich_assets.bind("<<TreeviewSelect>>", self._on_immich_asset_tree_select)

        # Right: Detail Card & Preview
        right_frame = tk.Frame(body, bg=BG_CARD, padx=12, pady=10, width=380)
        right_frame.pack(side="right", fill="both", expand=False)
        right_frame.pack_propagate(False)

        tk.Label(right_frame, text="Metadata & EXIF Details", font=(FONT_FAMILY, 10, "bold"), bg=BG_CARD, fg=ACCENT_BLUE).pack(anchor="w", pady=(0, 6))

        self.lbl_immich_asset_thumb = tk.Label(right_frame, text="No Preview", bg=BG_PANEL, fg=TEXT_DIM, width=42, height=10)
        self.lbl_immich_asset_thumb.pack(fill="x", pady=(0, 8))

        self.txt_immich_asset_details = tk.Text(right_frame, font=(FONT_FAMILY, 9), bg=BG_PANEL, fg=TEXT_MAIN, relief="flat", wrap="word")
        self.txt_immich_asset_details.pack(fill="both", expand=True)

    # ── 2. Tags & Albums Sub-Tab ─────────────────────────────────────
    def _build_immich_sub_tags_albums(self, parent: tk.Frame):
        body = tk.Frame(parent, bg=BG_DARK)
        body.pack(fill="both", expand=True)

        # Left Column: Tags Manager
        col_tags = tk.Frame(body, bg=BG_CARD, padx=12, pady=12)
        col_tags.pack(side="left", fill="both", expand=True, padx=(0, 6))

        hdr_t = tk.Frame(col_tags, bg=BG_CARD)
        hdr_t.pack(fill="x", pady=(0, 8))
        tk.Label(hdr_t, text="🏷️ Immich Tags", font=(FONT_FAMILY, 11, "bold"), bg=BG_CARD, fg=ACCENT_BLUE).pack(side="left")
        self._make_button(hdr_t, "🔄 Refresh", self._on_immich_refresh_tags, fg=TEXT_MAIN, bg=BG_PANEL).pack(side="right")

        cols_t = ("name", "id", "type")
        self.tree_immich_tags = ttk.Treeview(col_tags, columns=cols_t, show="headings", height=8)
        self.tree_immich_tags.heading("name", text="Tag Name")
        self.tree_immich_tags.heading("id", text="Tag ID")
        self.tree_immich_tags.heading("type", text="Type")
        self.tree_immich_tags.column("name", width=140)
        self.tree_immich_tags.column("id", width=140)
        self.tree_immich_tags.column("type", width=70)
        self.tree_immich_tags.pack(fill="both", expand=True, pady=(0, 8))

        f_create_t = tk.Frame(col_tags, bg=BG_CARD)
        f_create_t.pack(fill="x", pady=(0, 6))
        tk.Label(f_create_t, text="New Tag:", font=(FONT_FAMILY, 9, "bold"), bg=BG_CARD, fg=TEXT_MAIN).pack(side="left", padx=(0, 4))
        tk.Entry(f_create_t, textvariable=self.var_immich_new_tag, font=(FONT_FAMILY, 9), bg=BG_PANEL, fg=TEXT_MAIN, insertbackground=TEXT_MAIN, relief="flat", width=18).pack(side="left", padx=(0, 6), ipady=3)
        self._make_button(f_create_t, "➕ Create Tag", self._on_immich_create_tag, fg=BG_DARK, bg=ACCENT_GREEN).pack(side="left")

        f_apply_t = tk.Frame(col_tags, bg=BG_CARD)
        f_apply_t.pack(fill="x")
        tk.Label(f_apply_t, text="Target Asset ID:", font=(FONT_FAMILY, 9, "bold"), bg=BG_CARD, fg=TEXT_MAIN).pack(side="left", padx=(0, 4))
        tk.Entry(f_apply_t, textvariable=self.var_immich_tag_target_asset, font=(FONT_FAMILY, 9), bg=BG_PANEL, fg=TEXT_MAIN, insertbackground=TEXT_MAIN, relief="flat", width=18).pack(side="left", padx=(0, 6), ipady=3)
        self._make_button(f_apply_t, "🏷️ Apply Tag", self._on_immich_apply_tag, fg=BG_DARK, bg=ACCENT_BLUE).pack(side="left")

        tk.Label(
            col_tags,
            textvariable=self.var_immich_tags_count,
            font=(FONT_FAMILY, 8, "bold"),
            bg=BG_CARD,
            fg=ACCENT_BLUE,
            anchor="w",
        ).pack(anchor="w", pady=(6, 0))

        # Right Column: Albums Manager
        col_albums = tk.Frame(body, bg=BG_CARD, padx=12, pady=12)
        col_albums.pack(side="right", fill="both", expand=True, padx=(6, 0))

        hdr_a = tk.Frame(col_albums, bg=BG_CARD)
        hdr_a.pack(fill="x", pady=(0, 8))
        tk.Label(hdr_a, text="🖼️ Immich Albums", font=(FONT_FAMILY, 11, "bold"), bg=BG_CARD, fg=ACCENT_GREEN).pack(side="left")
        self._make_button(hdr_a, "🔄 Refresh", self._on_immich_refresh_albums, fg=TEXT_MAIN, bg=BG_PANEL).pack(side="right")

        cols_a = ("name", "id", "assets")
        self.tree_immich_albums = ttk.Treeview(col_albums, columns=cols_a, show="headings", height=8)
        self.tree_immich_albums.heading("name", text="Album Name")
        self.tree_immich_albums.heading("id", text="Album ID")
        self.tree_immich_albums.heading("assets", text="Assets")
        self.tree_immich_albums.column("name", width=140)
        self.tree_immich_albums.column("id", width=140)
        self.tree_immich_albums.column("assets", width=70)
        self.tree_immich_albums.pack(fill="both", expand=True, pady=(0, 8))

        f_create_a = tk.Frame(col_albums, bg=BG_CARD)
        f_create_a.pack(fill="x", pady=(0, 6))
        tk.Label(f_create_a, text="New Album:", font=(FONT_FAMILY, 9, "bold"), bg=BG_CARD, fg=TEXT_MAIN).pack(side="left", padx=(0, 4))
        tk.Entry(f_create_a, textvariable=self.var_immich_new_album, font=(FONT_FAMILY, 9), bg=BG_PANEL, fg=TEXT_MAIN, insertbackground=TEXT_MAIN, relief="flat", width=18).pack(side="left", padx=(0, 6), ipady=3)
        self._make_button(f_create_a, "➕ Create Album", self._on_immich_create_album, fg=BG_DARK, bg=ACCENT_GREEN).pack(side="left")

        f_apply_a = tk.Frame(col_albums, bg=BG_CARD)
        f_apply_a.pack(fill="x")
        tk.Label(f_apply_a, text="Target Asset ID:", font=(FONT_FAMILY, 9, "bold"), bg=BG_CARD, fg=TEXT_MAIN).pack(side="left", padx=(0, 4))
        tk.Entry(f_apply_a, textvariable=self.var_immich_album_target_asset, font=(FONT_FAMILY, 9), bg=BG_PANEL, fg=TEXT_MAIN, insertbackground=TEXT_MAIN, relief="flat", width=18).pack(side="left", padx=(0, 6), ipady=3)
        self._make_button(f_apply_a, "🖼️ Add to Album", self._on_immich_add_to_album, fg=BG_DARK, bg=ACCENT_BLUE).pack(side="left")

        tk.Label(
            col_albums,
            textvariable=self.var_immich_albums_count,
            font=(FONT_FAMILY, 8, "bold"),
            bg=BG_CARD,
            fg=ACCENT_GREEN,
            anchor="w",
        ).pack(anchor="w", pady=(6, 0))

    # ── 3. Upload Image Sub-Tab ──────────────────────────────────────
    def _build_immich_sub_upload(self, parent: tk.Frame):
        card = tk.Frame(parent, bg=BG_CARD, padx=24, pady=20)
        card.pack(fill="both", expand=True)

        tk.Label(card, text="📤 Upload Image File to Immich Server", font=(FONT_FAMILY, 12, "bold"), bg=BG_CARD, fg=ACCENT_BLUE).pack(anchor="w", pady=(0, 10))

        file_row = tk.Frame(card, bg=BG_CARD)
        file_row.pack(fill="x", pady=(0, 12))

        self._make_button(file_row, "📁 Choose Local Image File", self._on_immich_select_upload_file, fg=BG_DARK, bg=ACCENT_GREEN).pack(side="left", padx=(0, 10))
        tk.Label(file_row, textvariable=self.var_immich_upload_file_path, font=(FONT_FAMILY, 9), bg=BG_CARD, fg=TEXT_MAIN, anchor="w").pack(side="left", fill="x", expand=True)

        # Upload Preview & Action
        content = tk.Frame(card, bg=BG_CARD)
        content.pack(fill="both", expand=True, pady=(0, 10))

        self.lbl_immich_upload_preview = tk.Label(content, text="No Image Selected", bg=BG_PANEL, fg=TEXT_DIM, width=40, height=12)
        self.lbl_immich_upload_preview.pack(side="left", padx=(0, 16))

        right_info = tk.Frame(content, bg=BG_CARD)
        right_info.pack(side="left", fill="both", expand=True)

        self.lbl_immich_upload_file_info = tk.Label(right_info, text="Select an image file above to view file details.", font=(FONT_FAMILY, 9), bg=BG_CARD, fg=TEXT_DIM, justify="left", anchor="nw")
        self.lbl_immich_upload_file_info.pack(anchor="nw", fill="both", expand=True, pady=(0, 10))

        self.btn_immich_upload_action = self._make_button(right_info, "📤 Start Upload to Immich", self._on_immich_do_upload, fg=BG_DARK, bg=ACCENT_BLUE)
        self.btn_immich_upload_action.pack(anchor="w", pady=(0, 10))
        self.btn_immich_upload_action.config(state="disabled")

        tk.Label(right_info, textvariable=self.var_immich_upload_status, font=(FONT_FAMILY, 9, "bold"), bg=BG_CARD, fg=ACCENT_AMBER, anchor="w").pack(anchor="w")

    # ── 4. Face & People Finder Sub-Tab ──────────────────────────────
    def _build_immich_sub_people(self, parent: tk.Frame):
        body = tk.Frame(parent, bg=BG_DARK)
        body.pack(fill="both", expand=True)

        # Left Column: Recognized People List (Req 1: Query for Existing Names)
        left_col = tk.Frame(body, bg=BG_CARD, padx=12, pady=12)
        left_col.pack(side="left", fill="both", expand=True, padx=(0, 6))

        hdr = tk.Frame(left_col, bg=BG_CARD)
        hdr.pack(fill="x", pady=(0, 8))
        tk.Label(hdr, text="👤 Recognized People / Names", font=(FONT_FAMILY, 11, "bold"), bg=BG_CARD, fg=ACCENT_BLUE).pack(side="left")
        self._make_button(hdr, "🔄 Query Names", self._on_immich_refresh_people, fg=BG_DARK, bg=ACCENT_GREEN).pack(side="right")

        f_filter = tk.Frame(left_col, bg=BG_CARD)
        f_filter.pack(fill="x", pady=(0, 6))
        tk.Label(f_filter, text="Filter:", font=(FONT_FAMILY, 9), bg=BG_CARD, fg=TEXT_DIM).pack(side="left", padx=(0, 4))
        e_filt = tk.Entry(f_filter, textvariable=self.var_immich_person_filter, font=(FONT_FAMILY, 9), bg=BG_PANEL, fg=TEXT_MAIN, insertbackground=TEXT_MAIN, relief="flat")
        e_filt.pack(side="left", fill="x", expand=True, ipady=3)
        self.var_immich_person_filter.trace_add("write", lambda *args: self._filter_immich_people_tree())

        cols_p = ("name", "id")
        self.tree_immich_people = ttk.Treeview(left_col, columns=cols_p, show="headings", height=10)
        self.tree_immich_people.heading("name", text="Name / ID Label")
        self.tree_immich_people.heading("id", text="Person ID")
        self.tree_immich_people.column("name", width=180)
        self.tree_immich_people.column("id", width=180)

        sb_p = ttk.Scrollbar(left_col, orient="vertical", command=self.tree_immich_people.yview)
        self.tree_immich_people.configure(yscrollcommand=sb_p.set)
        self.tree_immich_people.pack(side="left", fill="both", expand=True)
        sb_p.pack(side="right", fill="y")

        tk.Label(
            left_col,
            textvariable=self.var_immich_people_count,
            font=(FONT_FAMILY, 9, "bold"),
            bg=BG_CARD,
            fg=ACCENT_BLUE,
            anchor="w",
        ).pack(anchor="w", pady=(6, 0))

        self.tree_immich_people.bind("<<TreeviewSelect>>", self._on_immich_person_select)

        # Right Column: Person's Tagged Assets (Req 2: Retrieve all assets tagged with ID)
        right_col = tk.Frame(body, bg=BG_CARD, padx=12, pady=12)
        right_col.pack(side="right", fill="both", expand=True, padx=(6, 0))

        hdr_r = tk.Frame(right_col, bg=BG_CARD)
        hdr_r.pack(fill="x", pady=(0, 8))
        self.lbl_immich_person_header = tk.Label(hdr_r, text="Assets for Selected Person", font=(FONT_FAMILY, 11, "bold"), bg=BG_CARD, fg=ACCENT_GREEN)
        self.lbl_immich_person_header.pack(side="left")

        self.btn_immich_person_assets = self._make_button(hdr_r, "🔍 Fetch Person Assets", self._on_immich_load_person_assets, fg=BG_DARK, bg=ACCENT_BLUE)
        self.btn_immich_person_assets.pack(side="right")
        self.btn_immich_person_assets.config(state="disabled")

        cols_pa = ("filename", "id", "created", "path")
        self.tree_immich_person_assets = ttk.Treeview(right_col, columns=cols_pa, show="headings", height=10)
        self.tree_immich_person_assets.heading("filename", text="Filename")
        self.tree_immich_person_assets.heading("id", text="Asset ID")
        self.tree_immich_person_assets.heading("created", text="Created At")
        self.tree_immich_person_assets.heading("path", text="Original Path")
        self.tree_immich_person_assets.column("filename", width=130)
        self.tree_immich_person_assets.column("id", width=130)
        self.tree_immich_person_assets.column("created", width=110)
        self.tree_immich_person_assets.column("path", width=220)

        sb_pa = ttk.Scrollbar(right_col, orient="vertical", command=self.tree_immich_person_assets.yview)
        self.tree_immich_person_assets.configure(yscrollcommand=sb_pa.set)
        self.tree_immich_person_assets.pack(fill="both", expand=True)
        sb_pa.pack(side="right", fill="y")

        tk.Label(
            right_col,
            textvariable=self.var_immich_person_assets_count,
            font=(FONT_FAMILY, 9, "bold"),
            bg=BG_CARD,
            fg=ACCENT_GREEN,
            anchor="w",
        ).pack(anchor="w", pady=(6, 0))

        # Local Path Mapping & Mass Edit Bridge Card
        map_card = tk.Frame(right_col, bg=BG_PANEL, padx=12, pady=10)
        map_card.pack(fill="x", pady=(10, 0))

        tk.Label(
            map_card,
            text="Local Folder Mapping for Mass Edit",
            font=(FONT_FAMILY, 9, "bold"),
            bg=BG_PANEL,
            fg=ACCENT_BLUE,
        ).pack(anchor="w", pady=(0, 4))

        # Target Local Folder Row
        row_loc = tk.Frame(map_card, bg=BG_PANEL)
        row_loc.pack(fill="x", pady=2)
        tk.Label(row_loc, text="Local Path:", font=(FONT_FAMILY, 8, "bold"), bg=BG_PANEL, fg=TEXT_MAIN, width=12, anchor="w").pack(side="left")
        e_loc = tk.Entry(row_loc, textvariable=self.var_immich_local_path, font=(FONT_FAMILY, 8), bg=BG_CARD, fg=TEXT_MAIN, insertbackground=TEXT_MAIN, relief="flat")
        e_loc.pack(side="left", fill="x", expand=True, padx=(0, 6), ipady=2)
        self._make_button(row_loc, "📁 Target Folder (Browse)", self._on_immich_browse_local_path, fg=BG_DARK, bg=ACCENT_GREEN).pack(side="right")

        # Server Path Prefix & Open in Mass Edit Row
        row_srv = tk.Frame(map_card, bg=BG_PANEL)
        row_srv.pack(fill="x", pady=2)
        tk.Label(row_srv, text="Server Prefix:", font=(FONT_FAMILY, 8, "bold"), bg=BG_PANEL, fg=TEXT_MAIN, width=12, anchor="w").pack(side="left")
        e_srv = tk.Entry(row_srv, textvariable=self.var_immich_server_prefix, font=(FONT_FAMILY, 8), bg=BG_CARD, fg=TEXT_MAIN, insertbackground=TEXT_MAIN, relief="flat")
        e_srv.pack(side="left", fill="x", expand=True, padx=(0, 6), ipady=2)

        self.btn_open_in_mass_edit = self._make_button(
            row_srv,
            "📂 Open in Mass Edit",
            self._on_immich_open_person_in_mass_edit,
            fg=BG_DARK,
            bg=ACCENT_BLUE,
        )
        self.btn_open_in_mass_edit.pack(side="right")

    # ── Immich Event Handlers & API Callbacks ────────────────────────
    def _on_immich_test_click(self):
        url = self.var_immich_url.get().strip()
        key = self.var_immich_key.get().strip()
        self.var_immich_status.set("Testing communication with Immich server…")
        if hasattr(self, "lbl_immich_top_status"):
            self.lbl_immich_top_status.config(fg=ACCENT_AMBER)
        self.update_idletasks()

        def _bg_test():
            success, msg = test_immich_connection(url, key)
            if success:
                self.var_immich_status.set(f"✅ {msg}")
                if hasattr(self, "lbl_immich_top_status"):
                    self.lbl_immich_top_status.config(fg=ACCENT_GREEN)
                self._update_status(f"Immich: {msg}")
            else:
                self.var_immich_status.set(f"❌ {msg}")
                if hasattr(self, "lbl_immich_top_status"):
                    self.lbl_immich_top_status.config(fg=ACCENT_RED)
                self._update_status(f"Immich Error: {msg}")

        threading.Thread(target=_bg_test, daemon=True).start()

    def _on_immich_fetch_asset(self):
        asset_id = self.var_immich_asset_id.get().strip()
        if not asset_id:
            messagebox.showwarning("Missing Asset ID", "Please enter an Immich Asset ID to fetch metadata.")
            return

        url = self.var_immich_url.get()
        key = self.var_immich_key.get()

        def _bg():
            ok, info = immich_get_asset_info(url, key, asset_id)
            if ok and isinstance(info, dict):
                lines = [
                    f"Filename: {info.get('originalFileName', 'N/A')}",
                    f"Asset ID: {info.get('id', 'N/A')}",
                    f"Type: {info.get('type', 'IMAGE')}",
                    f"Format: {info.get('originalMimeType', 'N/A')}",
                    f"Created: {info.get('fileCreatedAt', 'N/A')}",
                    f"Updated: {info.get('fileModifiedAt', 'N/A')}",
                ]
                exif = info.get("exifInfo", {})
                if exif:
                    lines.extend([
                        "\n--- EXIF Metadata ---",
                        f"Make/Model: {exif.get('make', '')} {exif.get('model', '')}",
                        f"Exposure: {exif.get('exposureTime', 'N/A')} s, f/{exif.get('fNumber', 'N/A')}",
                        f"ISO: {exif.get('iso', 'N/A')}",
                        f"Focal Length: {exif.get('focalLength', 'N/A')} mm",
                    ])
                tags = info.get("tags", [])
                if tags:
                    lines.append(f"\nTags: {', '.join(t.get('name', '') for t in tags)}")
                people = info.get("people", [])
                if people:
                    lines.append(f"People: {', '.join(p.get('name', 'Unnamed') for p in people)}")

                txt = "\n".join(lines)
                self.txt_immich_asset_details.delete("1.0", "end")
                self.txt_immich_asset_details.insert("1.0", txt)

                thumb_bytes = immich_download_thumbnail(url, key, asset_id)
                if thumb_bytes:
                    try:
                        import io
                        im = Image.open(io.BytesIO(thumb_bytes))
                        im.thumbnail((260, 180))
                        photo = ImageTk.PhotoImage(im)
                        self._immich_thumb_cache[asset_id] = photo
                        self.lbl_immich_asset_thumb.config(image=photo, text="")
                    except Exception:
                        pass
            else:
                messagebox.showerror("Asset Error", f"Could not retrieve asset details:\n{info}")

        threading.Thread(target=_bg, daemon=True).start()

    def _on_immich_load_recent_assets(self):
        url = self.var_immich_url.get()
        key = self.var_immich_key.get()

        def _bg():
            ok, assets = immich_get_recent_assets(url, key, limit=50)
            if ok and isinstance(assets, list):
                for item in self.tree_immich_assets.get_children():
                    self.tree_immich_assets.delete(item)
                for a in assets:
                    fn = a.get("originalFileName") or a.get("filename") or "Asset"
                    aid = a.get("id", "")
                    created = str(a.get("fileCreatedAt", ""))[:19].replace("T", " ")
                    self.tree_immich_assets.insert("", "end", iid=aid, values=(fn, aid, created))
                self.var_immich_assets_count.set(f"Total found: {len(assets)} asset(s)")
                self._update_status(f"Loaded {len(assets)} recent Immich assets.")
            else:
                self.var_immich_assets_count.set("Total found: 0 asset(s)")
                messagebox.showerror("Error", f"Failed to load assets:\n{assets}")

        threading.Thread(target=_bg, daemon=True).start()

    def _on_immich_asset_tree_select(self, event):
        sel = self.tree_immich_assets.selection()
        if sel:
            asset_id = sel[0]
            self.var_immich_asset_id.set(asset_id)
            self._on_immich_fetch_asset()

    def _on_immich_refresh_tags(self):
        url = self.var_immich_url.get()
        key = self.var_immich_key.get()

        def _bg():
            ok, tags = immich_get_tags(url, key)
            if ok and isinstance(tags, list):
                for item in self.tree_immich_tags.get_children():
                    self.tree_immich_tags.delete(item)
                for t in tags:
                    name = t.get("name")
                    if name:
                        self._known_keywords.add(name)
                    self.tree_immich_tags.insert("", "end", values=(t.get("name", ""), t.get("id", ""), t.get("type", "USER")))
                self.after(0, self._save_immich_config)
                self.var_immich_tags_count.set(f"Total found: {len(tags)} tag(s)")
                self._update_status(f"Retrieved {len(tags)} Immich tags.")
            else:
                self.var_immich_tags_count.set("Total found: 0 tag(s)")
                messagebox.showerror("Tags Error", f"Failed to retrieve tags:\n{tags}")

        threading.Thread(target=_bg, daemon=True).start()

    def _on_immich_create_tag(self):
        tag_name = self.var_immich_new_tag.get().strip()
        if not tag_name:
            return
        url = self.var_immich_url.get()
        key = self.var_immich_key.get()

        def _bg():
            ok, msg = immich_create_tag(url, key, tag_name)
            if ok:
                self._known_keywords.add(tag_name)
                self.after(0, self._save_immich_config)
                self.var_immich_new_tag.set("")
                self._on_immich_refresh_tags()
                messagebox.showinfo("Success", msg)
            else:
                messagebox.showerror("Error", msg)

        threading.Thread(target=_bg, daemon=True).start()

    def _on_immich_apply_tag(self):
        asset_id = self.var_immich_tag_target_asset.get().strip()
        sel_tag = self.tree_immich_tags.selection()
        if not asset_id or not sel_tag:
            messagebox.showwarning("Selection Required", "Please select a tag from the list and enter a target Asset ID.")
            return
        tag_id = self.tree_immich_tags.item(sel_tag[0])["values"][1]
        url = self.var_immich_url.get()
        key = self.var_immich_key.get()

        def _bg():
            ok, msg = immich_add_tag_to_asset(url, key, tag_id, asset_id)
            if ok:
                messagebox.showinfo("Success", msg)
            else:
                messagebox.showerror("Error", msg)

        threading.Thread(target=_bg, daemon=True).start()

    def _on_immich_refresh_albums(self):
        url = self.var_immich_url.get()
        key = self.var_immich_key.get()

        def _bg():
            ok, albums = immich_get_albums(url, key)
            if ok and isinstance(albums, list):
                for item in self.tree_immich_albums.get_children():
                    self.tree_immich_albums.delete(item)
                for a in albums:
                    count = a.get("assetCount") or len(a.get("assets", []))
                    self.tree_immich_albums.insert("", "end", values=(a.get("albumName", ""), a.get("id", ""), count))
                self.var_immich_albums_count.set(f"Total found: {len(albums)} album(s)")
                self._update_status(f"Retrieved {len(albums)} Immich albums.")
            else:
                self.var_immich_albums_count.set("Total found: 0 album(s)")
                messagebox.showerror("Albums Error", f"Failed to retrieve albums:\n{albums}")

        threading.Thread(target=_bg, daemon=True).start()

    def _on_immich_create_album(self):
        album_name = self.var_immich_new_album.get().strip()
        if not album_name:
            return
        url = self.var_immich_url.get()
        key = self.var_immich_key.get()

        def _bg():
            ok, msg = immich_create_album(url, key, album_name)
            if ok:
                self.var_immich_new_album.set("")
                self._on_immich_refresh_albums()
                messagebox.showinfo("Success", msg)
            else:
                messagebox.showerror("Error", msg)

        threading.Thread(target=_bg, daemon=True).start()

    def _on_immich_add_to_album(self):
        asset_id = self.var_immich_album_target_asset.get().strip()
        sel_album = self.tree_immich_albums.selection()
        if not asset_id or not sel_album:
            messagebox.showwarning("Selection Required", "Please select an album from the list and enter a target Asset ID.")
            return
        album_id = self.tree_immich_albums.item(sel_album[0])["values"][1]
        url = self.var_immich_url.get()
        key = self.var_immich_key.get()

        def _bg():
            ok, msg = immich_add_asset_to_album(url, key, album_id, asset_id)
            if ok:
                self._on_immich_refresh_albums()
                messagebox.showinfo("Success", msg)
            else:
                messagebox.showerror("Error", msg)

        threading.Thread(target=_bg, daemon=True).start()

    def _on_immich_select_upload_file(self):
        fn = filedialog.askopenfilename(
            title="Select Image to Upload to Immich",
            filetypes=[("Image Files", "*.jpg *.jpeg *.png *.webp *.tiff *.tif *.bmp"), ("All Files", "*.*")]
        )
        if not fn:
            return

        p = Path(fn)
        self.var_immich_upload_file_path.set(str(p))
        sz_mb = p.stat().st_size / (1024 * 1024)

        info_txt = f"Filename: {p.name}\nPath: {p}\nFile Size: {sz_mb:.2f} MB"
        try:
            with Image.open(p) as im:
                info_txt += f"\nDimensions: {im.width} x {im.height} px\nFormat: {im.format}"
                im_copy = im.copy()
                im_copy.thumbnail((260, 200))
                photo = ImageTk.PhotoImage(im_copy)
                self.lbl_immich_upload_preview.config(image=photo, text="")
                self._upload_preview_photo = photo
        except Exception as e:
            info_txt += f"\nPreview Error: {e}"

        self.lbl_immich_upload_file_info.config(text=info_txt)
        self.btn_immich_upload_action.config(state="normal")
        self.var_immich_upload_status.set("Ready to upload")

    def _on_immich_do_upload(self):
        file_path = self.var_immich_upload_file_path.get().strip()
        if not file_path:
            return

        url = self.var_immich_url.get()
        key = self.var_immich_key.get()
        self.var_immich_upload_status.set("Uploading image to Immich server…")
        self.btn_immich_upload_action.config(state="disabled")

        def _bg():
            ok, msg = immich_upload_asset(url, key, file_path)
            if ok:
                self.var_immich_upload_status.set(f"✅ {msg}")
                messagebox.showinfo("Upload Complete", msg)
            else:
                self.var_immich_upload_status.set(f"❌ {msg}")
                messagebox.showerror("Upload Failed", msg)
            self.btn_immich_upload_action.config(state="normal")

        threading.Thread(target=_bg, daemon=True).start()

    def _on_immich_refresh_people(self):
        url = self.var_immich_url.get()
        key = self.var_immich_key.get()

        def _bg():
            ok, people = immich_get_people(url, key)
            if ok and isinstance(people, list):
                self._immich_people_cache = people
                self._filter_immich_people_tree()
                self._update_status(f"Retrieved {len(people)} recognized people from Immich.")
            else:
                messagebox.showerror("People Query Error", f"Could not retrieve recognized people:\n{people}")

        threading.Thread(target=_bg, daemon=True).start()

    def _filter_immich_people_tree(self):
        filt = self.var_immich_person_filter.get().strip().lower()
        for item in self.tree_immich_people.get_children():
            self.tree_immich_people.delete(item)

        for p in self._immich_people_cache:
            name = p.get("name") or "Unnamed Person"
            pid = p.get("id", "")
            if not filt or filt in name.lower() or filt in pid.lower():
                self.tree_immich_people.insert("", "end", iid=pid, values=(name, pid))

        count = len(self.tree_immich_people.get_children())
        self.var_immich_people_count.set(f"Total found: {count} person(s)")

    def _on_immich_person_select(self, event):
        sel = self.tree_immich_people.selection()
        if sel:
            pid = sel[0]
            item_vals = self.tree_immich_people.item(pid)["values"]
            pname = item_vals[0] if item_vals else pid
            self._immich_selected_person_id = pid
            self._immich_selected_person_name = pname
            self.lbl_immich_person_header.config(text=f"Assets for Person: {pname}")
            self.btn_immich_person_assets.config(state="normal")

    def _on_immich_load_person_assets(self):
        pid = self._immich_selected_person_id
        if not pid:
            messagebox.showwarning("No Person Selected", "Please select a person from the list on the left.")
            return

        url = self.var_immich_url.get()
        key = self.var_immich_key.get()

        def _bg():
            ok, assets = immich_get_person_assets(url, key, pid)
            if ok and isinstance(assets, list):
                for item in self.tree_immich_person_assets.get_children():
                    self.tree_immich_person_assets.delete(item)
                for a in assets:
                    fn = a.get("originalFileName") or a.get("filename") or "Asset"
                    aid = a.get("id", "")
                    created = str(a.get("fileCreatedAt", ""))[:19].replace("T", " ")
                    orig_path = a.get("originalPath") or "N/A"
                    self.tree_immich_person_assets.insert("", "end", values=(fn, aid, created, orig_path))
                pname = self._immich_selected_person_name or "Person"
                self.var_immich_person_assets_count.set(f"Total found: {len(assets)} asset(s) for '{pname}'")
                self._update_status(f"Loaded {len(assets)} assets for person '{self._immich_selected_person_name}'.")
            else:
                self.var_immich_person_assets_count.set("Total found: 0 asset(s)")
                messagebox.showerror("Error", f"Failed to retrieve assets for person:\n{assets}")

        threading.Thread(target=_bg, daemon=True).start()

    def _on_immich_browse_local_path(self):
        d = filedialog.askdirectory(title="Select Local Target Folder for Immich Image Assets")
        if d:
            self.var_immich_local_path.set(d)
            self._save_immich_config()

    def _on_immich_open_person_in_mass_edit(self):
        local_root = self.var_immich_local_path.get().strip()
        if not local_root:
            d = filedialog.askdirectory(title="Select Local Target Folder for Immich Image Assets")
            if d:
                local_root = d
                self.var_immich_local_path.set(d)
                self._save_immich_config()
            else:
                return

        server_prefix = self.var_immich_server_prefix.get().strip()

        items = self.tree_immich_person_assets.get_children()
        if not items:
            messagebox.showwarning("No Person Assets Loaded", "Please select a person and click 'Fetch Person Assets' first.")
            return

        matched_local_paths: list[Path] = []
        missing_count = 0

        # Normalize prefix paths for Windows/POSIX compatibility
        s_pref_norm = server_prefix.replace("/", "\\").rstrip("\\").lower()
        l_root_norm = local_root.replace("/", "\\").rstrip("\\")

        for item in items:
            vals = self.tree_immich_person_assets.item(item)["values"]
            if len(vals) < 4:
                continue
            filename = str(vals[0])
            orig_path = str(vals[3])

            matched_path = None
            if orig_path and orig_path != "N/A":
                op_norm = orig_path.replace("/", "\\")
                op_norm_lower = op_norm.lower()

                # Strategy 1: Replace server_prefix with local_root
                if s_pref_norm and op_norm_lower.startswith(s_pref_norm):
                    rel = op_norm[len(s_pref_norm):].lstrip("\\")
                    cand = Path(l_root_norm) / rel
                    if cand.exists():
                        matched_path = cand

                # Strategy 2: Relative sub-folder match
                if not matched_path:
                    parts = [p for p in op_norm.split("\\") if p]
                    if len(parts) >= 2:
                        sub_rel = Path(parts[-2]) / parts[-1]
                        cand_sub = Path(l_root_norm) / sub_rel
                        if cand_sub.exists():
                            matched_path = cand_sub

                # Strategy 3: Direct filename match in local_root
                if not matched_path:
                    cand_direct = Path(l_root_norm) / filename
                    if cand_direct.exists():
                        matched_path = cand_direct

            if matched_path and matched_path.exists():
                matched_local_paths.append(matched_path)
            else:
                missing_count += 1

        if not matched_local_paths:
            msg = (
                f"Could not locate any matching local images under:\n{local_root}\n\n"
                f"Server path prefix:\n{server_prefix}\n\n"
                "Please check that your Target Folder and Server Prefix match your local file structure."
            )
            messagebox.showerror("Local Files Not Found", msg)
            return

        pname = self._immich_selected_person_name or "Person"
        if missing_count > 0:
            self._update_status(f"Found {len(matched_local_paths)} local file(s) for '{pname}' ({missing_count} missing on disk).")
        else:
            self._update_status(f"Matched all {len(matched_local_paths)} local image file(s) for '{pname}'!")

        self._open_in_mass_edit(matched_local_paths)

    def _open_in_mass_edit(self, image_paths: list[Path]):
        if not image_paths:
            return

        self._me_all_images = list(image_paths)
        self._me_active_images = list(image_paths)
        self._me_selected_indices.clear()
        self._me_last_clicked_index = None

        # Build folder list / options for Mass Edit folder dropdown
        self._me_folders = {}
        for p in image_paths:
            self._me_folders.setdefault(p.parent, []).append(p)
        self._me_folder_list = list(self._me_folders.keys())

        pname = getattr(self, "_immich_selected_person_name", None) or "Person"
        combo_options = [f"📁 All Matched Assets for '{pname}' ({len(image_paths)} images)"]
        for folder_path in self._me_folder_list:
            count = len(self._me_folders[folder_path])
            combo_options.append(f"📁 {folder_path.name} ({count} images)")

        if hasattr(self, "_combo_me_folders"):
            self._combo_me_folders["values"] = combo_options
            self._combo_me_folders.current(0)

        # Switch mode tab to Mass Edit
        self._current_mode = "mass_edit"
        self._update_mode_buttons()

        self._frame_dup_area.pack_forget()
        self._frame_fv_area.pack_forget()
        self._frame_immich_area.pack_forget()
        self._frame_me_area.pack(fill="both", expand=True, padx=20, pady=15)

        self._me_render_grid()

    def _fv_remove_path(self, path: Path):
        if path in self._fv_all_images:
            self._fv_all_images.remove(path)
        if path in self._fv_active_images:
            self._fv_active_images.remove(path)
        folder = path.parent
        if folder in self._fv_folders and path in self._fv_folders[folder]:
            self._fv_folders[folder].remove(path)
            if not self._fv_folders[folder]:
                del self._fv_folders[folder]

    def _on_key_press(self, event):
        """Handle keyboard shortcuts based on active mode."""
        keysym = event.keysym
        char = event.char.lower()

        # F5 — restart the process to pick up code changes
        if keysym == 'F5':
            os.execv(sys.executable, [sys.executable] + sys.argv)
            return

        # If user is currently typing in tag entry box or immich input box, don't trigger hotkeys!
        focus_w = self.focus_get()
        if focus_w in (
            getattr(self, "entry_fv_tag", None),
            getattr(self, "entry_me_tag", None),
            getattr(self, "entry_immich_url", None),
            getattr(self, "entry_immich_key", None),
        ):
            return

        if self._current_mode == "mass_edit":
            if char in ('t', 'm'):
                if hasattr(self, "entry_me_tag"):
                    self.entry_me_tag.focus_set()
                    self.entry_me_tag.selection_range(0, tk.END)
                return
            elif char in ('r', 'q', 'e'):
                self._me_rotate_selected()
            elif keysym in ('Delete', 'BackSpace') or char == 's':
                self._me_trash_selected()
            elif keysym == 'a' and (event.state & 0x0004):  # Ctrl+A
                self._me_select_all()
            return

        if self._current_mode == "folder_viewer":
            if char in ('t', 'm'):
                if hasattr(self, "entry_fv_tag"):
                    self.entry_fv_tag.focus_set()
                    self.entry_fv_tag.selection_range(0, tk.END)
                return
            elif keysym in ('Left', 'Prior') or char == 'a':
                self._fv_prev()
            elif keysym in ('Right', 'Next', 'space') or char in ('d', 'n'):
                self._fv_next()
            elif char in ('r', 'q', 'e'):
                self._fv_rotate()
            elif char == 'c':
                self._fv_chop()
            elif keysym in ('Delete', 'BackSpace') or char == 's':
                self._fv_trash()
            elif keysym == 'Home':
                self._fv_first()
            elif keysym == 'End':
                self._fv_last()
            return

        if not self._current_pair:
            return
        if char == 'w':
            self._act_keep_both()
        elif char == 'a':
            self._act_keep_left()
        elif char == 's':
            self._act_trash_both()
        elif char == 'd':
            self._act_keep_right()
        elif char == 'q':
            self.panel_left.rotate_image()
        elif char == 'e':
            self.panel_right.rotate_image()

    # ── Action button callbacks ─────────────────────────────────────────────
    def _act_keep_both(self):
        self._advance()

    def _act_keep_left(self):
        if not self._current_pair:
            self._advance()
            return
        right = self._current_pair[1]
        self._set_review_state(active=False)  # block double-clicks during flash
        self.panel_left.flash_green()
        self.update_idletasks()               # force repaint NOW before advancing
        send_to_trash(right)
        self._purge_deleted(right)
        self.after(FLASH_MS, self._advance)

    def _act_keep_right(self):
        if not self._current_pair:
            self._advance()
            return
        left = self._current_pair[0]
        self._set_review_state(active=False)
        self.panel_right.flash_green()
        self.update_idletasks()
        send_to_trash(left)
        self._purge_deleted(left)
        self.after(FLASH_MS, self._advance)

    def _act_trash_both(self):
        if self._current_pair:
            left, right = self._current_pair
            send_to_trash(left)
            send_to_trash(right)
            self._purge_deleted(left, right)
        self._advance()

    def _act_del_left(self):
        if not self._current_pair:
            return
        path = self._current_pair[0]
        if messagebox.askyesno(
            "Permanent Delete",
            f"Permanently delete (NO Recycle Bin):\n\n{path}\n\nThis cannot be undone!",
        ):
            delete_permanent(path)
            self._purge_deleted(path)
            self._advance()

    def _act_del_right(self):
        if not self._current_pair:
            return
        path = self._current_pair[1]
        if messagebox.askyesno(
            "Permanent Delete",
            f"Permanently delete (NO Recycle Bin):\n\n{path}\n\nThis cannot be undone!",
        ):
            delete_permanent(path)
            self._purge_deleted(path)
            self._advance()

    def _advance(self):
        self._current_pair = None
        self._load_next_pair()

    # ── UI helpers ──────────────────────────────────────────────────────────
    def _set_review_state(self, active: bool):
        state = "normal" if active else "disabled"
        for btn in self._action_buttons:
            btn.config(state=state)

    def _update_status(self, msg: str):
        self.lbl_status.config(text=msg)

    def _similarity_label(self, a: Path, b: Path) -> str:
        """Return a human-readable similarity string for the two image paths."""
        try:
            import imagehash
            with Image.open(a) as ia, Image.open(b) as ib:
                ha = imagehash.phash(ia.convert("RGB"))
                hb = imagehash.phash(ib.convert("RGB"))
            dist = ha - hb
            # Max possible distance for pHash 8×8 = 64 bits
            pct = max(0, 100 - int(dist / 64 * 100))
            if dist == 0:
                label = "Exact perceptual match (100%)"
            elif dist <= 5:
                label = f"Nearly identical  ({pct}% similar)"
            elif dist <= 10:
                label = f"Very similar  ({pct}% similar)"
            else:
                label = f"Similar  ({pct}% similar, dist={dist})"
            return f"🔍 Similarity\n{label}"
        except Exception:
            return "🔍 Similarity\n(unavailable)"


# ─────────────────────────────────────────────────────────────────────────────
# Colour utility
# ─────────────────────────────────────────────────────────────────────────────
def _lighten(hex_color: str, amount: int = 20) -> str:
    """Return a slightly lighter version of a hex colour string."""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) != 6:
        return "#" + hex_color
    r, g, b = (int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    r = min(255, r + amount)
    g = min(255, g + amount)
    b = min(255, b + amount)
    return f"#{r:02x}{g:02x}{b:02x}"


def _darken(hex_color: str, amount: int = 40) -> str:
    """Return a darker version of a hex colour string (used for disabled state)."""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) != 6:
        return "#" + hex_color
    r, g, b = (int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    r = max(0, r - amount)
    g = max(0, g - amount)
    b = max(0, b - amount)
    return f"#{r:02x}{g:02x}{b:02x}"


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = DuplicateDetectiveApp()

    # Centre on screen
    app.update_idletasks()
    sw = app.winfo_screenwidth()
    sh = app.winfo_screenheight()
    w = int(sw * 0.85)
    h = int(sh * 0.85)
    x = (sw - w) // 2
    y = (sh - h) // 2
    app.geometry(f"{w}x{h}+{x}+{y}")
    
    app.state("zoomed")

    app.mainloop()
