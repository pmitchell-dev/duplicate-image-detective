# Duplicate Image Detective 🔍

> **✨ Vibe coded** — This project was built entirely through conversational AI-assisted development (vibe coding) using [Antigravity by Google DeepMind](https://deepmind.google). No manual code was written.

A desktop application for Windows that recursively scans a directory for visually duplicate images and lets you decide what to do with each pair — keep, trash, or permanently delete.

---

## Screenshot

```
┌─────────────────────────────────────────────────────────────┐
│ 📁 Directory: C:\Users\...\Pictures          [Browse] [Scan]│
├───────────────────┬─────────────────┬───────────────────────┤
│                   │    Actions      │                       │
│   ◀ Image 1       │  ✅ Keep Both   │       Image 2 ▶       │
│                   │ [✅Keep|🗑Trash] │                       │
│  [image preview]  │ [🗑Trash|✅Keep] │   [image preview]     │
│                   │  🗑 Trash Both  │                       │
│  filename.jpg     │ ─────────────  │  filename_copy.jpg    │
│  C:\path\to\file  │ ☠ Delete Img1  │  C:\path\to\copy      │
│                   │ ☠ Delete Img2  │                       │
└───────────────────┴─────────────────┴───────────────────────┘
```

---

## Features

- **Recursive directory scan** — finds duplicates in all subdirectories
- **Perceptual hashing (pHash)** — detects visually identical images even if they differ in compression, quality, or metadata
- **Threaded scanner** — UI stays responsive while scanning; review pairs as they're found
- **Scroll-wheel zoom** — hover over either image and scroll to zoom in/out, anchored to the cursor position (up to 12×)
- **Side-by-side preview** — see both images simultaneously with full file path displayed
- **Similarity score** — shows how visually similar the pair is (e.g. "Nearly identical — 98%")
- **Six action buttons**:
  - ✅ **Keep Both** — skip this pair, no changes
  - **Keep ◀ / Trash ▶** — send Image 2 to the Recycle Bin, keep Image 1
  - **Trash ◀ / Keep ▶** — send Image 1 to the Recycle Bin, keep Image 2
  - 🗑 **Trash Both** — send both to the Recycle Bin
  - ☠ **Delete Image 1 (Permanent)** — bypass Recycle Bin (confirmation required)
  - ☠ **Delete Image 2 (Permanent)** — bypass Recycle Bin (confirmation required)
- **Safe by default** — trash actions use the Windows Recycle Bin; permanent delete requires a confirmation dialog
- **Smart queue management** — if a file appears in multiple duplicate pairs and gets trashed, it's automatically removed from all remaining pairs in the queue

---

## Requirements

- **Python 3.10+**
- **Windows** (Recycle Bin integration via `send2trash`)

### Python dependencies

```
Pillow>=10.0.0
imagehash>=4.3.1
send2trash>=1.8.2
```

---

## Installation

```powershell
git clone https://github.com/YOUR_USERNAME/duplicate-image-detective.git
cd duplicate-image-detective
pip install -r requirements.txt
```

---

## Usage

```powershell
python main.py
```

1. Click **Browse…** and select the root directory to scan
2. Click **▶ Start Scan** — the scanner runs in the background
3. Duplicate pairs appear one at a time for review
4. Click an action button for each pair
5. When finished, the app shows a completion message

---

## Files

| File | Purpose |
|---|---|
| `main.py` | Tkinter GUI application — run this |
| `scanner.py` | Background duplicate scanner (pHash + threading) |
| `requirements.txt` | Python dependencies |

---

## How Duplicate Detection Works

1. Every image file is hashed using **perceptual hash (pHash)** from the `imagehash` library — this converts each image to a compact 64-bit fingerprint based on its visual frequency content
2. Any two images with a hash **distance ≤ 6 bits** are flagged as duplicates
3. This threshold catches re-saved, re-compressed, or slightly edited copies of the same image while avoiding false positives on genuinely different photos

---

## Supported Image Formats

`.jpg` `.jpeg` `.png` `.gif` `.bmp` `.webp` `.tiff` `.tif`

---

## License

MIT
