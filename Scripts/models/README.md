# models/ — Native AI models (reserved for future use)

This package is a placeholder for **on-device / native AI models** and their
helper scripts that future versions of PDF Ai Decompile will use to improve
"decompilation" quality, for example:

- a layout/figure detector to place figures and captions more accurately,
- a math-OCR / equation-recognition model to turn display equations into real
  LaTeX (instead of the current image or heuristic-text approaches),
- a reading-order / table-structure model for complex multi-column layouts,
- a reference/citation parser that emits clean BibTeX.

## How it is meant to be used

The backend (`backend/`) calls into this package through small, well-defined
functions. Today those are not implemented; the backend uses deterministic,
dependency-free heuristics so the tool works with no model downloads.

When models are added here, keep them optional: the tool must still run if the
model files are absent (fall back to the current heuristics). Document each
model's input/output contract in `Doc/SKILL.md`.

## Suggested layout (when implemented)

```
models/
├─ __init__.py
├─ weights/                 # downloaded model weights (git-ignored)
├─ equation_ocr.py          # display-equation -> LaTeX
├─ layout_detector.py       # figure / caption / column detection
└─ reference_parser.py      # references -> BibTeX
```
