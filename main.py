"""
main.py — Duplicate Image Detective
A Tkinter application for finding and managing near-duplicate images.
"""
from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from scanner import SCAN_DONE, DuplicateScanner, ScanStats

# ─────────────────────────────────────────────────────────────────────────────
# Constants / palette
# ─────────────────────────────────────────────────────────────────────────────
BG_DARK      = "#1a1a2e"
BG_PANEL     = "#16213e"
BG_CARD      = "#0f3460"
ACCENT_BLUE  = "#4361ee"
ACCENT_GREEN = "#4cc9f0"
ACCENT_RED   = "#f72585"
ACCENT_AMBER = "#f4a261"
TEXT_MAIN    = "#e0e0e0"
TEXT_DIM     = "#8888aa"
FONT_FAMILY  = "Segoe UI"

# Action button colours
COLOR_KEEP       = "#1a8c3f"   # deep green    — "keep" half
COLOR_TRASH      = "#c96a10"   # deep amber    — "trash to Recycle Bin" half
COLOR_BOTH_KEEP  = "#145c2a"   # darker green  — Keep Both
COLOR_BOTH_TRASH = "#7a3200"   # darker amber  — Trash Both
COLOR_PERM_DEL   = "#9b1030"   # deep crimson  — permanent delete

HASH_THRESHOLD  = 6           # ≤6 bits difference → duplicate
POLL_MS         = 200         # UI queue-poll interval (ms)
PREVIEW_SIZE    = (460, 520)  # max canvas size (px)


# ─────────────────────────────────────────────────────────────────────────────
# Helper: safely send file to Recycle Bin
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


# ─────────────────────────────────────────────────────────────────────────────
# Image panel helper
# ─────────────────────────────────────────────────────────────────────────────
class ImagePanel(tk.Frame):
    """A framed canvas that displays a scaled image with scroll-wheel zoom."""

    ZOOM_STEP = 1.15   # multiply zoom by this per scroll tick
    ZOOM_MIN  = 0.05   # never zoom out further than 5 % of original
    ZOOM_MAX  = 12.0   # cap at 12×

    def __init__(self, master, label_text: str, **kwargs):
        super().__init__(master, bg=BG_PANEL, **kwargs)
        self._photo   = None   # ImageTk reference (prevent GC)
        self._orig    = None   # original PIL.Image (full resolution)
        self._zoom    = 1.0    # current zoom factor
        self._pan_x   = 0.0   # image-origin x in canvas pixels
        self._pan_y   = 0.0   # image-origin y in canvas pixels

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
            width=PREVIEW_SIZE[0],
            height=PREVIEW_SIZE[1],
            bg=BG_CARD,
            highlightthickness=2,
            highlightbackground=ACCENT_BLUE,
        )
        self.canvas.pack(padx=10, pady=4)

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
            wraplength=PREVIEW_SIZE[0],
        )
        self.lbl_filename.pack(pady=(2, 0))

        # Full path label
        self.lbl_path = tk.Label(
            self,
            text="",
            font=(FONT_FAMILY, 8),
            bg=BG_PANEL,
            fg=TEXT_DIM,
            wraplength=PREVIEW_SIZE[0],
        )
        self.lbl_path.pack(pady=(0, 6))

    # ── Public API ────────────────────────────────────────────────────────

    def load_image(self, path: Path):
        """Load *path* and display it at fit-zoom; enables scroll-wheel zoom."""
        try:
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
                PREVIEW_SIZE[0] // 2, PREVIEW_SIZE[1] // 2,
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
        self.lbl_filename.config(text="—")
        self.lbl_path.config(text="")

    def show_placeholder(self, text: str):
        """Show a centred text message; clears any loaded image."""
        self._orig = None
        self.canvas.delete("all")
        self._photo = None
        self.canvas.create_text(
            PREVIEW_SIZE[0] // 2, PREVIEW_SIZE[1] // 2,
            text=text,
            fill=TEXT_DIM,
            font=(FONT_FAMILY, 12),
            justify="center",
            width=PREVIEW_SIZE[0] - 20,
        )
        self.lbl_filename.config(text="—")
        self.lbl_path.config(text="")

    # ── Zoom / render internals ───────────────────────────────────────────

    def _calc_fit_zoom(self) -> float:
        """Zoom level that makes the image fill the canvas without distortion."""
        if self._orig is None:
            return 1.0
        iw, ih = self._orig.size
        cw, ch = PREVIEW_SIZE
        return min(cw / iw, ch / ih)

    def _calc_centered_pan(self) -> tuple[float, float]:
        """Pan offset that centres the image at the current zoom."""
        if self._orig is None:
            return 0.0, 0.0
        iw, ih = self._orig.size
        cw, ch = PREVIEW_SIZE
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
        cw, ch  = PREVIEW_SIZE
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
        cw, ch = PREVIEW_SIZE
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
class DuplicateDetectiveApp(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title("Duplicate Image Detective")
        self.configure(bg=BG_DARK)
        self.minsize(1200, 720)
        self.resizable(True, True)

        # Internal state
        self._scan_queue: queue.Queue = queue.Queue()
        self._stats = ScanStats()
        self._scanner: DuplicateScanner | None = None
        self._pending_pairs: list[tuple[Path, Path]] = []
        self._current_pair: tuple[Path, Path] | None = None
        self._scan_running = False
        self._scan_done = False
        self._pair_index = 0  # displayed pair counter

        self._build_ui()
        self._set_review_state(active=False)

    # ── UI construction ────────────────────────────────────────────────────
    def _build_ui(self):
        self._build_topbar()
        self._build_main_area()
        self._build_statusbar()

    def _build_topbar(self):
        bar = tk.Frame(self, bg=BG_PANEL, pady=8)
        bar.pack(fill="x", side="top")

        tk.Label(
            bar,
            text="📁  Directory:",
            font=(FONT_FAMILY, 10, "bold"),
            bg=BG_PANEL,
            fg=ACCENT_GREEN,
        ).pack(side="left", padx=(16, 4))

        self.var_dir = tk.StringVar(value="No directory selected")
        tk.Label(
            bar,
            textvariable=self.var_dir,
            font=(FONT_FAMILY, 10),
            bg=BG_PANEL,
            fg=TEXT_MAIN,
            anchor="w",
        ).pack(side="left", fill="x", expand=True)

        self._btn_browse = self._make_button(
            bar, "Browse…", self._on_browse,
            fg=BG_DARK, bg=ACCENT_GREEN,
        )
        self._btn_browse.pack(side="right", padx=6)

        self._btn_scan = self._make_button(
            bar, "▶  Start Scan", self._on_start_scan,
            fg=BG_DARK, bg=ACCENT_BLUE,
        )
        self._btn_scan.pack(side="right", padx=(0, 6))
        self._btn_scan.config(state="disabled")

    def _build_main_area(self):
        area = tk.Frame(self, bg=BG_DARK)
        area.pack(fill="both", expand=True, padx=10, pady=8)
        area.columnconfigure(0, weight=3)
        area.columnconfigure(1, weight=2)
        area.columnconfigure(2, weight=3)
        area.rowconfigure(0, weight=1)

        self.panel_left  = ImagePanel(area, "◀  Image 1")
        self.panel_left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))

        self._build_action_panel(area)

        self.panel_right = ImagePanel(area, "Image 2  ▶")
        self.panel_right.grid(row=0, column=2, sticky="nsew", padx=(6, 0))

    def _build_action_panel(self, parent):
        frame = tk.Frame(parent, bg=BG_PANEL, padx=12, pady=12)
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
        self.lbl_pair_counter.pack(pady=(0, 6))

        # Column orientation labels so the user can map buttons to panels
        hdr = tk.Frame(frame, bg=BG_PANEL)
        hdr.pack(fill="x", padx=2, pady=(0, 2))
        tk.Label(hdr, text="◄ Image 1", font=(FONT_FAMILY, 8, "bold"),
                 bg=BG_PANEL, fg=TEXT_DIM).pack(side="left")
        tk.Label(hdr, text="Image 2 ►", font=(FONT_FAMILY, 8, "bold"),
                 bg=BG_PANEL, fg=TEXT_DIM).pack(side="right")

        self._action_buttons: list[tk.Button] = []
        self._split_actions: list = []   # (enabled_dict, container, l_lbl, l_bg, r_lbl, r_bg)

        # ── Keep Both — full-width green ─────────────────────
        btn_kb = self._make_button(
            frame, "✅  Keep Both", self._act_keep_both,
            fg="#ffffff", bg=COLOR_BOTH_KEEP,
        )
        btn_kb.pack(fill="x", pady=(0, 3))
        self._action_buttons.append(btn_kb)

        # ── Keep Left | Trash Right ─────────────────────
        self._make_split_action(
            frame,
            left_text="✅ Keep\n◄ Image 1",  left_bg=COLOR_KEEP,
            right_text="🗑 Trash\nImage 2 ►", right_bg=COLOR_TRASH,
            command=self._act_keep_left,
        ).pack(fill="x", pady=3)

        # ── Trash Left | Keep Right ─────────────────────
        self._make_split_action(
            frame,
            left_text="🗑 Trash\n◄ Image 1",  left_bg=COLOR_TRASH,
            right_text="✅ Keep\nImage 2 ►", right_bg=COLOR_KEEP,
            command=self._act_keep_right,
        ).pack(fill="x", pady=3)

        # ── Trash Both — full-width amber ──────────────────
        btn_tb = self._make_button(
            frame, "🗑  Trash Both", self._act_trash_both,
            fg="#ffffff", bg=COLOR_BOTH_TRASH,
        )
        btn_tb.pack(fill="x", pady=(3, 0))
        self._action_buttons.append(btn_tb)

        # ── Separator ────────────────────────────────────
        tk.Frame(frame, bg=TEXT_DIM, height=1).pack(fill="x", pady=10)

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
        btn_dl.pack(side="left", fill="both", expand=True, padx=(0, 2))
        self._action_buttons.append(btn_dl)

        btn_dr = self._make_button(
            del_row, "☠  Delete\nImage 2 ►", self._act_del_right,
            fg="#ffffff", bg=COLOR_PERM_DEL,
        )
        btn_dr.pack(side="right", fill="both", expand=True, padx=(2, 0))
        self._action_buttons.append(btn_dr)

        # ── Similarity badge ─────────────────────────────────
        tk.Frame(frame, bg=TEXT_DIM, height=1).pack(fill="x", pady=12)
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

    def _make_split_action(
        self, parent,
        left_text: str, left_bg: str,
        right_text: str, right_bg: str,
        command,
    ) -> tk.Frame:
        """
        Build a two-tone split row that acts as a SINGLE button.
        Left and right halves are tk.Label widgets inside a tk.Frame;
        all three widgets are bound to the same *command* so the entire
        row is one click target.  state dict lets _set_review_state
        enable/disable it without touching tk.Button.state.
        """
        enabled = {"on": True}   # mutable flag shared by all closures

        container = tk.Frame(parent, bg=BG_PANEL, cursor="hand2")

        left_lbl = tk.Label(
            container, text=left_text, bg=left_bg, fg="#ffffff",
            font=(FONT_FAMILY, 9, "bold"), padx=8, pady=9,
            justify="center", cursor="hand2",
        )
        left_lbl.pack(side="left", fill="both", expand=True, padx=(0, 1))

        right_lbl = tk.Label(
            container, text=right_text, bg=right_bg, fg="#ffffff",
            font=(FONT_FAMILY, 9, "bold"), padx=8, pady=9,
            justify="center", cursor="hand2",
        )
        right_lbl.pack(side="right", fill="both", expand=True, padx=(1, 0))

        def _click(e):
            if enabled["on"]:
                command()

        def _enter(e):
            if enabled["on"]:
                left_lbl.config(bg=_lighten(left_bg, 25))
                right_lbl.config(bg=_lighten(right_bg, 25))

        def _leave(e):
            left_lbl.config(bg=left_bg if enabled["on"] else _darken(left_bg))
            right_lbl.config(bg=right_bg if enabled["on"] else _darken(right_bg))

        for w in (container, left_lbl, right_lbl):
            w.bind("<Button-1>", _click)
            w.bind("<Enter>",   _enter)
            w.bind("<Leave>",   _leave)

        # Register for enable/disable in _set_review_state
        self._split_actions.append(
            (enabled, container, left_lbl, left_bg, right_lbl, right_bg)
        )
        return container


    def _build_statusbar(self):
        bar = tk.Frame(self, bg=BG_PANEL, pady=4)
        bar.pack(fill="x", side="bottom")

        self.lbl_status = tk.Label(
            bar,
            text="Ready — choose a directory and start a scan.",
            font=(FONT_FAMILY, 9),
            bg=BG_PANEL,
            fg=TEXT_DIM,
            anchor="w",
        )
        self.lbl_status.pack(side="left", padx=12)

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

        # Style the progressbar
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

    # ── Button factory ──────────────────────────────────────────────────────
    @staticmethod
    def _make_button(parent, text, command, fg=TEXT_MAIN, bg=BG_CARD, width=None):
        kw = dict(font=(FONT_FAMILY, 9, "bold"), relief="flat", cursor="hand2",
                  activebackground=BG_DARK, fg=fg, bg=bg,
                  padx=10, pady=7, command=command)
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
            self._update_status("Directory selected. Click 'Start Scan' to begin.")

    def _on_start_scan(self):
        if self._scan_running:
            return
        root_dir = self.var_dir.get()
        if not root_dir or not os.path.isdir(root_dir):
            messagebox.showwarning("No Directory", "Please select a valid directory first.")
            return

        # Reset state
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

    # ── Action button callbacks ─────────────────────────────────────────────
    def _act_keep_both(self):
        self._advance()

    def _act_keep_left(self):
        if self._current_pair:
            right = self._current_pair[1]
            send_to_trash(right)
            self._purge_deleted(right)
        self._advance()

    def _act_keep_right(self):
        if self._current_pair:
            left = self._current_pair[0]
            send_to_trash(left)
            self._purge_deleted(left)
        self._advance()

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
        for enabled, container, l_lbl, l_bg, r_lbl, r_bg in self._split_actions:
            enabled["on"] = active
            cursor = "hand2" if active else "arrow"
            l_lbl.config(bg=l_bg if active else _darken(l_bg), cursor=cursor)
            r_lbl.config(bg=r_bg if active else _darken(r_bg), cursor=cursor)
            container.config(cursor=cursor)

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
    w, h = 1300, 780
    sw = app.winfo_screenwidth()
    sh = app.winfo_screenheight()
    x = (sw - w) // 2
    y = (sh - h) // 2
    app.geometry(f"{w}x{h}+{x}+{y}")

    app.mainloop()
