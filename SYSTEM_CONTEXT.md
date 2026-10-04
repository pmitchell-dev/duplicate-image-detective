# 🎨 PicCurator Studio — System Context
**Last Updated:** 2026-09-09
**Type:** Python Desktop App (Windows)

---

## Purpose
Recursively scans image directories for visually duplicate photos using perceptual hashing (pHash), provides a sequential Folder Image Viewer for reviewing images folder-by-folder, features a **Mass Edit** grid view mode with Shift/Ctrl multi-selection, and includes an **Immich Server Integration** mode with Address & API Key connection testing.

---

## Tech Stack
- **Language:** Python 3.10+
- **UI:** Tkinter (Python built-in)
- **Hashing:** `imagehash` (pHash, 6-bit distance threshold)
- **Image & Metadata Processing:** Pillow (EXIF + XMP RDF metadata payload engine)
- **Recycle Bin:** `send2trash`
- **Packaging:** PyInstaller → `PicCurator Studio v5.exe`

---

## Key Files
| File | Purpose |
|---|---|
| `main.py` | Tkinter GUI — quad mode (Duplicate Scanner, Image Viewer, Mass Edit, Immich Integration) |
| `scanner.py` | Threaded scanner, folder image collector, EXIF (`XPKeywords` `0x9C9E`) & Immich XMP tag read/write engine |
| `requirements.txt` | Python dependencies |
| `picCurator Studio.spec` | PyInstaller build specification (outputs `PicCurator Studio v5.exe`) |
| `test_scanner.py` | Unit tests for scanner, folder collection, and tag payload read/write |

---

## Keyboard Shortcuts

### Duplicate Scanner Mode (WASDQE)
| Key | Action |
|---|---|
| W | Keep both — skip to next pair |
| A | Keep image 1 — trash image 2 |
| D | Keep image 2 — trash image 1 |
| S | Trash both |
| Q | Rotate image 1 90° clockwise |
| E | Rotate image 2 90° clockwise |

### Image Viewer Mode
| Key | Action |
|---|---|
| Right / D / N / Space | Next image |
| Left / A | Previous image |
| R / Q / E | Rotate image 90° clockwise |
| Delete / BackSpace / S | Send current image to Recycle Bin (with confirmation) |
| T / M | Focus Tag / Keyword entry box |
| Home / End | Jump to First / Last image |

### Mass Edit Mode
| Key | Action |
|---|---|
| Shift + Click | Select contiguous range of images |
| Ctrl + Click | Toggle selection of image |
| Ctrl + A | Select all images |
| R / Q / E | Rotate all highlighted images 90° clockwise |
| Delete / BackSpace / S | Trash all highlighted images (with confirmation) |
| T / M | Focus Mass Tag entry box |

---

## Features
- **Duplicate Scanner:** Every image hashed with pHash; pairs with distance ≤ 6 bits flagged.
- **Image Viewer:** Browse images folder-by-folder with single-image sidebar controls and bottom-anchored delete button.
- **Mass Edit Mode:** 5-column scrollable grid view with Shift & Ctrl multi-selection, set-intersection tag display, mass tagging, and mass rotation.
- **Immich Mode:** Swaps top bar directory controls for Server Address & API Key input fields with live connection testing (`⚡ Test Communication`).

---

## Build
```bash
pyinstaller "picCurator Studio.spec" --clean --noconfirm
# Output: dist/PicCurator Studio v5.exe
```
