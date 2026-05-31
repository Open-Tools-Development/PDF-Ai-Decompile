# PDF Image Remover

A small, cross-platform desktop tool for working with PDF papers. It can:

* **Remove images** from a PDF while keeping all text and the exact layout,
* **Convert a PDF to LaTeX** — one compilable IEEE `.tex` file per PDF, plus a
  shared `Latex_Resource` folder of extracted figures, or
* **Convert a PDF to Markdown** — full text, no images.

The LaTeX and Markdown outputs are designed so that **any AI tool can read the
full paper without having to process the PDF**, and so the cleaned PDFs upload
without hitting image limits.

Built with [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter).
Author: **Jerry James**. Licensed under **GPL-3.0**.

---

## Project layout

```
<project root>/
├─ Scripts/            All source code, scripts and assets (this folder)
│   ├─ pdf_image_remover.py   Main app (GUI)
│   ├─ pdf_remove.py          Image-removal engine
│   ├─ pdf_to_latex.py        PDF → LaTeX renderer
│   ├─ pdf_to_markdown.py     PDF → Markdown renderer
│   ├─ pdf_common.py          Shared PDF parsing engine
│   ├─ pdf_math.py            Inline-math reconstruction (subscripts, symbols)
│   ├─ pdf_equations.py       Display-equation detection + image extraction
│   ├─ about_info.py          Tool metadata / features / how-to
│   ├─ build_info.py          Build date (auto-generated; reset by clean.bat)
│   ├─ make_assets.py         Regenerates icon.ico + splash.png
│   ├─ icon.ico, splash.png, icon_preview.png
│   ├─ requirements.txt
│   ├─ install_dependencies.bat
│   ├─ run.bat
│   ├─ build_exe.bat
│   ├─ clean.bat
│   ├─ LICENSE
│   └─ README.md
└─ Published_Tool/     The finished EXE is placed here by build_exe.bat
```

## Quick start (run from source)

1. Install **Python 3.8+** (tick *Add Python to PATH* during setup on Windows).
2. From the `Scripts` folder, run **`install_dependencies.bat`** once.
3. Run **`run.bat`** to open the tool.

On macOS/Linux, the equivalents are:

```bash
pip install -r requirements.txt
python3 pdf_image_remover.py
```

## Using the tool

1. **Add PDFs** — *Add PDF File(s)…* or *Add Folder…* (optionally *Subfolders*).
2. **Choose an Operation** (required, nothing is selected by default):
   * **Remove images from PDF**
     * *Images only* — removes raster photos/figures, keeps charts, tables,
       equations and layout. (Clears AI image-upload limits.)
     * *Images + figures/charts* — also removes vector plots/diagrams for a
       clean text-only PDF.
   * **Convert PDF → LaTeX**
   * **Convert PDF → Markdown (full text)**
3. **Set the options** for that operation, including where to save the output:
   *Beside each PDF* or *In one chosen output folder*.
4. Click **Start**. If no operation is selected, the tool shows an error and
   does not run.

For LaTeX output, upload the generated `.tex` **and** its `Latex_Resource`
folder to Overleaf, or compile locally with `pdflatex` (two passes).

## Build a standalone EXE (Windows)

From the `Scripts` folder, run **`build_exe.bat`**. It installs PyInstaller if
needed, stamps the build date into `build_info.py`, bundles the icon and splash,
and writes the finished program to:

```
..\Published_Tool\PDFImageRemover.exe
```

A native splash (with the tool name, author and license) shows while the EXE
unpacks. Copy the EXE to any Windows PC — no Python required.

## Clean before committing

Run **`clean.bat`** to delete PyInstaller's `build/`, any `dist/`, `*.spec`,
`__pycache__/` and `*.pyc`, and to reset `build_info.py` to the development
placeholder. Your source files and the EXE in `Published_Tool` are left
untouched.

## Equation handling (PDF → LaTeX)

PDF text extraction cannot fully recover complex LaTeX math (multi-line aligned
equations, matrices, integrals). The LaTeX converter therefore offers four
equation modes, selectable in the UI (default: **Rebuild as LaTeX math text**):

| Mode | What it does | Trade-off |
|------|--------------|-----------|
| Rebuild as LaTeX math text | Equations become editable LaTeX with recovered sub/superscripts and symbols. | Compiles and is editable, but complex math is approximate and may need a manual check. |
| Improve inline math only | Recovers inline symbols/subscripts; leaves display equations as plain text. | Lightest touch; display equations stay rough. |
| Hybrid (text + equation images) | Inline math as text, plus an exact image for each display equation. | Editable prose with correct-looking equations; equations are images. |
| Equation images (exact) | Every display equation is inserted as an exact cropped image. | Looks perfect; equations are not editable text. |

For an equation-heavy paper, **Hybrid** or **Equation images** gives the most
faithful result; **Rebuild as LaTeX text** is best when you intend to edit the
equations afterwards.

## Image file naming

Extracted images are named with a short, configurable prefix taken from the PDF
file name, a unique number (so several PDFs can share one `Latex_Resource`
folder without clashing), and the figure/equation number, e.g.:

```
RISAidedM_3_Fig-2.png      RISAidedM_11_Eq-5.png      RISAidedM_1_Img-1.png
```

The prefix length is set in the UI (default **9** letters; set **0** to use the
full PDF name).

## What the conversion does and doesn't do

* It recovers the **text and structure** of the PDF (title, authors, abstract,
  index terms, all sections/subsections/sub-subsections, figure & table
  captions, references with `\cite{}` and an embedded bibliography, and author
  biographies). It is **not** a pixel-perfect reproduction of the PDF.
* **Equations** are extracted as approximate plain text (PDF text extraction
  cannot recover LaTeX math), and may need manual review. Common Unicode math
  symbols are mapped to LaTeX so the file still compiles.
* In many IEEE papers the numeric **table grids** are drawn as vector graphics
  (not selectable text), so those values are captured as figure **images**
  rather than as text.

## How image removal works (technical)

For each page the tool adds one whole-page redaction box that paints nothing,
then applies it with image removal on (and, in text-only mode, vector line-art
removal too); text removal stays off. The whole-page box also clears images
nested inside Form XObjects — a case a per-image search can miss. Saving with
`garbage=4, clean=True` physically discards the orphaned image objects, so the
file ends up with no image objects at all.

## License

This program is free software, distributed under the GNU General Public
License v3.0. See the [`LICENSE`](LICENSE) file. It comes with **no warranty**.
