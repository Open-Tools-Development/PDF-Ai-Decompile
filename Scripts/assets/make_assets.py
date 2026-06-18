#!/usr/bin/env python3
"""
make_assets.py
==============
Generate icon.ico and splash.png for PDF Ai Decompile.

Run from the Scripts directory:   python -m assets.make_assets
or from this folder:               python make_assets.py

The icon depicts a PDF page being "decompiled" into structured streams of
code/text on the right \u2014 conveying the tool's purpose at a glance. Assets are
written next to this script (Scripts/assets/).
"""

import os
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = "/usr/share/fonts/truetype/dejavu"


def font(name, size):
    try:
        return ImageFont.truetype(os.path.join(FONT_DIR, name), size)
    except Exception:
        return ImageFont.load_default()


# Palette
BG = (15, 23, 42)          # slate-900
PANEL = (30, 41, 59)       # slate-800
ACCENT = (56, 189, 248)    # sky-400
ACCENT2 = (251, 191, 36)   # amber-400
GREEN = (74, 222, 128)     # emerald-400
VIOLET = (167, 139, 250)   # violet-400
WHITE = (241, 245, 249)
MUTED = (148, 163, 184)


def rounded(draw, box, radius, fill, outline=None, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline,
                           width=width)


# --------------------------------------------------------------------------- #
#  ICON  - a PDF page on the left "decompiling" into code/text streams (right) #
#          with an arrow. Conveys "PDF -> structured source".                  #
# --------------------------------------------------------------------------- #
def make_icon(path, size=256):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size / 256.0

    def S(v):
        return int(v * s)

    # Rounded app tile background.
    rounded(d, [S(8), S(8), S(248), S(248)], S(48), fill=BG)

    # Left: a compact PDF page with a folded corner + "PDF" tag.
    px0, py0, px1, py1 = S(40), S(58), S(116), S(198)
    fold = S(22)
    page = [(px0, py0), (px1 - fold, py0), (px1, py0 + fold), (px1, py1),
            (px0, py1)]
    d.polygon(page, fill=WHITE)
    d.polygon([(px1 - fold, py0), (px1, py0 + fold), (px1 - fold, py0 + fold)],
              fill=MUTED)
    # a couple of faint content lines on the page
    for i, yy in enumerate((S(86), S(100), S(114), S(128))):
        w = S(54) if i != 3 else S(36)
        rounded(d, [px0 + S(10), yy, px0 + S(10) + w, yy + S(6)], S(3),
                fill=(203, 213, 225))
    # "PDF" tag
    rounded(d, [px0 + S(8), S(168), px0 + S(56), S(188)], S(5), fill=(239, 68, 68))
    d.text((px0 + S(13), S(170)), "PDF", font=font("DejaVuSans-Bold.ttf", S(13)),
           fill=WHITE)

    # Middle: a decompile arrow.
    ax0, ax1, ay = S(120), S(150), S(128)
    d.line([(ax0, ay), (ax1, ay)], fill=ACCENT2, width=S(8))
    d.polygon([(ax1 + S(2), ay - S(10)), (ax1 + S(16), ay),
               (ax1 + S(2), ay + S(10))], fill=ACCENT2)

    # Right: structured "streams" (code/text) the PDF decompiles into.
    bx0 = S(158)
    colors = [ACCENT, GREEN, VIOLET, ACCENT, GREEN]
    lengths = [60, 46, 54, 38, 50]
    yy = S(70)
    for c, ln in zip(colors, lengths):
        # a small leading bracket/brace dot then a line = a "token stream"
        d.ellipse([bx0, yy, bx0 + S(8), yy + S(8)], fill=c)
        rounded(d, [bx0 + S(14), yy, bx0 + S(14) + S(ln), yy + S(8)], S(4),
                fill=c)
        yy += S(20)
    # a small angle-bracket motif </> to signal "source/code"
    d.text((bx0, S(176)), "</>", font=font("DejaVuSansMono-Bold.ttf", S(30)),
           fill=WHITE)

    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128),
             (256, 256)]
    img.save(path, format="ICO", sizes=sizes)
    img.save(os.path.splitext(path)[0] + "_preview.png")


# --------------------------------------------------------------------------- #
#  SPLASH                                                                      #
# --------------------------------------------------------------------------- #
def make_splash(path, version, w=640, h=380):
    img = Image.new("RGB", (w, h), BG)
    d = ImageDraw.Draw(img)

    d.rectangle([0, 0, 8, h], fill=ACCENT)
    d.rectangle([0, 0, w, 100], fill=PANEL)

    f_title = font("DejaVuSans-Bold.ttf", 30)
    f_sub = font("DejaVuSans.ttf", 15)
    f_small = font("DejaVuSans.ttf", 13)
    f_tiny = font("DejaVuSans.ttf", 12)
    f_author = font("DejaVuSans-Bold.ttf", 15)

    icon = Image.open(os.path.join(HERE, "icon_preview.png")).convert(
        "RGBA").resize((72, 72))
    img.paste(icon, (26, 14), icon)

    d.text((112, 24), "PDF Ai Decompile", font=f_title, fill=WHITE)
    d.text((114, 64),
           "Decompile PDFs  \u00b7  LaTeX  \u00b7  Markdown  \u00b7  Image removal",
           font=f_sub, fill=ACCENT)

    y = 124
    desc = [
        "Decompile PDF papers back into clean, structured source: strip images",
        "(keeping text & layout), or rebuild a paper into compilable IEEE LaTeX",
        "or full-text Markdown \u2014 ready for any AI tool to read directly.",
    ]
    for line in desc:
        d.text((30, y), line, font=f_small, fill=MUTED)
        y += 22

    y += 12
    chips = ["Remove images", "PDF \u2192 LaTeX", "PDF \u2192 Markdown"]
    cx = 30
    for c in chips:
        tw = d.textlength(c, font=f_tiny)
        rounded(d, [cx, y, cx + tw + 24, y + 28], 14, fill=(2, 6, 23),
                outline=ACCENT, width=1)
        d.text((cx + 12, y + 7), c, font=f_tiny, fill=ACCENT)
        cx += tw + 36

    d.line([30, h - 64, w - 24, h - 64], fill=(51, 65, 85), width=1)
    d.text((30, h - 52), "by Jerry James", font=f_author, fill=WHITE)
    d.text((30, h - 30),
           "Open-Tools-Development  \u00b7  Open source  \u00b7  GPL-3.0",
           font=f_tiny, fill=MUTED)
    vtext = f"v{version}"
    d.text((w - 24 - d.textlength(vtext, font=f_small), h - 50), vtext,
           font=f_small, fill=ACCENT2)
    load = "Starting\u2026"
    d.text((w - 24 - d.textlength(load, font=f_tiny), h - 28), load,
           font=f_tiny, fill=MUTED)

    img.save(path)


def _get_version():
    # Read the version from app.about_info without importing GUI deps.
    scripts = os.path.dirname(HERE)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    try:
        from app import about_info
        return about_info.VERSION
    except Exception:
        return "3.0"


if __name__ == "__main__":
    make_icon(os.path.join(HERE, "icon.ico"))
    make_splash(os.path.join(HERE, "splash.png"), _get_version())
    print("Generated icon.ico, icon_preview.png, splash.png in", HERE)
