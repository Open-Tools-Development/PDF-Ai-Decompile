#!/usr/bin/env python3
"""
pdf_remove.py
=============
Core image-removal logic (no UI), extracted so the GUI and the converters can
share it. Two modes:

* remove_vector=False : remove raster images only; keep vector graphics,
  tables, equations and the exact text layout. (Clears Claude's image limit.)
* remove_vector=True  : also remove vector graphics -> clean text-only PDF.

Both keep text byte-identical and in the same positions, and the output
contains zero raster images. The whole-page redaction also removes images
nested inside Form XObjects (which a per-image search can miss).
"""

import os

import fitz  # PyMuPDF


def _apply_redactions(page, remove_vector):
    graphics = (
        fitz.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED
        if remove_vector
        else fitz.PDF_REDACT_LINE_ART_NONE
    )
    try:
        page.apply_redactions(
            images=fitz.PDF_REDACT_IMAGE_REMOVE,
            graphics=graphics,
            text=fitz.PDF_REDACT_TEXT_NONE,
        )
        return
    except (TypeError, AttributeError):
        pass
    try:
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_REMOVE)
    except (TypeError, AttributeError):
        page.apply_redactions()


def remove_images_from_pdf(input_path, output_path, remove_vector=False):
    """Remove images from ``input_path`` and write ``output_path``.

    Returns ``(removed, remaining)``:
        removed   - number of raster images removed
        remaining - raster images still detected afterwards (expected 0)
    """
    out_parent = os.path.dirname(os.path.abspath(output_path))
    if out_parent:
        os.makedirs(out_parent, exist_ok=True)

    doc = fitz.open(input_path)
    removed = 0
    try:
        for page in doc:
            n_imgs = len(page.get_images(full=True))
            n_draws = len(page.get_drawings()) if remove_vector else 0
            if n_imgs == 0 and n_draws == 0:
                continue
            try:
                page.add_redact_annot(page.rect, fill=False, cross_out=False)
            except TypeError:
                page.add_redact_annot(page.rect, fill=False)
            _apply_redactions(page, remove_vector)
            removed += n_imgs
        doc.save(output_path, garbage=4, deflate=True, clean=True)
    finally:
        doc.close()

    remaining = 0
    try:
        check = fitz.open(output_path)
        for page in check:
            remaining += len(page.get_images(full=True))
        check.close()
    except Exception:
        remaining = -1
    return removed, remaining


if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 3:
        rv = "--vector" in sys.argv
        print(remove_images_from_pdf(sys.argv[1], sys.argv[2], remove_vector=rv))
    else:
        print("usage: pdf_remove.py <input.pdf> <output.pdf> [--vector]")
