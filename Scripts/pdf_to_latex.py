#!/usr/bin/env python3
"""
pdf_to_latex.py
===============
Convert an (IEEE-style) PDF into a single, self-contained LaTeX file using the
IEEEtran document class, plus a "Latex_Resource" folder of extracted figures.

One .tex per PDF (named after the PDF) that compiles on Overleaf (pdfLaTeX),
recovering title, authors, abstract, index terms, numbered sections /
subsections / sub-subsections, figure & table captions, references (with
\\cite{refN} and an embedded bibliography) and author biographies.

Math handling is selectable via ``math_mode`` because PDF text extraction cannot
fully recover complex LaTeX math:
    "text"   - reconstruct math as LaTeX text (compiles, editable, approximate).
               Default. Inline math gets $...$ with recovered sub/superscripts.
    "image"  - rasterize every display equation as an exact image (not editable).
    "hybrid" - rebuild simple inline math as text AND insert display-equation
               images for the complex ones (best of both).
    "inline" - improve inline math only; leave display equations as plain text.

Image file naming is configurable (see ``name_prefix_len``): files are named
``<prefix>_<n>_<Tag>-<num>`` e.g. ``RISAidedM_3_Fig-2`` / ``RISAidedM_7_Eq-5``.
"""

import os
import re

import fitz  # PyMuPDF

from pdf_common import (
    parse_structure, extract_raster_images, extract_vector_figures,
    latex_text, safe_label, make_name_prefix, build_image_name,
)
from pdf_equations import extract_equation_images


_PREAMBLE = r"""%% ------------------------------------------------------------------
%% Auto-generated from "__SRC_NAME__" by PDF Image Remover (PDF -> LaTeX).
%% Author of tool: Jerry James.  Licensed under GPL-3.0.
%%
%% This file recovers the TEXT and STRUCTURE of the original PDF in a clean,
%% compilable IEEEtran form. It is NOT a pixel-perfect copy of the PDF.
%% Math mode used: __MATH_MODE__.
%% Figures (and any equation images) are in the "Latex_Resource" folder.
%% Compile with pdfLaTeX (e.g., on Overleaf).
%% ------------------------------------------------------------------
\documentclass[journal]{IEEEtran}

\usepackage[T1]{fontenc}
\usepackage[utf8]{inputenc}
\usepackage{lmodern}
\usepackage{amsmath,amssymb,amsfonts}
\usepackage{graphicx}
\usepackage{textcomp}
\usepackage{url}
\usepackage{cite}
\usepackage[hidelinks]{hyperref}

\graphicspath{{Latex_Resource/}{./Latex_Resource/}}

\begin{document}
"""


def _figure_float(image_file, caption_latex, label, star=False):
    env = "figure*" if star else "figure"
    width = r"\textwidth" if star else r"\columnwidth"
    return (
        f"\n\\begin{{{env}}}[!t]\n"
        "  \\centering\n"
        f"  \\includegraphics[width={width}]{{{image_file}}}\n"
        f"  \\caption{{{caption_latex}}}\n"
        f"  \\label{{{label}}}\n"
        f"\\end{{{env}}}\n"
    )


def _equation_image_block(image_file, label):
    """A display equation rendered as a centered image (image/hybrid modes)."""
    return (
        "\n\\begin{figure}[!ht]\n"
        "  \\centering\n"
        f"  \\includegraphics[width=\\columnwidth]{{{image_file}}}\n"
        f"  \\label{{{label}}}\n"
        "\\end{figure}\n"
    )


def convert_pdf_to_latex(pdf_path, out_dir, resource_dirname="Latex_Resource",
                         math_mode="text", name_prefix_len=9):
    """Convert ``pdf_path`` to a .tex file in ``out_dir``.

    Parameters
    ----------
    math_mode : {"text","image","hybrid","inline"}
        How to handle equations (see module docstring).
    name_prefix_len : int
        Number of leading alphanumeric characters of the PDF name to use as the
        image-name prefix (default 9). 0 means use the full alphanumeric stem.

    Returns the path to the written .tex file.
    """
    if math_mode not in ("text", "image", "hybrid", "inline"):
        math_mode = "text"
    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(pdf_path))[0]
    label_stem = safe_label(stem)
    resource_dir = os.path.join(out_dir, resource_dirname)
    prefix = make_name_prefix(stem, name_prefix_len)

    # One global counter across ALL image kinds so names never collide, even
    # when several PDFs share the same Latex_Resource folder.
    counter = {"n": 0}
    # Track figure/equation numbers seen per kind to tag filenames.
    fig_seq = {"fig": 0, "eq": 0, "img": 0, "tab": 0}

    def namer(kind, page):
        counter["n"] += 1
        fig_seq[kind] = fig_seq.get(kind, 0) + 1
        return build_image_name(prefix, counter["n"], kind, fig_seq[kind])

    doc = fitz.open(pdf_path)
    try:
        structure = parse_structure(doc)
        raster = extract_raster_images(doc, resource_dir, stem, namer=namer)
        vector = extract_vector_figures(doc, resource_dir, stem,
                                        start_counter=0, namer=namer)
        equations = []
        if math_mode in ("image", "hybrid"):
            equations = extract_equation_images(doc, resource_dir, stem,
                                                namer=namer)
    finally:
        doc.close()

    # Group figure images by page for caption pairing.
    images_by_page = {}
    for img in raster + vector:
        images_by_page.setdefault(img["page"], []).append(img["file"])
    used_files = set()

    def pop_image_for_page(page):
        for p in (page, page - 1, page + 1):
            lst = images_by_page.get(p)
            if lst:
                f = lst.pop(0)
                used_files.add(f)
                return f
        return None

    # Group equation images by page (consumed as we walk paragraphs).
    eqs_by_page = {}
    for e in equations:
        eqs_by_page.setdefault(e["page"], []).append(e["file"])

    inline_math = math_mode in ("text", "hybrid", "inline")

    def text_latex(s, citations=True):
        return latex_text(s, citations=citations, inline_math=inline_math)

    out = [_PREAMBLE.replace("__SRC_NAME__", os.path.basename(pdf_path))
                    .replace("__MATH_MODE__", math_mode)]

    # --- Title / author block ---
    title_tex = text_latex(structure["title"], citations=False) or \
        text_latex(stem, citations=False)
    out.append(f"\n\\title{{{title_tex}}}\n")

    author_tex = text_latex(structure["authors"], citations=False)
    thanks_tex = text_latex(structure["thanks"], citations=False)
    if not author_tex:
        author_tex = "Unknown Author"
    if thanks_tex:
        out.append(
            "\n\\author{%\n"
            f"  {author_tex}%\n"
            f"  \\thanks{{{thanks_tex}}}%\n"
            "}\n"
        )
    else:
        out.append(f"\n\\author{{{author_tex}}}\n")

    out.append("\n\\maketitle\n")

    # --- Abstract / index terms ---
    if structure["abstract"]:
        out.append("\n\\begin{abstract}\n")
        out.append(text_latex(structure["abstract"]) + "\n")
        out.append("\\end{abstract}\n")
    if structure["index_terms"]:
        out.append("\n\\begin{IEEEkeywords}\n")
        out.append(text_latex(structure["index_terms"], citations=False) + "\n")
        out.append("\\end{IEEEkeywords}\n")

    # --- Body elements ---
    fig_counter = 0
    inserted_eq_pages = set()

    for el in structure["elements"]:
        etype = el["type"]
        if etype == "section":
            out.append(f"\n\\section{{{text_latex(el['text'], citations=False)}}}\n")
        elif etype == "subsection":
            out.append(f"\n\\subsection{{{text_latex(el['text'], citations=False)}}}\n")
        elif etype == "subsubsection":
            out.append(f"\n\\subsubsection{{{text_latex(el['text'], citations=False)}}}\n")
        elif etype == "paragraph":
            out.append("\n" + text_latex(el["text"]) + "\n")
            # In image/hybrid mode, flush this page's equation images right
            # after the first paragraph on that page that we emit.
            if math_mode in ("image", "hybrid"):
                page = el["page"]
                if page not in inserted_eq_pages and eqs_by_page.get(page):
                    for ef in eqs_by_page.get(page, []):
                        used_files.add(ef)
                        out.append(_equation_image_block(
                            ef, f"eq:{label_stem}:{os.path.splitext(ef)[0]}"))
                    inserted_eq_pages.add(page)
        elif etype in ("figure_caption", "table_caption", "algorithm"):
            fig_counter += 1
            cap = text_latex(el["text"])
            img = pop_image_for_page(el["page"])
            label = f"fig:{label_stem}:{fig_counter}"
            if img:
                out.append(_figure_float(img, cap, label))
            else:
                out.append("\n\\par\\textit{" + cap + "}\n")

    # --- Any equation images not yet inserted (e.g., pages with no paragraph) ---
    if math_mode in ("image", "hybrid"):
        for page, files in eqs_by_page.items():
            for ef in files:
                if ef in used_files:
                    continue
                used_files.add(ef)
                out.append(_equation_image_block(
                    ef, f"eq:{label_stem}:{os.path.splitext(ef)[0]}"))

    # --- Leftover figure images (e.g., author photos) ---
    leftovers = [img["file"] for img in (raster + vector)
                 if img["file"] not in used_files]
    if leftovers:
        out.append("\n\\section*{Additional Extracted Figures}\n")
        for f in leftovers:
            fig_counter += 1
            out.append(_figure_float(
                f, "Extracted figure (auto-detected).",
                f"fig:{label_stem}:extra{fig_counter}"))

    # --- Author biographies ---
    if structure["biographies"]:
        out.append("\n\\section*{Author Biographies}\n")
        for para in structure["biographies"]:
            out.append("\n" + text_latex(para) + "\n")

    # --- References (embedded bibliography) ---
    refs = structure["references"]
    if refs:
        out.append("\n\\begin{thebibliography}{" + str(len(refs)) + "}\n")
        for r in refs:
            out.append(
                f"\\bibitem{{ref{r['num']}}} {text_latex(r['text'], citations=False)}\n"
            )
        out.append("\\end{thebibliography}\n")

    out.append("\n\\end{document}\n")

    tex_path = os.path.join(out_dir, f"{stem}.tex")
    with open(tex_path, "w", encoding="utf-8") as fh:
        fh.write("".join(out))

    return tex_path


if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 3:
        mm = sys.argv[3] if len(sys.argv) >= 4 else "text"
        print(convert_pdf_to_latex(sys.argv[1], sys.argv[2], math_mode=mm))
    else:
        print("usage: pdf_to_latex.py <input.pdf> <output_dir> [math_mode]")
