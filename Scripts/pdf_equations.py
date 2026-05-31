#!/usr/bin/env python3
"""
pdf_equations.py
================
Detect display-equation regions on a PDF page and rasterize them as images.
Used by the "image" and "hybrid" math modes of the PDF -> LaTeX converter.

Strategy
--------
Authors mark display equations with a right-aligned number like "(3)". We use
those markers as anchors: for each marker we grow a vertical band (within its
column) that covers the equation lines immediately above it, then render that
band to a PNG. This reproduces the equation EXACTLY (cases environments,
matrices, integrals), which plain-text reconstruction cannot do reliably.

This module is deliberately conservative: it only treats a region as a display
equation when it has a trailing (N) marker, so ordinary prose is never
rasterized by mistake.
"""

import os
import re

import fitz  # PyMuPDF

_EQNUM_RE = re.compile(r"\((\d{1,3})\)\s*$")
# A line is "mathy" if it carries math symbols or sub/superscript-sized spans.
_MATH_CHARS = set("=≈≤≥≠×÷±∓βκτΩσηφθλμπγρξψχωΔΣΦΨΓΛΘΞΠ∈∉∥√∂∇∫∑∏⊗⊕⊙→←⇒⟨⟩‖†∞≜·")


def _line_records(page):
    """Return per-line records with bbox, text, dominant size, column side."""
    R = page.rect
    cx = R.x0 + R.width / 2.0
    out = []
    d = page.get_text("dict")
    for b in d.get("blocks", []):
        if b.get("type") != 0:
            continue
        for line in b.get("lines", []):
            spans = line.get("spans", [])
            if not spans:
                continue
            text = "".join(s["text"] for s in spans)
            if not text.strip():
                continue
            x0 = min(s["bbox"][0] for s in spans)
            y0 = min(s["bbox"][1] for s in spans)
            x1 = max(s["bbox"][2] for s in spans)
            y1 = max(s["bbox"][3] for s in spans)
            sizes = [s["size"] for s in spans]
            base = max(set(sizes), key=sizes.count)
            small = any(s["size"] < base * 0.86 and s["text"].strip()
                        for s in spans)
            bcx = (x0 + x1) / 2.0
            out.append({
                "text": text.strip(), "x0": x0, "y0": y0, "x1": x1, "y1": y1,
                "size": base, "small": small, "col": 0 if bcx < cx else 1,
            })
    return out


def _is_mathy(rec):
    if rec["small"]:
        return True
    return any(c in _MATH_CHARS for c in rec["text"])


def detect_equation_regions(page, max_lines_up=9):
    """Return a list of fitz.Rect regions, one per display equation.

    Each region spans the column horizontally and covers the equation's lines.
    """
    R = page.rect
    cx = R.x0 + R.width / 2.0
    recs = _line_records(page)
    if not recs:
        return []
    recs.sort(key=lambda r: (r["col"], r["y0"]))

    regions = []
    by_col = {0: [r for r in recs if r["col"] == 0],
              1: [r for r in recs if r["col"] == 1]}

    for col, lst in by_col.items():
        col_x0 = R.x0 + 0.045 * R.width if col == 0 else cx + 0.005 * R.width
        col_x1 = cx - 0.01 * R.width if col == 0 else R.x1 - 0.045 * R.width
        for i, rec in enumerate(lst):
            if not _EQNUM_RE.search(rec["text"]):
                continue
            # Grow upward to cover all the equation's lines. Display equations
            # are tightly stacked with small inter-line gaps; we keep absorbing
            # lines while either (a) the line is mathy, or (b) the vertical gap
            # is small (sub-line spacing, e.g. fraction numerators / cases).
            top = rec["y0"]
            bottom = rec["y1"]
            j = i - 1
            grown = 0
            prose_after_math = False
            while j >= 0 and grown < max_lines_up:
                prev = lst[j]
                gap = top - prev["y1"]
                mathy = _is_mathy(prev)
                # A genuinely large gap ends the equation.
                if gap > 1.6 * prev["size"]:
                    break
                # A clearly-prose lead-in line: take ONE (for context) then stop.
                if not mathy and grown >= 1:
                    if prev["text"].endswith((".", ":", "as", "by", "where")):
                        break
                    if gap > 0.7 * prev["size"]:
                        break
                top = prev["y0"]
                grown += 1
                j -= 1
            # Some equations (cases / matrices) extend BELOW the line that
            # carries the (N) marker. Grow downward a little while the next
            # line is mathy and tightly spaced.
            k = i + 1
            down = 0
            while k < len(lst) and down < 4:
                nxt = lst[k]
                gap = nxt["y0"] - bottom
                if gap > 1.3 * nxt["size"]:
                    break
                if not _is_mathy(nxt):
                    break
                if _EQNUM_RE.search(nxt["text"]):
                    break  # that's a different equation
                bottom = nxt["y1"]
                down += 1
                k += 1
            clip = fitz.Rect(col_x0, top - 3, col_x1, bottom + 5) & R
            if clip.height > 8 and clip.width > 20:
                regions.append(clip)
    # Sort top-to-bottom by column then y.
    regions.sort(key=lambda r: (0 if (r.x0 + r.x1) / 2 < cx else 1, r.y0))
    return regions


def extract_equation_images(doc, resource_dir, stem, dpi=200, namer=None):
    """Rasterize every detected display equation in the document.

    ``namer`` optional callable namer(kind, page) -> base filename.

    Returns a list of dicts: {file, page, y0} ordered by page then position.
    """
    os.makedirs(resource_dir, exist_ok=True)
    out = []
    counter = 0
    for pno, page in enumerate(doc):
        for clip in detect_equation_regions(page):
            try:
                pix = page.get_pixmap(clip=clip, dpi=dpi)
                if pix.width < 24 or pix.height < 12:
                    pix = None
                    continue
                counter += 1
                if namer is not None:
                    base = namer("eq", pno)
                else:
                    base = f"{stem}_eq{counter}"
                fname = base + ".png"
                pix.save(os.path.join(resource_dir, fname))
                out.append({"file": fname, "page": pno, "y0": clip.y0})
                pix = None
            except Exception:
                continue
    return out
