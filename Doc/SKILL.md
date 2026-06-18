---
name: PDF Ai Decompile
description: >
  Desktop tool that "decompiles" PDF papers (especially IEEE-format) back into
  clean structured source. Three operations, runnable in any combination:
  (1) remove images from a PDF while keeping text and layout; (2) convert a PDF
  into a single compilable IEEEtran LaTeX file plus an extracted-figures folder;
  (3) convert a PDF into a full-text Markdown file with no images. The LaTeX and
  Markdown outputs are optimised for AI tools to read without processing the PDF.
  Use this document to understand the whole tool before modifying or extending it.
version: "3.0"
author: Jerry James
org: Open-Tools-Development
license: GPL-3.0
repository: https://github.com/Open-Tools-Development/PDF-Ai-Decompile
language: Python 3.8+
ui: CustomTkinter
key_dependencies: [PyMuPDF (fitz), customtkinter, Pillow]
---

# PDF Ai Decompile — Architecture & Skill Document

This is the authoritative reference for the tool. It is written so that an AI
agent (e.g. Claude Code) can read it once and then confidently navigate, run,
debug and extend the codebase. When you change behaviour, update this file.

---

## 1. Purpose and mental model

A PDF is a *compiled, display-oriented* artifact: text is positioned glyph by
glyph, equations are baked in, and figures may be embedded raster images or
drawn vector graphics. AI tools struggle to read PDFs faithfully and often hit
image-upload limits.

**PDF Ai Decompile reverses that** ("decompiles") into source that is easy to
read and process:

- **Remove images** → a PDF that keeps all text + exact layout but has zero
  raster images (clears image limits), or a fully text-only PDF.
- **PDF → LaTeX** → one compilable IEEEtran `.tex` recovering title, authors,
  abstract, index terms, the full section hierarchy, captions, citations
  (`\cite{}`), an embedded bibliography, and author biographies; figures are
  extracted to a shared `Latex_Resource/` folder.
- **PDF → Markdown** → the full text as Markdown, no images — the lightest,
  most AI-friendly representation.

It is **best-effort text/structure recovery, not a pixel-perfect reverse
renderer**. Equations especially cannot be perfectly recovered from PDF text;
the tool offers four equation strategies (see §6).

---

## 2. Repository layout (packages and responsibilities)

```
PDF-Ai-Decompile/
├─ README.md                 User-facing readme (one level above Scripts/)
├─ Doc/SKILL.md              THIS document
├─ Published_Tool/           Build output (PDFAiDecompile.exe) goes here
└─ Scripts/
    ├─ app/                  UI layer (no PDF logic lives here)
    │   ├─ pdf_ai_decompile.py   The CTk window, option panels, batch runner
    │   └─ about_info.py         All identity strings + revision history
    ├─ backend/              Pure logic, no UI imports; safe to call headless
    │   ├─ pdf_common.py         Shared parser + text→LaTeX + image extraction
    │   ├─ pdf_remove.py         Image removal
    │   ├─ pdf_to_latex.py       LaTeX renderer (consumes pdf_common structure)
    │   ├─ pdf_to_markdown.py    Markdown renderer
    │   ├─ pdf_math.py           Inline math reconstruction (symbols/scripts)
    │   └─ pdf_equations.py      Display-equation detection + rasterisation
    ├─ models/               Reserved for future native AI models (see §10)
    ├─ assets/               icon.ico, splash.png, make_assets.py
    ├─ run_app.py            Launcher: puts Scripts/ on sys.path, calls app.main
    ├─ build_info.py         BUILD_DATE (generated at build, reset by clean)
    ├─ requirements.txt, *.bat, LICENSE, .gitignore
```

**Import rules**
- `backend/*` modules import each other with **relative imports**
  (`from .pdf_common import ...`). They never import `app`.
- `app/pdf_ai_decompile.py` imports `from app import about_info` and
  `from backend.pdf_remove import ...` etc.
- Everything runs with `Scripts/` on `sys.path`. `run_app.py` guarantees that
  (it inserts its own directory). PyInstaller uses `run_app.py` as the entry.

---

## 3. How to run, test and build

**Run from source** (from `Scripts/`):
```bash
pip install -r requirements.txt
python3 run_app.py            # or: python -m app.pdf_ai_decompile
```

**Headless backend use** (no GUI; this is how to script/test conversions):
```python
import sys; sys.path.insert(0, "Scripts")
from backend.pdf_to_latex import convert_pdf_to_latex
from backend.pdf_to_markdown import convert_pdf_to_markdown
from backend.pdf_remove import remove_images_from_pdf

remove_images_from_pdf("paper.pdf", "paper_noimg.pdf", remove_vector=False)
convert_pdf_to_latex("paper.pdf", "out/", math_mode="text", name_prefix_len=9)
convert_pdf_to_markdown("paper.pdf", "out/")
```

**Regenerate icon/splash** (from `Scripts/`): `python -m assets.make_assets`.

**Build the Windows EXE**: run `Scripts/build_exe.bat` on Windows. It calls
PyInstaller with `run_app.py` as entry, `--name PDFAiDecompile`, bundles
`assets/`, collects customtkinter + pymupdf, and writes
`..\Published_Tool\PDFAiDecompile.exe`. `clean.bat` removes build artifacts.

**Validating LaTeX output**: compile with `pdflatex` twice (for refs). The
project has been validated to compile to **0 errors** on real IEEE papers in all
four math modes.

---

## 4. Data flow (end to end)

```
PDF ──▶ backend.pdf_common.parse_structure(doc)
            │     (reading-order blocks → structured elements)
            ▼
      structure dict ───────────────┐
            │                        │
            ├── pdf_to_latex ────────┤ + extract_raster_images
            │     (renders .tex)     │ + extract_vector_figures
            │                        │ + (image/hybrid) pdf_equations.extract_equation_images
            │                        ▼
            │                  Latex_Resource/*.png  (uniquely named)
            │
            └── pdf_to_markdown (renders .md, no images)

PDF ──▶ backend.pdf_remove.remove_images_from_pdf  (independent path)
```

The UI (`app`) only orchestrates: it collects a file queue + options, then for
each PDF runs each enabled operation in a worker thread, posting log/progress
messages back to the Tk main loop through a `queue.Queue`.

---

## 5. backend/pdf_common.py — the shared parser (most important module)

This module turns a PDF into a structured, ordered representation and provides
the text→LaTeX pipeline and image extraction.

### 5.1 Reading order
- `build_ordered_blocks(doc)` → list of text blocks in human reading order.
- Per page, `_get_page_blocks` reads `page.get_text("dict")`, keeps text blocks,
  records `bbox`, dominant font `size`, `bold`, and strips running
  headers/footers by vertical position **and** by regex (IEEE Xplore footer,
  ISSN/copyright line, page numbers, DOI line).
- `_order_blocks_on_page` implements **two-column reading order with full-width
  banding**: blocks wider than ~62% of the page (title, wide captions) split the
  page into horizontal bands; within each band the left column is emitted before
  the right column. This is what makes multi-column IEEE papers come out in the
  right order.

### 5.2 Structure parsing
`parse_structure(doc)` returns a dict:
```
{
  "title": str, "authors": str, "thanks": str,     # thanks = affiliation footnote
  "abstract": str, "index_terms": str,
  "elements": [ {type, text, page}, ... ],
  "references": [ {num:int, text:str}, ... ],
  "biographies": [str, ...],
}
```
`elements` types: `section`, `subsection`, `subsubsection`, `paragraph`,
`figure_caption`, `table_caption`, `algorithm`. The body is produced by walking
the ordered blocks **once** and routing each to the current section, so no text
is dropped. Detection details:
- **Title**: largest-font block in the region above the abstract on page 1
  (restricted so a big drop-cap or a section heading is never mistaken for it).
- **Authors / thanks**: blocks between title and "Abstract"; a block starting
  "Manuscript received" becomes `thanks` (rendered as `\thanks{...}`).
- **Headings**: Roman-numeral sections (`I. INTRODUCTION`), lettered subsections
  (`A. Related Works`), numbered sub-subsections (`1) Foo:`). Named sections like
  `REFERENCES`, `ACKNOWLEDGMENT`, `APPENDIX` are recognised without numbers.
  An IEEE **drop-cap** (a lone capital starting a section's first word) is
  repaired (`L` + `OCATION` → `LOCATION`).
- **References**: after the `REFERENCES` heading, text is split on `[n]` markers
  into `{num, text}`. Parsing stops when an author **biography** is detected
  (heuristics: "received the ... degree", "(Member, IEEE)", etc.); biographies
  are captured separately so they don't pollute the bibliography.

### 5.3 Text → LaTeX pipeline
`latex_text(text, citations=True, inline_math=False)`:
1. Strip C0/C1 control chars (mangled-math artefacts that break LaTeX).
2. If `inline_math` (used by text/inline/hybrid modes): detect inline math
   fragments and wrap them in `$...$` with recovered symbols/subscripts; prose
   between fragments is escaped normally. Otherwise map math Unicode to
   `\ensuremath{...}` tokens.
3. Escape LaTeX specials, convert citations, map Unicode.
- `_convert_citations` turns `[3]`, `[8], [9]`, `[18]–[20]` into a single
  `\cite{...}`, expanding ranges. A negative lookbehind prevents converting
  array indices like `r[0]` or `x[N-1]`.
- Inline-math safety nets (so output always compiles): `_sanitize_math_commands`
  rewrites any unknown `\word` inside `$...$` to `\mathrm{word}`;
  `_balance_math_braces` escapes literal set-notation braces (`{1,...,M}`) and
  closes any script braces left open.

### 5.4 Image extraction + naming
- `extract_raster_images(doc, resource_dir, stem, namer=None)` saves embedded
  raster images (skips tiny icons).
- `extract_vector_figures(doc, resource_dir, stem, start_counter=0, namer=None)`
  finds vector-drawn figures by clustering `page.get_drawings()` rectangles on a
  coarse grid (connected components) and rasterising each cluster (filtered by
  area so rules/tiny marks and full-page are skipped). This captures plots and
  vector tables as PNGs.
- **Naming** (configurable, collision-free across PDFs):
  `make_name_prefix(stem, prefix_len=9)` → first N alphanumerics of the PDF name
  (0 = full). `build_image_name(prefix, counter, kind, fig_number)` →
  `"<prefix>_<counter>_<Tag>-<num>"`, Tag ∈ {Fig, Eq, Img, Tab}. The LaTeX
  renderer passes a `namer` closure with **one global counter** so every image
  across raster/vector/equation kinds gets a unique name; multiple PDFs can
  share one `Latex_Resource/` folder without clashing.

---

## 6. Equations — the four math modes (backend/pdf_to_latex.py + pdf_math.py + pdf_equations.py)

`convert_pdf_to_latex(..., math_mode=...)` supports:

| mode | inline math | display equations | editable? |
|------|-------------|-------------------|-----------|
| `text` (default) | rebuilt as `$...$` LaTeX with recovered scripts | rebuilt as text too | yes (approx.) |
| `inline` | rebuilt as `$...$` | left as plain text | yes |
| `hybrid` | rebuilt as `$...$` | inserted as exact images | mixed |
| `image` | (text) | inserted as exact images | no (images) |

- **pdf_math.py** reconstructs math from spans using two cues PyMuPDF gives per
  span: font **size** (a script is typeset smaller, < 0.86× body) and **baseline
  y** (subscript sits lower, superscript higher). `spans_to_math` emits
  `_{...}` / `^{...}`. `MATH_SYMBOLS` maps Greek/operators/relations to bare
  LaTeX commands (no `\ensuremath`, since already in math mode).
- **pdf_equations.py** detects display equations **conservatively** using the
  right-aligned `(N)` equation-number markers as anchors. For each marker it
  grows a vertical band over the equation's lines (handles tall cases/matrices,
  including rows below the marker) and rasterises that column-region to a PNG
  via `page.get_pixmap(clip=...)`. Because it requires an `(N)` marker, ordinary
  prose is never rasterised by mistake. In image/hybrid mode the renderer
  inserts each page's equation images right after that page's first paragraph.

**Why images at all?** Plain PDF text cannot represent a `cases` brace, a matrix
or stacked limits reliably. The image modes reproduce those exactly. The text
mode is the right default when the user wants to *edit* the math afterward.

---

## 7. backend/pdf_remove.py — image removal

`remove_images_from_pdf(input_path, output_path, remove_vector=False)` →
`(removed, remaining)`.
- For each page it adds **one whole-page redaction annotation** (painting
  nothing) then applies it with image removal on (and, if `remove_vector=True`,
  vector line-art removal too); **text removal stays off**.
- The whole-page redaction also clears images nested inside Form XObjects, which
  a per-image search can miss. Saving with `garbage=4, deflate=True, clean=True`
  physically drops the orphaned image objects, so the output has zero image
  objects. `remaining` is verified by re-opening and counting (expected 0).
- `remove_vector=False` → keep charts/tables/vector graphics + text + exact
  layout (clears AI image limits). `remove_vector=True` → clean text-only PDF.

---

## 8. backend/pdf_to_markdown.py

`convert_pdf_to_markdown(pdf_path, out_dir, math_mode="text",
name_prefix_len=9, out_basename=None)` walks the same `parse_structure` output
and emits Markdown: `#` title, `_authors_`, a `>` blockquote for the affiliation
footnote, `**Abstract.**`, `**Index Terms.**`, `##/###/####` headings, captions
as italic lines (no images by design), `## References` as a numbered list, and
`## Author Biographies`. `math_mode`/`name_prefix_len` are accepted for API
symmetry but Markdown is always full-text, no images (ideal for AI ingestion).
`out_basename` optionally overrides the output file stem.

---

## 9. app/ — the UI layer

`app/pdf_ai_decompile.py` defines:
- `resource_path(rel)` — resolves assets. In a PyInstaller bundle it looks in
  `sys._MEIPASS` (root and `assets/`); from source it resolves
  `Scripts/assets/<rel>` (this file is in `Scripts/app/`).
- `show_source_splash()` — a brief CTk splash when run from source; the EXE uses
  PyInstaller's native `--splash` instead (`close_pyi_splash()` closes it).
- `AboutDialog` — renders identity, features, how-to, notes and **revision
  history** from `about_info`.
- `App` — the main window. Key state:
  - `op_vars`: dict of three `BooleanVar` (remove / latex / markdown) — **any
    combination** can be enabled; Start errors if none are.
  - `dest` ("beside" | "folder") + `output_dir` — **shared** output location.
  - Remove sub-options: `remove_mode` (images | all), `remove_suffix`
    (default `_noimg`).
  - Convert sub-options: `math_mode`, `prefix_len`, `conv_prefix` (optional
    output-name prefix for `.tex`/`.md`).
  - Layout: a **two-column** options area so everything fits without scrolling —
    shared output + Remove options on the left, the taller Convert/equation
    options on the right. Panels are shown/hidden by `_refresh_panels()`.
  - **Mandatory-suffix rule**: if Remove is on AND `dest == "beside"` AND the
    suffix is empty → Start is blocked with an error (protects the original
    PDF). With `dest == "folder"` the suffix is optional. The hint label updates
    live via `_update_suffix_hint()`.
  - `_worker(cfg)` runs in a thread: for each file × each enabled op it calls the
    backend, never overwriting the source, and reports progress
    (`files × ops` steps) and per-file log lines through `msg_queue`.

`about_info.py` holds every user-visible string: `APP_NAME`, `TAGLINE`,
`VERSION`, `AUTHOR`, `ORG`, `LICENSE`, `COPYRIGHT`, `PROJECT_URL`,
`DESCRIPTION`, `FEATURES`, `HOW_TO`, `NOTES`, `REVISION_HISTORY`. Change identity
here and it propagates to the window, About dialog and (via make_assets) splash.

---

## 10. models/ — future native AI models (not yet implemented)

Reserved package for on-device models that would raise quality: math-OCR (real
LaTeX for display equations instead of images/heuristics), layout/figure
detection, reading-order/table-structure models, BibTeX reference parsing. The
contract: backend calls small optional functions here; if model files are
absent the tool must fall back to today's deterministic heuristics. Document any
added model's I/O here and in this file. See `Scripts/models/README.md`.

---

## 11. Conventions, gotchas and extension points

- **Add a new operation**: add a `BooleanVar` to `App.op_vars` + a checkbox + an
  options panel; handle it in `_worker`; implement the logic as a new
  `backend/` module with a single top-level `convert_*`/`process_*` function
  returning the output path. Keep UI out of `backend`.
- **Add an equation/figure heuristic**: prefer `backend/pdf_equations.py`
  (detection) or `backend/pdf_math.py` (symbol/script reconstruction). Keep
  detection conservative (avoid rasterising prose).
- **Naming**: always route image filenames through the `namer` closure so the
  global counter keeps names unique across PDFs sharing a folder.
- **LaTeX must always compile**: any new text that goes into the `.tex` must go
  through `latex_text(...)`; never inject raw PDF text.
- **No browser storage / network** is used. The tool is fully offline.
- **Headless/CI**: the GUI needs a display (use Xvfb to smoke-test); the backend
  needs none and is the right surface for automated tests.
- **Validated fixtures**: the two IEEE papers used in development — a multiband
  CSI delay-estimation paper and an equation-heavy RIS-aided localization paper
  — both convert and compile cleanly (0 pdfLaTeX errors) in all four modes.

---

## 12. Known limitations (be honest about these)

- Conversion recovers text/structure, not pixel-perfect layout.
- `text`/`inline` equation modes are approximations; `hybrid`/`image` give exact
  equations as images.
- In many IEEE papers numeric **table grids are vector graphics** (not selectable
  text); their numbers are captured as figure images, not as text.
- Figure↔caption pairing is by page/order heuristics; occasional mismatches are
  possible. Author photos (raster) with no "Fig." caption are appended under
  "Additional Extracted Figures".
- The Windows `.exe` must be built on Windows (PyInstaller is host-targeted).
