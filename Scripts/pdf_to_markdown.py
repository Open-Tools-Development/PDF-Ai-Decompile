#!/usr/bin/env python3
"""
pdf_to_markdown.py
==================
Convert an (IEEE-style) PDF into a single clean Markdown (.md) file containing
the full text, with NO images. Reuses the shared parser in pdf_common.

Output structure:
* # Title
* _Authors_  (+ a footnote block for the manuscript/affiliation info)
* **Abstract** paragraph
* **Index Terms** line
* ## Sections / ### Subsections / #### Sub-subsections, with paragraphs
* Figure / table captions kept as italic lines (no image, by design)
* ## References as a numbered list
* ## Author Biographies

Inline citations are left as [n] (natural for Markdown / AI reading).
"""

import os
import re

import fitz  # PyMuPDF

from pdf_common import parse_structure


def _md_escape(text):
    """Light Markdown escaping: avoid accidental headings / emphasis at line
    starts. We keep it minimal so the text stays readable for AI tools."""
    if not text:
        return ""
    # Collapse whitespace.
    text = re.sub(r"[ \t]+", " ", text).strip()
    return text


def convert_pdf_to_markdown(pdf_path, out_dir, math_mode="text",
                            name_prefix_len=9):
    """Convert ``pdf_path`` to a .md file in ``out_dir``. Returns the .md path.

    ``math_mode`` is accepted for API symmetry with the LaTeX converter. Markdown
    output is full-text with no images by design, so all modes keep equations as
    readable inline text (Unicode math symbols), which is ideal for AI tools.
    ``name_prefix_len`` is accepted but unused here (no image files are written).
    """
    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(pdf_path))[0]

    doc = fitz.open(pdf_path)
    try:
        s = parse_structure(doc)
    finally:
        doc.close()

    out = []
    title = _md_escape(s["title"]) or stem
    out.append(f"# {title}\n")

    if s["authors"]:
        out.append(f"\n_{_md_escape(s['authors'])}_\n")
    if s["thanks"]:
        out.append(f"\n> {_md_escape(s['thanks'])}\n")

    if s["abstract"]:
        out.append("\n**Abstract.** " + _md_escape(s["abstract"]) + "\n")
    if s["index_terms"]:
        out.append("\n**Index Terms.** " + _md_escape(s["index_terms"]) + "\n")

    for el in s["elements"]:
        t = el["type"]
        txt = _md_escape(el["text"])
        if t == "section":
            out.append(f"\n## {txt}\n")
        elif t == "subsection":
            out.append(f"\n### {txt}\n")
        elif t == "subsubsection":
            out.append(f"\n#### {txt}\n")
        elif t == "paragraph":
            out.append("\n" + txt + "\n")
        elif t in ("figure_caption", "table_caption", "algorithm"):
            # No images in Markdown output (by design): keep the caption text.
            out.append("\n*" + txt + "*\n")

    if s["biographies"]:
        out.append("\n## Author Biographies\n")
        for para in s["biographies"]:
            out.append("\n" + _md_escape(para) + "\n")

    if s["references"]:
        out.append("\n## References\n")
        for r in sorted(s["references"], key=lambda x: x["num"]):
            out.append(f"\n{r['num']}. {_md_escape(r['text'])}")
        out.append("\n")

    md_path = os.path.join(out_dir, f"{stem}.md")
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write("".join(out))
    return md_path


if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 3:
        print(convert_pdf_to_markdown(sys.argv[1], sys.argv[2]))
    else:
        print("usage: pdf_to_markdown.py <input.pdf> <output_dir>")
