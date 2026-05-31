#!/usr/bin/env python3
"""
pdf_common.py
=============
Shared engine for extracting structured content from (IEEE-style) PDF papers.

The goal is NOT to reproduce the visual PDF, but to recover ALL of the text in a
clean, structured form (title, authors, abstract, index terms, numbered sections
and subsections, figure/table captions, references and author biographies) that
both LaTeX and Markdown renderers can consume, and that an AI tool can read with
no PDF processing.

Design notes
------------
* Reading order: pages are processed top-to-bottom; on each page full-width
  blocks (title, wide captions) split the page into horizontal bands, and within
  each band the left column is emitted before the right column. This recovers the
  correct two-column reading order used by IEEE journals.
* Completeness: every body text block is routed to the current section as the
  parser walks the ordered block list once, so nothing is silently dropped
  (running headers, page numbers and the IEEE Xplore download footer are removed
  on purpose).
* Math/equations: PDF text extraction cannot recover LaTeX math, so equations
  come through as approximate plain text. Common Unicode symbols are mapped to
  LaTeX so the document still compiles.

Requires: PyMuPDF (fitz).
"""

import os
import re
import unicodedata

import fitz  # PyMuPDF


# --------------------------------------------------------------------------- #
#  Low-level block extraction                                                  #
# --------------------------------------------------------------------------- #
_BOLD_FLAG = 1 << 4  # PyMuPDF span flag bit for bold


def _block_font_info(block):
    """Return (max_size, is_bold, is_italic) for a text block dict."""
    max_size = 0.0
    bold = False
    italic = False
    for line in block.get("lines", []):
        for span in line.get("spans", []):
            if span["size"] > max_size:
                max_size = span["size"]
            flags = span.get("flags", 0)
            if flags & _BOLD_FLAG:
                bold = True
            if flags & 2:  # italic bit
                italic = True
    return round(max_size, 1), bold, italic


# Footer / header text that should always be discarded.
_FOOTER_PATTERNS = [
    re.compile(r"Authorized licensed use limited to", re.I),
    re.compile(r"Restrictions apply", re.I),
    re.compile(r"Downloaded on .* from IEEE Xplore", re.I),
    re.compile(r"^\d{3,4}-\d{3,4}\s*\u00a9\s*\d{4}\s+IEEE", re.I),  # ISSN © year IEEE
    re.compile(r"Personal use is permitted", re.I),
    re.compile(r"See https?://www\.ieee\.org/publications", re.I),
    re.compile(r"Digital Object Identifier", re.I),
]


def _is_footer_text(text):
    t = text.strip()
    if not t:
        return True
    for pat in _FOOTER_PATTERNS:
        if pat.search(t):
            return True
    # Bare page number
    if re.fullmatch(r"\d{1,4}", t):
        return True
    return False


def _get_page_blocks(page, page_no):
    """Return cleaned text blocks for a page, with font info and bbox."""
    d = page.get_text("dict")
    H = page.rect.height
    blocks = []
    for b in d.get("blocks", []):
        if b.get("type") != 0:  # skip image blocks here
            continue
        size, bold, italic = _block_font_info(b)
        lines = []
        for line in b.get("lines", []):
            line_text = "".join(s["text"] for s in line.get("spans", []))
            lines.append(line_text)
        text = "\n".join(lines).strip()
        if not text:
            continue
        x0, y0, x1, y1 = b["bbox"]
        cy = (y0 + y1) / 2.0
        # Strip running header / footer by vertical position.
        if cy < 0.055 * H or cy > 0.945 * H:
            continue
        if _is_footer_text(text):
            continue
        blocks.append({
            "text": text,
            "lines": lines,
            "bbox": (x0, y0, x1, y1),
            "size": size,
            "bold": bold,
            "italic": italic,
            "page": page_no,
        })
    return blocks


def _order_blocks_on_page(blocks, page_rect):
    """Order blocks into two-column reading order with full-width banding."""
    if not blocks:
        return []
    W = page_rect.width
    cx = page_rect.x0 + W / 2.0
    full = [b for b in blocks if (b["bbox"][2] - b["bbox"][0]) > 0.62 * W]
    cols = [b for b in blocks if b not in full]
    fulls = sorted(full, key=lambda b: b["bbox"][1])

    # Build vertical segments separated by the full-width blocks.
    segs = []
    prev = page_rect.y0
    for fb in fulls:
        segs.append((prev, fb["bbox"][1]))
        prev = fb["bbox"][3]
    segs.append((prev, page_rect.y1 + 1))

    def col_of(b):
        bcx = (b["bbox"][0] + b["bbox"][2]) / 2.0
        return 0 if bcx < cx else 1

    seg_blocks = [[] for _ in segs]
    for b in cols:
        bcy = (b["bbox"][1] + b["bbox"][3]) / 2.0
        idx = len(segs) - 1
        for si, (s, e) in enumerate(segs):
            if s <= bcy < e:
                idx = si
                break
        seg_blocks[idx].append(b)

    ordered = []
    for si in range(len(segs)):
        sb = seg_blocks[si]
        left = sorted((b for b in sb if col_of(b) == 0), key=lambda b: b["bbox"][1])
        right = sorted((b for b in sb if col_of(b) == 1), key=lambda b: b["bbox"][1])
        ordered.extend(left)
        ordered.extend(right)
        if si < len(fulls):
            ordered.append(fulls[si])
    return ordered


def build_ordered_blocks(doc):
    """Return all text blocks of the document in reading order."""
    ordered = []
    for pno, page in enumerate(doc):
        page_blocks = _get_page_blocks(page, pno)
        ordered.extend(_order_blocks_on_page(page_blocks, page.rect))
    return ordered


# --------------------------------------------------------------------------- #
#  Heading / caption detection                                                 #
# --------------------------------------------------------------------------- #
_ROMAN = r"(?:M{0,3}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3}))"
_SECTION_RE = re.compile(r"^(" + _ROMAN + r")\.\s+(\S.{0,70})$")
_NAMED_SECTION_RE = re.compile(
    r"^(ACKNOWLEDGMENTS?|REFERENCES|NOMENCLATURE|APPENDIX(?:\s+[A-Z0-9]+)?"
    r"|APPENDICES)\s*$"
)
_SUBSECTION_RE = re.compile(r"^([A-Z])\.\s+(\S.{0,70})$")
_SUBSUB_RE = re.compile(r"^(\d+)\)\s+(\S.*)$")
_FIG_RE = re.compile(r"^(Fig\.?|Figure)\s*\d+", re.I)
_TABLE_RE = re.compile(r"^TABLE\s+[IVXLC0-9]", re.I)
_ALGO_RE = re.compile(r"^Algorithm\s+\d+", re.I)


def _uppercase_ratio(s):
    letters = [c for c in s if c.isalpha()]
    if not letters:
        return 0.0
    up = [c for c in letters if c.isupper()]
    return len(up) / len(letters)


def _classify_heading(first_line):
    """Return (kind, title) or None. kind in section/subsection/subsubsection."""
    s = first_line.strip()
    if not s:
        return None
    if _NAMED_SECTION_RE.match(s):
        return ("section", s.title() if s.isupper() else s)
    m = _SECTION_RE.match(s)
    if m and _uppercase_ratio(m.group(2)) > 0.55:
        return ("section", m.group(2).strip())
    m = _SUBSECTION_RE.match(s)
    if m and _uppercase_ratio(m.group(2)) < 0.9 and len(s) < 70:
        # Avoid matching a normal sentence; subsection titles are short.
        return ("subsection", m.group(2).strip())
    return None


# --------------------------------------------------------------------------- #
#  Structure parsing                                                           #
# --------------------------------------------------------------------------- #
_BIO_MARKERS = [
    re.compile(r"received the .*degree", re.I),
    re.compile(r"\((?:Student |Senior |Graduate )?Member, IEEE\)"),
    re.compile(r"\(Fellow, IEEE\)"),
    re.compile(r"\(Life Fellow, IEEE\)"),
    re.compile(r"research interests include", re.I),
]


def _looks_like_bio(text):
    for pat in _BIO_MARKERS:
        if pat.search(text):
            return True
    return False


def parse_structure(doc):
    """Parse a document into a structured dict of elements.

    Returns dict with keys:
        title, authors, thanks, abstract, index_terms (strings)
        elements: ordered list of {type, text, page}
            types: section, subsection, subsubsection, paragraph,
                   figure_caption, table_caption, algorithm
        references: list of {num, text}
        biographies: list of paragraph strings
    """
    blocks = build_ordered_blocks(doc)

    title = ""
    authors = ""
    thanks = ""
    abstract = ""
    index_terms = ""
    elements = []
    references = []
    biographies = []

    if not blocks:
        return {
            "title": title, "authors": authors, "thanks": thanks,
            "abstract": abstract, "index_terms": index_terms,
            "elements": elements, "references": references,
            "biographies": biographies,
        }

    # --- Find abstract / index-terms / first-section anchors (needed early) ---
    def line_starts(b, word):
        return b["lines"] and b["lines"][0].strip().lower().startswith(word)

    abstract_idx = None
    index_idx = None
    body_start_idx = None
    thanks_idx = None

    for i, b in enumerate(blocks):
        low0 = b["lines"][0].strip().lower() if b["lines"] else ""
        if abstract_idx is None and low0.startswith("abstract"):
            abstract_idx = i
        if index_idx is None and (low0.startswith("index terms")
                                  or low0.startswith("keywords")):
            index_idx = i
        if (thanks_idx is None and b["page"] == 0
                and re.match(r"^manuscript received", low0)):
            thanks_idx = i
        if body_start_idx is None:
            cls = _classify_heading(b["lines"][0]) if b["lines"] else None
            if cls and cls[0] == "section":
                body_start_idx = i

    # --- Title: largest font block in the TOP region of page 1 ---
    # (Restrict to blocks above the abstract so a large drop-cap / section
    #  heading further down the page is never mistaken for the title.)
    page0 = [b for b in blocks if b["page"] == 0]
    abstract_y = None
    if abstract_idx is not None and blocks[abstract_idx]["page"] == 0:
        abstract_y = blocks[abstract_idx]["bbox"][1]
    title_candidates = [
        b for b in page0
        if abstract_y is None or b["bbox"][1] < abstract_y
    ] or page0
    title_block = None
    if title_candidates:
        max_size = max(b["size"] for b in title_candidates)
        # Top-most block at (near) the max size.
        cands = [b for b in title_candidates if abs(b["size"] - max_size) < 0.3]
        title_block = min(cands, key=lambda b: b["bbox"][1])
        title = " ".join(ln.strip() for ln in title_block["lines"]).strip()
    title_idx = blocks.index(title_block) if title_block in blocks else -1

    # --- Authors: between title and abstract (page 0) ---
    if title_idx >= 0:
        end = abstract_idx if abstract_idx is not None else title_idx + 3
        author_parts = []
        for j in range(title_idx + 1, max(title_idx + 1, end)):
            if j >= len(blocks):
                break
            b = blocks[j]
            if b["page"] != 0:
                break
            if j == thanks_idx:
                continue
            author_parts.append(" ".join(ln.strip() for ln in b["lines"]))
        authors = " ".join(p for p in author_parts if p).strip()

    # --- Thanks / affiliation footnote (page 0) ---
    if thanks_idx is not None:
        thanks = re.sub(r"\s+", " ",
                        " ".join(blocks[thanks_idx]["lines"])).strip()

    # --- Abstract text ---
    if abstract_idx is not None:
        atext = " ".join(blocks[abstract_idx]["lines"])
        atext = re.sub(r"^\s*abstract\s*[\u2014\u2013:\-]*\s*", "", atext, flags=re.I)
        abstract = re.sub(r"\s+", " ", atext).strip()

    # --- Index terms text ---
    if index_idx is not None:
        itext = " ".join(blocks[index_idx]["lines"])
        itext = re.sub(r"^\s*index terms\s*[\u2014\u2013:\-]*\s*", "", itext, flags=re.I)
        itext = re.sub(r"^\s*keywords\s*[\u2014\u2013:\-]*\s*", "", itext, flags=re.I)
        index_terms = re.sub(r"\s+", " ", itext).strip()

    # --- Walk body blocks ---
    if body_start_idx is None:
        # Fallback: start right after index terms / abstract / title.
        body_start_idx = (index_idx or abstract_idx or title_idx or -1) + 1

    mode = "body"            # body -> references -> biography
    ref_accum = []

    consumed = set([title_idx, abstract_idx, index_idx, thanks_idx])

    def emit_paragraphs_with_subsub(lines, page):
        """Emit a block's lines as paragraph(s), splitting out any inline
        sub-subsection markers like '1) Title: ...' that begin a line."""
        # Repair IEEE drop-cap: a lone single capital letter line followed by
        # the remainder of the first word (e.g. 'L' + 'OCATION ...').
        fixed = []
        skip = False
        for k, ln in enumerate(lines):
            if skip:
                skip = False
                continue
            s = ln.strip()
            if (len(s) == 1 and s.isalpha() and s.isupper()
                    and k + 1 < len(lines)):
                nxt = lines[k + 1].lstrip()
                fixed.append(s + nxt)
                skip = True
            else:
                fixed.append(ln)
        # Now group lines into paragraphs, breaking at sub-subsection markers.
        buf = []

        def flush():
            if buf:
                para = re.sub(r"\s+", " ", " ".join(buf)).strip()
                if para:
                    elements.append({"type": "paragraph",
                                     "text": para, "page": page})
                buf.clear()

        for ln in fixed:
            s = ln.strip()
            m = _SUBSUB_RE.match(s)
            if m:
                head_body = m.group(2)
                colon = head_body.find(":")
                if 0 < colon <= 70:
                    flush()
                    htitle = head_body[:colon].strip()
                    elements.append({"type": "subsubsection",
                                     "text": htitle, "page": page})
                    rest = head_body[colon + 1:].strip()
                    if rest:
                        buf.append(rest)
                    continue
            buf.append(ln)
        flush()

    for i in range(body_start_idx, len(blocks)):
        if i in consumed:
            continue
        b = blocks[i]
        first = b["lines"][0].strip() if b["lines"] else ""
        full = re.sub(r"[ \t]+", " ", b["text"]).strip()

        if mode == "body":
            # References heading?
            if _NAMED_SECTION_RE.match(first) and first.strip().upper().startswith("REFERENCES"):
                mode = "references"
                continue
            # Caption blocks
            if _FIG_RE.match(first):
                elements.append({"type": "figure_caption",
                                 "text": re.sub(r"\s+", " ", b["text"]).strip(),
                                 "page": b["page"]})
                continue
            if _TABLE_RE.match(first):
                elements.append({"type": "table_caption",
                                 "text": re.sub(r"\s+", " ", b["text"]).strip(),
                                 "page": b["page"]})
                continue
            if _ALGO_RE.match(first):
                elements.append({"type": "algorithm",
                                 "text": re.sub(r"\s+", " ", b["text"]).strip(),
                                 "page": b["page"]})
                continue
            # Headings
            cls = _classify_heading(first)
            if cls:
                kind, htitle = cls
                elements.append({"type": kind, "text": htitle, "page": b["page"]})
                # Emit any remaining lines of the block as paragraph(s).
                rest_lines = b["lines"][1:]
                if rest_lines:
                    emit_paragraphs_with_subsub(rest_lines, b["page"])
                continue
            # Plain block: emit paragraph(s), handling inline sub-subsections.
            emit_paragraphs_with_subsub(b["lines"], b["page"])

        elif mode == "references":
            if ref_accum and _looks_like_bio(full):
                mode = "biography"
                biographies.append(full)
                continue
            ref_accum.append(full)

        elif mode == "biography":
            biographies.append(full)

    # --- Parse reference entries ---
    if ref_accum:
        joined = " ".join(ref_accum)
        joined = re.sub(r"\s+", " ", joined).strip()
        # Split on [n] markers.
        parts = re.split(r"(?=\[\d+\]\s)", joined)
        for p in parts:
            p = p.strip()
            m = re.match(r"^\[(\d+)\]\s*(.*)$", p, re.S)
            if m:
                references.append({"num": int(m.group(1)),
                                   "text": re.sub(r"\s+", " ", m.group(2)).strip()})

    return {
        "title": title,
        "authors": authors,
        "thanks": thanks,
        "abstract": abstract,
        "index_terms": index_terms,
        "elements": elements,
        "references": references,
        "biographies": biographies,
    }


# --------------------------------------------------------------------------- #
#  Image / figure extraction                                                   #
# --------------------------------------------------------------------------- #
def extract_raster_images(doc, resource_dir, stem, namer=None):
    """Save embedded raster images to resource_dir with unique names.

    ``namer`` is an optional callable namer(kind, page) -> base filename
    (without extension). When omitted, falls back to the legacy
    ``{stem}_img{n}`` scheme.

    Returns list of {file, page} dicts (page is 0-based)."""
    os.makedirs(resource_dir, exist_ok=True)
    saved = []
    seen = set()
    counter = 0
    for pno, page in enumerate(doc):
        for img in page.get_images(full=True):
            xref = img[0]
            if xref in seen:
                continue
            seen.add(xref)
            try:
                pix = fitz.Pixmap(doc, xref)
                if pix.n - pix.alpha >= 4:  # CMYK -> RGB
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                # Skip tiny images (icons/artefacts).
                if pix.width < 32 or pix.height < 32:
                    pix = None
                    continue
                counter += 1
                if namer is not None:
                    base = namer("img", pno)
                else:
                    base = f"{stem}_img{counter}"
                fname = base + ".png"
                pix.save(os.path.join(resource_dir, fname))
                saved.append({"file": fname, "page": pno})
                pix = None
            except Exception:
                continue
    return saved


def _cluster_drawings_grid(page, cell=6.0):
    """Cluster vector drawings into figure regions using a coarse grid.

    Returns list of fitz.Rect bounding boxes (one per connected cluster)."""
    drawings = page.get_drawings()
    if not drawings:
        return []
    R = page.rect
    W, H = R.width, R.height
    ncols = max(1, int(W / cell) + 1)
    nrows = max(1, int(H / cell) + 1)
    grid = bytearray(ncols * nrows)

    def idx(cxi, cyi):
        return cyi * ncols + cxi

    for d in drawings:
        r = d.get("rect")
        if r is None:
            continue
        if r.width <= 0 and r.height <= 0:
            continue
        x0 = max(R.x0, r.x0); y0 = max(R.y0, r.y0)
        x1 = min(R.x1, r.x1); y1 = min(R.y1, r.y1)
        cx0 = int((x0 - R.x0) / cell); cx1 = int((x1 - R.x0) / cell)
        cy0 = int((y0 - R.y0) / cell); cy1 = int((y1 - R.y0) / cell)
        for cyi in range(max(0, cy0), min(nrows - 1, cy1) + 1):
            base = cyi * ncols
            for cxi in range(max(0, cx0), min(ncols - 1, cx1) + 1):
                grid[base + cxi] = 1

    # Connected components (8-connectivity) via iterative flood fill.
    visited = bytearray(ncols * nrows)
    clusters = []
    for start in range(ncols * nrows):
        if not grid[start] or visited[start]:
            continue
        stack = [start]
        visited[start] = 1
        minx = miny = 10 ** 9
        maxx = maxy = -1
        cells = 0
        while stack:
            cur = stack.pop()
            cyi, cxi = divmod(cur, ncols)
            cells += 1
            if cxi < minx: minx = cxi
            if cxi > maxx: maxx = cxi
            if cyi < miny: miny = cyi
            if cyi > maxy: maxy = cyi
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    nxx, nyy = cxi + dx, cyi + dy
                    if 0 <= nxx < ncols and 0 <= nyy < nrows:
                        nidx = nyy * ncols + nxx
                        if grid[nidx] and not visited[nidx]:
                            visited[nidx] = 1
                            stack.append(nidx)
        rx0 = R.x0 + minx * cell
        ry0 = R.y0 + miny * cell
        rx1 = R.x0 + (maxx + 1) * cell
        ry1 = R.y0 + (maxy + 1) * cell
        clusters.append((fitz.Rect(rx0, ry0, rx1, ry1), cells))
    return clusters


def extract_vector_figures(doc, resource_dir, stem, start_counter=0, dpi=200,
                           namer=None):
    """Rasterize vector-drawn figures (plots, diagrams, vector tables).

    ``namer`` optional callable namer(kind, page) -> base filename. When
    omitted, uses the legacy ``{stem}_fig{n}`` scheme.

    Returns list of {file, page} dicts."""
    os.makedirs(resource_dir, exist_ok=True)
    saved = []
    counter = start_counter
    for pno, page in enumerate(doc):
        R = page.rect
        page_area = R.width * R.height
        clusters = _cluster_drawings_grid(page)
        # Sort top-to-bottom, then left-to-right.
        clusters.sort(key=lambda c: (round(c[0].y0, 1), round(c[0].x0, 1)))
        for rect, cells in clusters:
            area = rect.width * rect.height
            if area < 0.03 * page_area or area > 0.75 * page_area:
                continue
            if rect.width < 70 or rect.height < 55:
                continue
            clip = fitz.Rect(rect.x0 - 6, rect.y0 - 6,
                             rect.x1 + 6, rect.y1 + 6) & R
            try:
                pix = page.get_pixmap(clip=clip, dpi=dpi)
                counter += 1
                if namer is not None:
                    base = namer("fig", pno)
                else:
                    base = f"{stem}_fig{counter}"
                fname = base + ".png"
                pix.save(os.path.join(resource_dir, fname))
                saved.append({"file": fname, "page": pno})
                pix = None
            except Exception:
                continue
    return saved


# --------------------------------------------------------------------------- #
#  Text -> LaTeX helpers                                                        #
# --------------------------------------------------------------------------- #
# Common Unicode -> LaTeX (math wrapped in \ensuremath so it works anywhere).
_UNICODE_MAP = {
    # dashes / punctuation
    "\u2013": "--", "\u2014": "---", "\u2212": "-", "\u2010": "-", "\u2011": "-",
    "\u2018": "`", "\u2019": "'", "\u201c": "``", "\u201d": "''",
    "\u2026": "\\ldots{}", "\u00a0": " ", "\u200b": "", "\u00ad": "",
    "\u2032": "\\ensuremath{'}", "\u2033": "\\ensuremath{''}",
    "\u00b7": "\\ensuremath{\\cdot}", "\u2022": "\\ensuremath{\\bullet}",
    "\u00d7": "\\ensuremath{\\times}", "\u00f7": "\\ensuremath{\\div}",
    "\u00b1": "\\ensuremath{\\pm}", "\u2213": "\\ensuremath{\\mp}",
    # super/subscripts (common)
    "\u00b2": "\\ensuremath{^2}", "\u00b3": "\\ensuremath{^3}",
    "\u00b9": "\\ensuremath{^1}", "\u00b0": "\\ensuremath{^{\\circ}}",
    # set / logic / relations
    "\u2208": "\\ensuremath{\\in}", "\u2209": "\\ensuremath{\\notin}",
    "\u2282": "\\ensuremath{\\subset}", "\u2286": "\\ensuremath{\\subseteq}",
    "\u222a": "\\ensuremath{\\cup}", "\u2229": "\\ensuremath{\\cap}",
    "\u2200": "\\ensuremath{\\forall}", "\u2203": "\\ensuremath{\\exists}",
    "\u2264": "\\ensuremath{\\leq}", "\u2265": "\\ensuremath{\\geq}",
    "\u2260": "\\ensuremath{\\neq}", "\u2248": "\\ensuremath{\\approx}",
    "\u2261": "\\ensuremath{\\equiv}", "\u221d": "\\ensuremath{\\propto}",
    "\u2243": "\\ensuremath{\\simeq}", "\u225c": "\\ensuremath{\\triangleq}",
    "\u2245": "\\ensuremath{\\cong}", "\u226a": "\\ensuremath{\\ll}",
    "\u226b": "\\ensuremath{\\gg}",
    # operators / misc math
    "\u2211": "\\ensuremath{\\sum}", "\u220f": "\\ensuremath{\\prod}",
    "\u222b": "\\ensuremath{\\int}", "\u221a": "\\ensuremath{\\surd}",
    "\u2202": "\\ensuremath{\\partial}", "\u2207": "\\ensuremath{\\nabla}",
    "\u221e": "\\ensuremath{\\infty}", "\u2297": "\\ensuremath{\\otimes}",
    "\u2299": "\\ensuremath{\\odot}", "\u2295": "\\ensuremath{\\oplus}",
    "\u2217": "\\ensuremath{\\ast}", "\u2020": "\\ensuremath{\\dagger}",
    "\u2021": "\\ensuremath{\\ddagger}", "\u22c5": "\\ensuremath{\\cdot}",
    "\u2225": "\\ensuremath{\\|}", "\u2329": "\\ensuremath{\\langle}",
    "\u232a": "\\ensuremath{\\rangle}", "\u27e8": "\\ensuremath{\\langle}",
    "\u27e9": "\\ensuremath{\\rangle}",
    # arrows
    "\u2192": "\\ensuremath{\\rightarrow}", "\u2190": "\\ensuremath{\\leftarrow}",
    "\u2194": "\\ensuremath{\\leftrightarrow}",
    "\u21d2": "\\ensuremath{\\Rightarrow}", "\u21d0": "\\ensuremath{\\Leftarrow}",
    "\u21d4": "\\ensuremath{\\Leftrightarrow}",
    "\u2208\ufe00": "\\ensuremath{\\in}",
    # Greek lower
    "\u03b1": "\\ensuremath{\\alpha}", "\u03b2": "\\ensuremath{\\beta}",
    "\u03b3": "\\ensuremath{\\gamma}", "\u03b4": "\\ensuremath{\\delta}",
    "\u03b5": "\\ensuremath{\\epsilon}", "\u03b6": "\\ensuremath{\\zeta}",
    "\u03b7": "\\ensuremath{\\eta}", "\u03b8": "\\ensuremath{\\theta}",
    "\u03b9": "\\ensuremath{\\iota}", "\u03ba": "\\ensuremath{\\kappa}",
    "\u03bb": "\\ensuremath{\\lambda}", "\u03bc": "\\ensuremath{\\mu}",
    "\u03bd": "\\ensuremath{\\nu}", "\u03be": "\\ensuremath{\\xi}",
    "\u03bf": "o", "\u03c0": "\\ensuremath{\\pi}",
    "\u03c1": "\\ensuremath{\\rho}", "\u03c3": "\\ensuremath{\\sigma}",
    "\u03c2": "\\ensuremath{\\varsigma}", "\u03c4": "\\ensuremath{\\tau}",
    "\u03c5": "\\ensuremath{\\upsilon}", "\u03c6": "\\ensuremath{\\phi}",
    "\u03c7": "\\ensuremath{\\chi}", "\u03c8": "\\ensuremath{\\psi}",
    "\u03c9": "\\ensuremath{\\omega}", "\u03d5": "\\ensuremath{\\phi}",
    "\u03b8\ufe00": "\\ensuremath{\\theta}",
    # Greek upper
    "\u0393": "\\ensuremath{\\Gamma}", "\u0394": "\\ensuremath{\\Delta}",
    "\u0398": "\\ensuremath{\\Theta}", "\u039b": "\\ensuremath{\\Lambda}",
    "\u039e": "\\ensuremath{\\Xi}", "\u03a0": "\\ensuremath{\\Pi}",
    "\u03a3": "\\ensuremath{\\Sigma}", "\u03a6": "\\ensuremath{\\Phi}",
    "\u03a8": "\\ensuremath{\\Psi}", "\u03a9": "\\ensuremath{\\Omega}",
    "\u03a5": "\\ensuremath{\\Upsilon}",
}

# LaTeX special characters that must be escaped in plain text.
_LATEX_SPECIAL = {
    "\\": r"\textbackslash{}",
    "{": r"\{", "}": r"\}", "$": r"\$", "&": r"\&", "#": r"\#",
    "_": r"\_", "%": r"\%", "^": r"\textasciicircum{}",
    "~": r"\textasciitilde{}",
}


def _escape_latex(text):
    out = []
    for ch in text:
        out.append(_LATEX_SPECIAL.get(ch, ch))
    return "".join(out)


def _map_unicode(text):
    out = []
    for ch in text:
        o = ord(ch)
        if o < 0x80:
            out.append(ch)
            continue
        if ch in _UNICODE_MAP:
            out.append(_UNICODE_MAP[ch])
            continue
        # Keep Latin-1 / Latin Extended letters (inputenc handles them).
        if 0xA0 <= o <= 0x24F and unicodedata.category(ch).startswith("L"):
            out.append(ch)
            continue
        # Try decomposition to ASCII (e.g., accented -> base if no combining).
        decomp = unicodedata.normalize("NFKD", ch)
        ascii_part = "".join(c for c in decomp if ord(c) < 0x80)
        if ascii_part:
            out.append(ascii_part)
        # else: silently drop unmappable symbol.
    return "".join(out)


_CITE_GROUP_RE = re.compile(
    r"(?<![A-Za-z0-9\]])\[\d+\](?:\s*[\u2013\u2014,\-]\s*\[\d+\])*"
)
_CITE_RANGE_RE = re.compile(r"\[(\d+)\]\s*[\u2013\u2014\-]\s*\[(\d+)\]")
_CITE_SINGLE_RE = re.compile(r"\[(\d+)\]")


def _convert_citations(text):
    """Replace bracketed reference numbers with \\cite{...}.

    A bracket group is only treated as a citation when it is NOT immediately
    preceded by an identifier/closing-bracket character, so array indices like
    ``r[0]`` or ``x[N-1]`` are left alone.
    """
    def repl(m):
        group = m.group(0)
        nums = []
        for rm in _CITE_RANGE_RE.finditer(group):
            a, b = int(rm.group(1)), int(rm.group(2))
            if 0 < b - a < 60:
                nums.extend(range(a, b + 1))
        singles = [int(x) for x in _CITE_SINGLE_RE.findall(group)]
        for s in singles:
            if s not in nums:
                nums.append(s)
        nums = sorted(set(nums))
        if not nums:
            return group
        keys = ",".join(f"ref{n}" for n in nums)
        return "\\cite{" + keys + "}"

    return _CITE_GROUP_RE.sub(repl, text)


def _inline_mathify(text):
    """Wrap inline math fragments in $...$, converting math Unicode to LaTeX
    commands inside the math, while leaving ordinary prose untouched.

    Conservative: only fragments that clearly look like math (a math symbol,
    or a single/short token carrying a sub/superscript or Greek letter) get
    wrapped. This runs on the RAW text, before LaTeX escaping of prose.
    """
    from pdf_math import MATH_SYMBOLS, _SUP, _SUB

    math_unicode = set(MATH_SYMBOLS) | set(_SUP) | set(_SUB) | set(
        "=≈≤≥≠×÷±∓∥√")
    # Token = a maximal run of non-space chars. We greedily merge adjacent
    # mathy tokens (and the spaces between them) into one math span.
    tokens = re.split(r"(\s+)", text)

    def token_is_math(tok):
        if not tok.strip():
            return False
        if any(c in math_unicode for c in tok):
            return True
        # variable with a digit/letter subscript pattern like x_g handled later;
        # treat short tokens with Greek as math
        return False

    out = []
    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        if token_is_math(tok):
            # Extend across following (space, mathy) pairs.
            j = i
            span_parts = [tok]
            k = i + 1
            while k + 1 < n:
                sep = tokens[k]
                nxt = tokens[k + 1]
                if sep.strip() == "" and (token_is_math(nxt) or _short_var(nxt)):
                    span_parts.append(sep)
                    span_parts.append(nxt)
                    k += 2
                else:
                    break
            raw = "".join(span_parts)
            out.append("\x00MATH\x00" + raw + "\x00ENDMATH\x00")
            i = k
        else:
            out.append(tok)
            i += 1
    return "".join(out)


def _short_var(tok):
    """A short token that is plausibly part of a surrounding math expression.

    Deliberately strict: a single variable letter (optionally with a digit),
    a number, a bracket, or an operator. English words like 'is', 'the', 'are'
    must NOT match, or prose gets swallowed into math spans.
    """
    t = tok.strip()
    if not t:
        return False
    # Pure operators / brackets / punctuation used in math.
    if re.fullmatch(r"[()\[\]{}+\-/*<>|=,;:]{1,3}", t):
        return True
    # A single variable letter, optionally followed by ONE digit (x, M2),
    # or a short all-caps/!-vowel matrix-ish token (no lowercase English word).
    if re.fullmatch(r"[A-Za-z]\d?", t):
        return True
    # A bare number (integer or decimal).
    if re.fullmatch(r"\d+(?:\.\d+)?", t):
        return True
    return False


def _render_inline_math(raw):
    """Convert a raw math fragment (between sentinels) to $...$ LaTeX,
    applying light subscript heuristics since plain text lacks font cues."""
    from pdf_math import _emit_text_math, _post_clean_math
    body = _emit_text_math(raw)
    # Only these variable-like Greek letters take a trailing subscript run.
    # (Relations/operators like \leq, \in, \times must NOT, or we'd produce
    #  nonsense such as "\leq_{1}".)
    var_cmds = [r"\alpha", r"\beta", r"\gamma", r"\delta", r"\epsilon",
                r"\zeta", r"\eta", r"\theta", r"\iota", r"\kappa",
                r"\lambda", r"\mu", r"\nu", r"\xi", r"\rho", r"\sigma",
                r"\tau", r"\upsilon", r"\phi", r"\chi", r"\psi", r"\omega",
                r"\Gamma", r"\Delta", r"\Theta", r"\Lambda", r"\Xi", r"\Pi",
                r"\Sigma", r"\Phi", r"\Psi", r"\Omega"]
    var_cmds.sort(key=len, reverse=True)
    for cmd in var_cmds:
        # Insert subscript braces; the negative-lookahead guards the command
        # name so it is never extended into an invalid sequence.
        body = re.sub(
            re.escape(cmd) + r"([A-Za-z0-9]{1,4})(?![A-Za-z])",
            lambda m: cmd + "_{" + m.group(1) + "}", body)
    body = _post_clean_math(body)
    body = body.strip()
    if not body:
        return ""
    body = _sanitize_math_commands(body)
    body = _balance_math_braces(body)
    return "$" + body + "$"


# Math commands that are safe to leave as-is inside $...$.
_SAFE_MATH_CMDS = {
    "alpha", "beta", "gamma", "delta", "epsilon", "varepsilon", "zeta", "eta",
    "theta", "vartheta", "iota", "kappa", "lambda", "mu", "nu", "xi", "pi",
    "varpi", "rho", "varrho", "sigma", "varsigma", "tau", "upsilon", "phi",
    "varphi", "chi", "psi", "omega", "Gamma", "Delta", "Theta", "Lambda",
    "Xi", "Pi", "Sigma", "Phi", "Psi", "Omega", "Upsilon",
    "times", "div", "pm", "mp", "ast", "cdot", "circ", "sum", "prod", "int",
    "sqrt", "partial", "nabla", "infty", "otimes", "oplus", "odot", "in",
    "notin", "subset", "subseteq", "supseteq", "cup", "cap", "forall",
    "exists", "leq", "geq", "neq", "approx", "equiv", "propto", "simeq",
    "cong", "triangleq", "ll", "gg", "rightarrow", "leftarrow",
    "leftrightarrow", "Rightarrow", "Leftarrow", "Leftrightarrow", "langle",
    "rangle", "mid", "dots", "ldots", "cdots", "neg", "operatorname",
    "mathcal", "mathbb", "mathrm", "mathbf", "left", "right", "frac", "text",
}


def _sanitize_math_commands(body):
    """Replace any unknown ``\\word`` sequence inside math with upright text,
    so a mis-reconstructed run like ``\\Omegagggej`` cannot break compilation.
    """
    def fix(m):
        name = m.group(1)
        if name in _SAFE_MATH_CMDS:
            return "\\" + name
        # Unknown: render the letters uprightly (drop the backslash).
        return "\\mathrm{" + name + "}"

    return re.sub(r"\\([A-Za-z]+)", fix, body)


def _balance_math_braces(body):
    """Ensure braces in a math fragment are balanced.

    Script braces we inserted (``_{`` / ``^{``) and command-argument braces are
    legitimate; but a literal ``{`` from set notation like ``{1,...,M}`` whose
    partner ``}`` falls outside the fragment leaves an unbalanced brace that
    breaks LaTeX. We convert *literal* set-notation braces to ``\\{`` / ``\\}``
    and then append any missing closing braces for our own scripts.
    """
    out = []
    i = 0
    n = len(body)
    open_script = 0
    while i < n:
        ch = body[i]
        if ch == "{":
            prev = body[i - 1] if i > 0 else ""
            if prev in ("_", "^") or prev.isalpha():
                open_script += 1
                out.append("{")
            else:
                out.append("\\{")
        elif ch == "}":
            if open_script > 0:
                open_script -= 1
                out.append("}")
            else:
                out.append("\\}")
        else:
            out.append(ch)
        i += 1
    out.append("}" * open_script)
    return "".join(out)


def latex_text(text, citations=True, inline_math=False):
    """Full pipeline. With ``inline_math`` True, inline math fragments are
    wrapped in $...$ with recovered symbols; otherwise math Unicode is mapped
    to \\ensuremath{...} tokens in prose (legacy behaviour)."""
    if not text:
        return ""
    # Remove control characters (C0/C1) that leak from mangled PDF math.
    text = "".join(
        ch for ch in text
        if ch in ("\t", "\n") or ord(ch) >= 0x20
    )

    if inline_math:
        # Normalize a leading list bullet to a text bullet (not math).
        text = re.sub(r"^\s*[\u2022\u00b7\u25cf\u2219]\s+",
                      "\\\\textbullet\\\\ ", text)
        # 1) Mark math spans on raw text.
        marked = _inline_mathify(text)
        # 2) Split into prose vs math, process each appropriately.
        pieces = re.split(r"\x00MATH\x00(.*?)\x00ENDMATH\x00", marked)
        rendered = []
        for idx, piece in enumerate(pieces):
            if idx % 2 == 1:
                rendered.append(_render_inline_math(piece))
            else:
                p = _escape_latex(piece)
                if citations:
                    p = _convert_citations(p)
                p = _map_unicode(p)
                rendered.append(p)
        return "".join(rendered)

    # Legacy prose path.
    t = _escape_latex(text)
    if citations:
        t = _convert_citations(t)
    t = _map_unicode(t)
    return t


def safe_label(stem):
    """A LaTeX-label-safe version of a filename stem."""
    return re.sub(r"[^A-Za-z0-9]+", "-", stem).strip("-") or "doc"


def make_name_prefix(stem, prefix_len=9):
    """Build a short, filesystem-safe prefix from the first ``prefix_len``
    alphanumeric characters of the PDF name.

    e.g. "RIS-Aided Mobile Localization.pdf" -> "RISAidedM" (len 9).
    """
    alnum = re.sub(r"[^A-Za-z0-9]+", "", stem)
    if not alnum:
        alnum = "doc"
    if prefix_len and prefix_len > 0:
        return alnum[:prefix_len]
    return alnum


def build_image_name(prefix, counter, kind="fig", fig_number=None):
    """Compose a unique, descriptive image filename (without extension dir).

    Layout:  <prefix>_<counter>[_Fig-<n>]
      prefix     short PDF-name prefix (see make_name_prefix)
      counter    global unique number, prevents duplicates across PDFs
      fig_number when known, appended as 'Fig-3' / 'Eq-7' so the file maps
                 to the figure/equation number in the paper.

    Examples:
      build_image_name("RISAidedM", 1, "fig", 3)  -> "RISAidedM_1_Fig-3"
      build_image_name("RISAidedM", 5, "eq", 7)   -> "RISAidedM_5_Eq-7"
      build_image_name("RISAidedM", 2, "img")     -> "RISAidedM_2_Img"
    """
    tag = {"fig": "Fig", "eq": "Eq", "img": "Img", "tab": "Tab"}.get(kind, "Fig")
    if fig_number is not None:
        return f"{prefix}_{counter}_{tag}-{fig_number}"
    return f"{prefix}_{counter}_{tag}"
