# picCurator Studio 🔍

> **✨ Vibe coded** — This project was built entirely through conversational AI-assisted development (vibe coding) using [Antigravity by Google DeepMind](https://deepmind.google). No manual code was written.

A desktop application for Windows that recursively scans a directory for visually duplicate images and lets you decide what to do with each pair — keep, trash, or permanently delete.

---

## Screenshot

![picCurator Studio](screenshots/screenshot.png)

---

## Features

- **Recursive directory scan** — finds duplicates in all subdirectories.
- **Perceptual hashing (pHash)** — detects visually identical images even if they differ in compression, quality, or resolution.
- **Threaded scanner** — UI stays responsive while scanning; review pairs as they're found.
- **Image Viewer** — seamless viewer for navigating images with half-transparent overlay arrows.
- **Mass Edit Mode** — bulk manage tags, navigate through active selections, and easily double-click any image to jump straight to it in Image Viewer.
- **Immich Integration** — query people directly from your Immich server and review their matched local files in Mass Edit mode.
- **Nord-inspired UI** — A professional, comfortable dark theme that's easy on the eyes.
- **"Loosened" Layout** — A modern, breathable design with ample padding for better focus.
- **Scroll-wheel zoom** — hover over either image and scroll to zoom in/out, anchored to the cursor position (up to 12×).
- **Side-by-side preview** — see both images simultaneously with full file path and match counts.
- **Similarity score** — shows how visually similar the pair is (e.g. "Nearly identical — 98%").

---

## Keyboard Shortcuts (WASDQE)

For a lightning-fast workflow, use the following hotkeys during review:

- **W**: Keep Both Images — move to the next pair without changes.
- **A**: Keep Image 1 — move Image 2 to the Recycle Bin.
- **D**: Keep Image 2 — move Image 1 to the Recycle Bin.
- **S**: Trash Both Images — move both to the Recycle Bin.
- **Q**: Rotate Image 1 (Left) 90° clockwise.
- **E**: Rotate Image 2 (Right) 90° clockwise.
- **R**: Rotate current image in Image Viewer 90° clockwise.

---

## Requirements

- **Python 3.10+**
- **Windows** (Recycle Bin integration via `send2trash`)

### Python dependencies

```
Pillow>=10.0.0
imagehash>=4.3.1
send2trash>=1.8.2
requests>=2.31.0
```

---

## Installation

```powershell
git clone https://github.com/legendary034/duplicate-image-detective.git
cd duplicate-image-detective
pip install -r requirements.txt
```

---

## Usage

```powershell
python main.py
```

1. Click **Browse…** and select the root directory to scan.
2. Choose your mode: **Duplicate Scanner**, **Image Viewer**, **Mass Edit**, or **Immich Integration**.
3. For duplicates, click **▶ Start Scan** — the scanner runs in the background. Duplicate pairs appear one at a time for review.
4. Use the **WASDQE** hotkeys or the action buttons to manage the images.
5. In **Mass Edit**, use shift/ctrl clicks to select multiple items, or double click to open seamlessly in Image Viewer.

### Standalone Executable
You can also run the pre-built `PicCurator Studio v6.exe` located in the `dist/` folder for a zero-install experience.

---

## Files

| File | Purpose |
|---|---|
| `main.py` | Tkinter GUI — quad mode (Duplicate Scanner, Image Viewer, Mass Edit, Immich Integration) |
| `scanner.py` | Background duplicate scanner (pHash + threading) |
| `requirements.txt` | Python dependencies |

---

## How Duplicate Detection Works

1. Every image file is hashed using **perceptual hash (pHash)** from the `imagehash` library.
2. Any two images with a hash **distance ≤ 6 bits** are flagged as duplicates.
3. This threshold catches re-saved, re-compressed, or slightly edited copies of the same image while avoiding false positives.

---

## Supported Image Formats


---

## License

MIT
