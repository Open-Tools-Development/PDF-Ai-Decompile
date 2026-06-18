#!/usr/bin/env python3
"""
pdf_math.py
===========
Reconstruct mathematics from PDF text spans into LaTeX.

PDF text extraction loses the structure of equations: subscripts and
superscripts become same-line characters, symbols become loose Unicode, and a
display equation is split across several "lines". This module recovers a usable
LaTeX approximation by exploiting two cues PyMuPDF gives per span:

* font SIZE   - a sub/superscript is typeset smaller than the body (e.g. 7pt vs
  10pt), so a size drop signals a script.
* BASELINE y  - a subscript sits below the running baseline, a superscript
  above it; the sign of the baseline shift disambiguates sub from super.

The output is best-effort LaTeX math (not guaranteed identical to the authors'
original source), good enough to compile and to convey the equation to a reader
or an AI tool. Greek letters, operators and relations are mapped to LaTeX
control sequences (WITHOUT \\ensuremath, because the result is already wrapped in
math mode by the caller).
"""

import re
import unicodedata


# Symbol -> bare LaTeX command (no \ensuremath; we are already in math mode).
MATH_SYMBOLS = {
    # Greek lower
    "\u03b1": r"\alpha", "\u03b2": r"\beta", "\u03b3": r"\gamma",
    "\u03b4": r"\delta", "\u03b5": r"\epsilon", "\u03f5": r"\epsilon",
    "\u03b6": r"\zeta", "\u03b7": r"\eta", "\u03b8": r"\theta",
    "\u03b9": r"\iota", "\u03ba": r"\kappa", "\u03bb": r"\lambda",
    "\u03bc": r"\mu", "\u03bd": r"\nu", "\u03be": r"\xi",
    "\u03c0": r"\pi", "\u03c1": r"\rho", "\u03c3": r"\sigma",
    "\u03c2": r"\varsigma", "\u03c4": r"\tau", "\u03c5": r"\upsilon",
    "\u03c6": r"\phi", "\u03d5": r"\phi", "\u03c7": r"\chi",
    "\u03c8": r"\psi", "\u03c9": r"\omega", "\u03d1": r"\vartheta",
    "\u03f1": r"\varrho", "\u03d6": r"\varpi",
    # Greek upper
    "\u0393": r"\Gamma", "\u0394": r"\Delta", "\u0398": r"\Theta",
    "\u039b": r"\Lambda", "\u039e": r"\Xi", "\u03a0": r"\Pi",
    "\u03a3": r"\Sigma", "\u03a6": r"\Phi", "\u03a8": r"\Psi",
    "\u03a9": r"\Omega", "\u03a5": r"\Upsilon",
    # operators / relations
    "\u00d7": r"\times", "\u00f7": r"\div", "\u00b1": r"\pm",
    "\u2213": r"\mp", "\u2217": r"\ast", "\u22c5": r"\cdot",
    "\u00b7": r"\cdot", "\u2022": r"\cdot", "\u2218": r"\circ",
    "\u2211": r"\sum", "\u220f": r"\prod", "\u222b": r"\int",
    "\u221a": r"\sqrt{}", "\u2202": r"\partial", "\u2207": r"\nabla",
    "\u221e": r"\infty", "\u2297": r"\otimes", "\u2295": r"\oplus",
    "\u2299": r"\odot", "\u2208": r"\in", "\u2209": r"\notin",
    "\u2282": r"\subset", "\u2286": r"\subseteq", "\u2287": r"\supseteq",
    "\u222a": r"\cup", "\u2229": r"\cap", "\u2200": r"\forall",
    "\u2203": r"\exists", "\u2264": r"\leq", "\u2265": r"\geq",
    "\u2260": r"\neq", "\u2248": r"\approx", "\u2261": r"\equiv",
    "\u221d": r"\propto", "\u2243": r"\simeq", "\u2245": r"\cong",
    "\u225c": r"\triangleq", "\u226a": r"\ll", "\u226b": r"\gg",
    "\u2192": r"\rightarrow", "\u2190": r"\leftarrow",
    "\u2194": r"\leftrightarrow", "\u21d2": r"\Rightarrow",
    "\u21d0": r"\Leftarrow", "\u21d4": r"\Leftrightarrow",
    "\u2207": r"\nabla", "\u2112": r"\mathcal{L}", "\u2102": r"\mathbb{C}",
    "\u211d": r"\mathbb{R}", "\u2115": r"\mathbb{N}", "\u2124": r"\mathbb{Z}",
    "\u2329": r"\langle", "\u232a": r"\rangle",
    "\u27e8": r"\langle", "\u27e9": r"\rangle",
    "\u2225": r"\|", "\u2223": r"\mid", "\u2032": r"'", "\u2033": r"''",
    "\u2026": r"\dots", "\u00ac": r"\neg", "\u2295": r"\oplus",
    # superscript / subscript digits handled separately
}

# Superscript / subscript Unicode digit blocks -> plain digit + which script.
_SUP = {"\u00b2": "2", "\u00b3": "3", "\u00b9": "1",
        "\u2070": "0", "\u2074": "4", "\u2075": "5", "\u2076": "6",
        "\u2077": "7", "\u2078": "8", "\u2079": "9",
        "\u207a": "+", "\u207b": "-", "\u207f": "n", "\u2071": "i"}
_SUB = {"\u2080": "0", "\u2081": "1", "\u2082": "2", "\u2083": "3",
        "\u2084": "4", "\u2085": "5", "\u2086": "6", "\u2087": "7",
        "\u2088": "8", "\u2089": "9", "\u208a": "+", "\u208b": "-"}


def _sym(ch):
    """Map one character to LaTeX math (returns None to drop)."""
    if ch in MATH_SYMBOLS:
        return MATH_SYMBOLS[ch]
    o = ord(ch)
    if o < 0x80:
        return ch
    # Decompose accented/letter-like to ASCII; otherwise drop.
    decomp = unicodedata.normalize("NFKD", ch)
    ascii_part = "".join(c for c in decomp if ord(c) < 0x80)
    return ascii_part if ascii_part else ""


def spans_to_math(spans, base_size):
    """Convert a list of spans (each a dict with text/size/origin_y) that make
    up a single math line into a LaTeX math string, recovering scripts.

    ``base_size`` is the dominant (body) font size of the line.
    """
    out = []
    script_thresh = base_size * 0.86  # below this size => a script
    # Determine a baseline reference (median of full-size spans' origin_y).
    full = [s for s in spans if s["size"] >= script_thresh]
    if full:
        base_y = sorted(s["origin_y"] for s in full)[len(full) // 2]
    else:
        base_y = spans[0]["origin_y"] if spans else 0.0

    mode = None  # None | "sub" | "sup"

    def close_script():
        nonlocal mode
        if mode is not None:
            out.append("}")
            mode = None

    for s in spans:
        text = s["text"]
        size = s["size"]
        oy = s["origin_y"]
        is_small = size < script_thresh
        # Positive dy => span sits lower on page => subscript.
        dy = oy - base_y

        if is_small and abs(dy) > 0.12 * base_size and text.strip():
            want = "sub" if dy > 0 else "sup"
            if want != mode:
                close_script()
                out.append("_{" if want == "sub" else "^{")
                mode = want
            out.append(_emit_text_math(text))
        else:
            # Full-size (or non-shifted) span: leave any open script.
            if text.strip() or mode is None:
                close_script()
            out.append(_emit_text_math(text))
    close_script()

    latex = "".join(out)
    return _post_clean_math(latex)


def _emit_text_math(text):
    """Map a span's characters to math, expanding sup/sub Unicode digits."""
    res = []
    for ch in text:
        if ch in _SUP:
            res.append("^{" + _SUP[ch] + "}")
        elif ch in _SUB:
            res.append("_{" + _SUB[ch] + "}")
        else:
            res.append(_sym(ch))
    return "".join(res)


# Multi-letter function names that should be upright in math mode.
_FUNC_NAMES = [
    "arg max", "arg min", "argmax", "argmin", "max", "min", "log", "ln",
    "exp", "sin", "cos", "tan", "diag", "tr", "Tr", "det", "Re", "Im",
    "var", "cov", "lim", "sup", "inf",
]


def _post_clean_math(s):
    """Tidy a reconstructed math string."""
    # Collapse runs of spaces.
    s = re.sub(r"[ \t]{2,}", " ", s)
    # Remove spaces just inside script braces: _{ x } -> _{x}
    s = re.sub(r"([_^]\{)\s+", r"\1", s)
    s = re.sub(r"\s+\}", "}", s)
    # Empty scripts -> drop.
    s = s.replace("_{}", "").replace("^{}", "")
    # Upright function names.
    for fn in _FUNC_NAMES:
        s = re.sub(r"(?<![\\A-Za-z])" + re.escape(fn) + r"(?![A-Za-z])",
                   "\\\\operatorname{" + fn.replace(" ", "\\,") + "}", s)
    # Common transpose/Hermitian/inverse superscripts written inline.
    s = s.replace(")T", ")^{T}").replace(")H", ")^{H}")
    s = re.sub(r"\)\s*-1\b", ")^{-1}", s)
    # Collapse duplicate spaces again.
    s = re.sub(r"[ \t]{2,}", " ", s).strip()
    return s


# --------------------------------------------------------------------------- #
#  Inline math detection inside a normal text run                              #
# --------------------------------------------------------------------------- #
# Characters that strongly indicate math content.
_MATH_CHARS = set(MATH_SYMBOLS) | set(_SUP) | set(_SUB) | set("=≈≤≥≠×÷±∓")


def line_has_math(spans, base_size):
    """Heuristic: does this line contain real math (scripts or math symbols)?"""
    script_thresh = base_size * 0.86
    has_script = any(s["size"] < script_thresh and s["text"].strip()
                     for s in spans)
    text = "".join(s["text"] for s in spans)
    has_sym = any(c in _MATH_CHARS for c in text)
    return has_script or has_sym
