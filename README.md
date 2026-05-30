# PDF Image Remover

A small Windows desktop tool that removes images from PDF files while keeping all
text and the exact page layout. Built so the cleaned PDFs upload to Claude AI
without hitting the image limit — ideal for reviewing the text of IEEE (or any)
papers. Keep your originals and share the cleaned copy; share the original later
if the figures matter.

## Two removal modes

You pick the mode in the window:

1. **Images only (default, recommended).**
   Removes embedded **raster** images (photographs, scanned figures, logos).
   Keeps vector graphics (line plots/charts, diagrams), tables, equations and the
   exact text layout. This already clears Claude's image limit, because Claude
   does **not** count vector graphics as images.

2. **Images + figures/charts (text-only).**
   Also removes **vector** graphics — plots, diagrams, and vector-drawn tables —
   leaving a clean text-only PDF. Figure/table **captions** (which are real text)
   are kept.
   Note: in many IEEE papers both the plots *and* the numeric table grids are
   drawn as vector graphics, so this mode removes both. Pick this only when you
   want the figures physically gone.

Both modes keep text byte-identical and in the same positions, and the output
contains zero raster images.

## Why a figure can "survive" images-only mode

Most charts in IEEE papers (e.g. MATLAB RMSE/CDF plots) are drawn as vector
line-art, not as embedded pictures. Images-only mode deliberately keeps vector
line-art so tables, rules and equation layout are not damaged — so those plots
stay. They do not count against Claude's image limit. If you want them gone too,
use the text-only mode.

## Files in this package

| File | Purpose |
|------|---------|
| `pdf_image_remover.py` | The tool (UI + removal logic). |
| `requirements.txt` | The one dependency (PyMuPDF). |
| `install_dependencies.bat` | Installs Python dependencies. Run once first. |
| `run.bat` | Runs the tool with Python. |
| `build_exe.bat` | Builds a standalone `.exe` (no Python needed to run it). |

## Quick start (run with Python)

1. Install **Python 3.8+** from <https://www.python.org/downloads/> and tick
   **"Add Python to PATH"** during setup.
2. Double-click **`install_dependencies.bat`** (one time).
3. Double-click **`run.bat`** to open the tool.

In the window:
1. Click **Add PDF File(s)…** or **Add Folder…**.
2. Pick the **removal mode** (Images only / Images + figures).
3. Click **Browse…** to choose an output folder.
4. Click **Remove Images**.

The **"Append \_noimg"** option (on by default) names outputs like
`paper_noimg.pdf` so your originals are never overwritten.

## Build a standalone EXE (optional)

Double-click **`build_exe.bat`**. When it finishes, your program is at:

```
dist\PDFImageRemover.exe
```

Copy that `.exe` to any Windows PC and run it — no Python required.

## How it works (technical)

For each page the tool adds one whole-page redaction box that paints nothing,
then applies it with image removal switched on (and, in text-only mode, vector
line-art removal too); text removal stays off. The whole-page box also clears
images nested inside Form XObjects — a case a per-image search can miss. Saving
with `garbage=4, clean=True` physically discards the orphaned image objects, so
the file ends up with no `/Image` objects, which is why no PDF reader, and no
AI, detects an image.

Tested on a real IEEE Transactions PDF (17 pages, 14 raster images, ~6000 vector
paths): images-only mode left 0 raster images with all vectors and text intact;
text-only mode additionally removed the vector graphics. In both cases the
extracted text and every text position were unchanged.
