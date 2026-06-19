#!/usr/bin/env python3
"""
about_info.py
=============
Central place for PDF Ai Decompile's identity, feature list, how-to text and
revision history. Used by the GUI's About dialog and by the splash/icon
generator, so the information appears identically everywhere and is trivial to
update.
"""

APP_NAME = "PDF Ai Decompile"
TAGLINE = "Decompile PDFs \u00b7 LaTeX \u00b7 Markdown \u00b7 Modify PDF"
VERSION = "3.1"

# --------------------------------------------------------------------------- #
#  Authors  (single source of truth)                                          #
#  To add a new co-author, append their name to this list \u2014 it propagates    #
#  automatically to the window title-bar, About dialog, splash image and the  #
#  copyright line. Nothing else needs editing.                                #
# --------------------------------------------------------------------------- #
AUTHORS = ["Jerry James", "Nisha Elizabeth"]
COPYRIGHT_YEAR = "2026"


def authors_string(conjunction="&"):
    """Return the author list as a readable string.

    One author  -> "A"
    Two authors -> "A & B"
    Three+      -> "A, B & C"
    """
    names = [a.strip() for a in AUTHORS if a and a.strip()]
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return f"{', '.join(names[:-1])} {conjunction} {names[-1]}"


# Backward-compatible single-string alias used around the app and splash.
AUTHOR = authors_string()
ORG = "Open-Tools-Development"
LICENSE = "GPL-3.0 (GNU General Public License v3.0)"
COPYRIGHT = f"Copyright (C) {COPYRIGHT_YEAR} {authors_string()}"
PROJECT_URL = "https://github.com/Open-Tools-Development/PDF-Ai-Decompile"

DESCRIPTION = (
    "A desktop tool that \u201cdecompiles\u201d PDF papers back into clean, "
    "structured source. It can strip images from a PDF while keeping all text "
    "and the exact layout, or rebuild a PDF into a compilable IEEE LaTeX "
    "project or a full-text Markdown file \u2014 formats that any AI tool can "
    "read without having to process the PDF."
)

FEATURES = [
    "Run several operations at once: enable any combination of Modify PDF, "
    "Convert to LaTeX and Convert to Markdown \u2014 each runs on every PDF.",
    "Modify PDF \u2014 remove images (raster only): keeps charts, tables, "
    "equations and the exact text layout. Clears AI image-upload limits.",
    "Modify PDF \u2014 remove images + figures: also removes vector "
    "plots/diagrams for a clean text-only PDF.",
    "Convert PDF \u2192 LaTeX \u2014 one compilable IEEEtran .tex per PDF, with "
    "title, authors, abstract, index terms, all sections/subsections, "
    "figure & table captions, \\cite{} citations and an embedded bibliography.",
    "Choose how equations are handled: rebuild as LaTeX text, inline-only, "
    "hybrid (text + equation images), or exact equation images \u2014 pick what "
    "suits each paper.",
    "Configurable short image names (e.g. Prefix_3_Fig-2.png): a few letters "
    "from the PDF name + a unique number + the figure number, so several PDFs "
    "can safely share one Latex_Resource folder.",
    "Convert PDF \u2192 Markdown \u2014 full text, no images, ideal for feeding "
    "to AI tools.",
    "Figures (raster images and vector plots) extracted to a shared "
    "\"Latex_Resource\" folder with unique, conflict-free names.",
    "Batch processing: add many PDFs or whole folders at once.",
    "Output beside each PDF, or all to one chosen folder.",
]

HOW_TO = [
    "1. Add the PDF(s): use \"Add PDF File(s)\u2026\" or \"Add Folder\u2026\".",
    "2. Enable one or more Operations (required): Modify PDF, Convert to "
    "LaTeX and/or Convert to Markdown. You can turn on any combination.",
    "3. Set the shared output location (beside each PDF, or one folder), then "
    "the sub-options for each enabled operation.",
    "4. If Modify PDF writes beside each PDF, a filename suffix (e.g. "
    "\"_noimg\") is required so the original PDF is not overwritten. When "
    "writing to a separate folder the suffix is optional.",
    "5. Click the Start button. Progress and a log appear at the bottom.",
    "6. For LaTeX output, upload the .tex and its \"Latex_Resource\" folder to "
    "Overleaf (or compile locally with pdfLaTeX).",
]

NOTES = [
    "LaTeX/Markdown conversion recovers the text and structure of the PDF; it "
    "is not a pixel-perfect reproduction.",
    "PDF text cannot fully recover complex LaTeX math. The \"Rebuild as LaTeX "
    "text\" mode is a good editable approximation; for exact equations choose "
    "the \"Hybrid\" or \"Equation images\" mode, which inserts the real "
    "equations as images.",
    "In many IEEE papers the numeric table grids are drawn as vector graphics "
    "(not selectable text), so those values are captured as figure images "
    "rather than as text.",
]

# Revision history (newest first). Shown in the About dialog and documented in
# Doc/SKILL.md.
REVISION_HISTORY = [
    ("3.1", "Renamed the image-removal operation to \"Modify PDF\" so the "
            "feature is easier to understand — it still removes images "
            "(and optionally vector figures) while keeping text and layout. "
            "Added co-author Nisha and made the author list configurable from a "
            "single place (about_info.AUTHORS)."),
    ("3.0", "Renamed the tool to \"PDF Ai Decompile\" and moved it to the "
            "Open-Tools-Development organisation. Restructured the codebase "
            "into app/ (UI), backend/ (logic) and models/ (future native AI) "
            "packages; added a Doc/SKILL.md architecture document."),
    ("2.2", "Multiple operations can run together (Remove + LaTeX + Markdown). "
            "Shared options shown once; larger two-column options layout; "
            "mandatory filename suffix when removing images beside the source."),
    ("2.1", "Four selectable equation modes (text / inline / hybrid / image); "
            "configurable short image names; window-icon fix."),
    ("2.0", "Added PDF \u2192 LaTeX and PDF \u2192 Markdown converters, the "
            "CustomTkinter UI, splash screen and app icon."),
    ("1.x", "Initial image-removal tool (raster-only and text-only modes)."),
]


def build_date_string():
    """Return the build date/time, falling back gracefully when not built."""
    try:
        import build_info  # generated by build_exe.bat
        return getattr(build_info, "BUILD_DATE", "Development build")
    except Exception:
        return "Development build"
