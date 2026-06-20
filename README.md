# PDF Ai Decompile

> Decompile PDF papers back into clean, structured source.

**PDF Ai Decompile** is a small, cross-platform desktop tool that takes PDF
papers and turns them back into formats that are easy for AI tools (and humans)
to work with. It is organised around **projects** (a tabbed workflow you can
save and resume) and two activity categories:

* **Modify PDF** — remove images from a PDF while keeping all text and the
  exact layout (optionally remove vector figures too, for a text-only PDF), and
* **Decompile to Text** — rebuild a PDF into **LaTeX** (one compilable IEEE
  `.tex` per PDF plus a shared `Latex_Resource` folder) and/or **Markdown**
  (full text, no images).

Both categories can run together on the files you select. A **Passwords** tab
unlocks protected PDFs (per-file or a shared pool) before processing, and an
**Inspector** tab shows file info, permissions and a page preview. The LaTeX and
Markdown outputs are designed so that **any AI tool can read the full paper
without processing the PDF**, and the cleaned PDFs upload without hitting image
limits.

Everything you set up — the file list and selection, options, output locations
and passwords — is saved into a single `.paidproj` project file so you can pick
up where you left off (Project ▸ New / Open / Save / Save As / Open Recent).

Built with [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter).
Authors: **Jerry James & Nisha** · Org: **Open-Tools-Development** · License: **GPL-3.0**.

Repository: <https://github.com/Open-Tools-Development/PDF-Ai-Decompile>

---

## Project layout

```
PDF-Ai-Decompile/
├─ README.md                  This file (one level above Scripts)
├─ Doc/
│   └─ SKILL.md               Full architecture / skill document (read this
│                             when migrating to Claude Code)
├─ Published_Tool/            The finished EXE is placed here by build_exe.bat
│   └─ .gitkeep
└─ Scripts/                   All source code and build scripts
    ├─ app/                   UI layer (CustomTkinter)
    │   ├─ __init__.py
    │   ├─ pdf_ai_decompile.py   Main application window + batch runner
    │   └─ about_info.py         Identity, features, how-to, revision history
    ├─ backend/               Backend logic (PDF parsing & conversion)
    │   ├─ __init__.py
    │   ├─ appconfig.py          Per-user config + recent projects
    │   ├─ project.py            Project file (.paidproj) save/load/schema
    │   ├─ pdf_info.py           Scan / password / page-render (Inspector)
    │   ├─ runner.py             Headless project runner (passwords → jobs)
    │   ├─ pdf_common.py         Shared parser (structure, escaping, images)
    │   ├─ pdf_remove.py         Image-removal engine (UI: "Modify PDF")
    │   ├─ pdf_to_latex.py       PDF → LaTeX renderer (4 equation modes)
    │   ├─ pdf_to_markdown.py    PDF → Markdown renderer
    │   ├─ pdf_math.py           Inline-math reconstruction
    │   └─ pdf_equations.py      Display-equation detection + image extraction
    ├─ models/                Native AI models (reserved for future use)
    │   ├─ __init__.py
    │   └─ README.md
    ├─ assets/                Icon + splash and their generator
    │   ├─ icon.ico, icon_preview.png, splash.png
    │   └─ make_assets.py
    ├─ run_app.py             Top-level launcher (also the PyInstaller entry)
    ├─ build_info.py          Build date (auto-generated; reset by clean.bat)
    ├─ requirements.txt
    ├─ install_dependencies.bat
    ├─ run.bat
    ├─ build_exe.bat
    ├─ clean.bat
    ├─ LICENSE
    └─ .gitignore
```

## Quick start (run from source)

1. Install **Python 3.8+** (tick *Add Python to PATH* during setup on Windows).
2. From the `Scripts` folder, run **`install_dependencies.bat`** once.
3. Run **`run.bat`** to open the tool.

On macOS/Linux, from the `Scripts` folder:

```bash
pip install -r requirements.txt
python3 run_app.py
```

## Using the tool

1. **Project** — start a **New** project (or **Open** a recent one) and give it a
   name in the header. **Save** / **Save As** writes a `.paidproj` file holding
   all of the below so you can resume later.
2. **Files tab** — *Add PDF File(s)…* or *Add Folder…* (optionally
   *Subfolders*), then tick which files to process (*Select all* / *Deselect
   all*, or filter by name / path / size / pages).
3. **Passwords tab** (only if some PDFs are protected) — add a shared password
   pool and/or a per-file password; *Detect passwords now* checks them. Locked
   files are skipped and flagged.
4. **Modify PDF tab** — enable it, choose *Execute* or *Validate*, what to
   remove, and the output location. When writing *beside each PDF* a filename
   suffix (default `_noimg`) is **required** so the original is never
   overwritten; to a *separate folder* it is optional.
5. **Decompile to Text tab** — enable it, pick **LaTeX** and/or **Markdown**, the
   equation mode, and the output location.
6. **Inspector tab** — pick a file to see its info, permissions and a page
   preview.
7. Click **Run**. Progress and a log appear at the bottom.

For LaTeX output, upload the `.tex` **and** its `Latex_Resource` folder to
Overleaf, or compile locally with `pdflatex` (two passes).

## Equation handling (PDF → LaTeX)

PDF text extraction cannot fully recover complex LaTeX math. Four modes are
selectable in the UI (default: **Rebuild as LaTeX math text**):

| Mode | What it does | Trade-off |
|------|--------------|-----------|
| Rebuild as LaTeX math text | Editable LaTeX with recovered sub/superscripts and symbols. | Compiles & editable, but complex math is approximate. |
| Improve inline math only | Recovers inline symbols/subscripts; display equations stay plain text. | Lightest touch. |
| Hybrid (text + equation images) | Inline math as text, exact image per display equation. | Editable prose + correct equations (as images). |
| Equation images (exact) | Every display equation inserted as an exact cropped image. | Looks perfect; equations not editable text. |

## Image file naming

Extracted images use a short, configurable prefix from the PDF name, a unique
number (so several PDFs can share one `Latex_Resource` folder), and the
figure/equation number, e.g. `RISAidedM_3_Fig-2.png`, `RISAidedM_11_Eq-5.png`.
The prefix length is set in the UI (default **9**; **0** = full PDF name).

## Build a standalone EXE (Windows)

From the `Scripts` folder, run **`build_exe.bat`**. It refreshes the assets,
stamps the build date into `build_info.py`, bundles the icon/splash, and writes:

```
..\Published_Tool\PDFAiDecompile.exe
```

A native splash shows while the EXE unpacks. Copy the EXE to any Windows PC —
no Python required.

## Clean before committing

Run **`clean.bat`** to delete `build/`, any `dist/`, `*.spec`, `__pycache__/`
and `*.pyc`, and to reset `build_info.py`. Source files and the EXE in
`Published_Tool` are left untouched.

## What the conversion does and doesn't do

* It recovers the **text and structure** (title, authors, abstract, index
  terms, all sections/subsections/sub-subsections, figure & table captions,
  references with `\cite{}` and an embedded bibliography, author biographies).
  It is **not** a pixel-perfect reproduction of the PDF.
* **Equations** are approximate in text mode; use Hybrid/Image for exact math.
* In many IEEE papers the numeric **table grids** are vector graphics (not
  selectable text), so those values are captured as figure images.

See **`Doc/SKILL.md`** for the full architecture, module contracts, data flow
and extension points.

## License

Free software under the GNU General Public License v3.0. See
[`Scripts/LICENSE`](Scripts/LICENSE). It comes with **no warranty**.
