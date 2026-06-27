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
TAGLINE = "Projects \u00b7 Modify PDF \u00b7 Decompile to LaTeX / Markdown"
VERSION = "4.5"

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
    "Projects: save everything you set up (file list + selection, options, "
    "output locations, passwords) into a single .paidproj file and resume "
    "later \u2014 New / Open / Save / Save As / Open Recent.",
    "Two activity categories you can run together: \"Modify PDF\" (remove "
    "images, or images + vector figures) and \"Decompile to Text\" (LaTeX "
    "and/or Markdown).",
    "Files tab: add files or whole folders, tick exactly which to process "
    "(Select all / Deselect all), and filter by name / path / size / page "
    "count.",
    "Per-category output: write beside each PDF (Modify PDF uses a mandatory "
    "suffix so the original is never overwritten) or into one chosen folder.",
    "Passwords tab: give a shared pool of candidate passwords and/or a "
    "specific password per file; protected PDFs are unlocked automatically "
    "before processing, and locked files are skipped and flagged.",
    "Inspector tab: file name, size, page count, encryption, recovered "
    "password and permission restrictions, plus a scrollable page preview.",
    "Advanced Modify: remove restrictions & password, search & replace text "
    "(literal or regex), search & replace image (match by similarity, delete "
    "or replace), AI image analysis, page-range selection and pages-to-keep, "
    "plus a Validate mode that reports changes without writing.",
    "Modify security & properties: set a new open password (fixed, or random "
    "per file written to a CSV), apply restrictions (block copy/print/edit), "
    "and set document properties (title/author/subject/keywords).",
    "Password recovery: brute force (charset/length/mask, threads, attempt or "
    "time limits, files in parallel) and dependency-free candidate models "
    "(Markov / rule mangler), with an encrypted reuse pool and your own model "
    "support \u2014 for PDFs you are authorised to open.",
    "Decompile \u2192 LaTeX: one compilable IEEEtran .tex per PDF (title, authors, "
    "abstract, sections, figure & table captions, \\cite{} and bibliography) "
    "with four equation modes; or \u2192 Markdown (full text, no images). A page "
    "range can limit which pages are decompiled.",
    "Configurable short image names (e.g. Prefix_3_Fig-2.png) so several PDFs "
    "can safely share one Latex_Resource folder.",
]

HOW_TO = [
    "1. Project: start a New project (or Open a recent one), name it in the "
    "header, and use Save / Save As to write a .paidproj file.",
    "2. Files tab: \"Add PDF File(s)\u2026\" or \"Add Folder\u2026\", then tick which "
    "files to process (Select all / Deselect all, or filter by "
    "name/size/pages).",
    "3. Passwords tab (only if some PDFs are protected): add a shared password "
    "pool and/or a per-file password; \"Detect passwords now\" checks them.",
    "4. Modify PDF tab: enable it, pick Execute or Validate, choose what to "
    "remove, and set the output location (a suffix is required when writing "
    "beside the PDF).",
    "5. Decompile to Text tab: enable it, pick LaTeX and/or Markdown, the "
    "equation mode, and the output location.",
    "6. Click Run. Progress and a log appear at the bottom; Save the project "
    "to keep your setup and any recovered passwords. For LaTeX, upload the "
    ".tex and its \"Latex_Resource\" folder to Overleaf (or compile locally).",
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
    "Passwords: only unlock PDFs you are authorised to open — the password "
    "tools are a local \"forgot my password\" helper. Brute force only "
    "succeeds against weak passwords; strong AES-256 passwords are infeasible "
    "to recover.",
    "AI models are managed in the Models tab: download, test, add your own, "
    "search/import from Hugging Face, or connect to a local LLM server "
    "(Ollama, LM Studio, …) or cloud platform (Claude, ChatGPT). The Setup "
    "tab installs the optional dependencies. Without any model, a heuristic "
    "description and the built-in password models are used.",
]

# Revision history (newest first). Shown in the About dialog and documented in
# Doc/SKILL.md.
REVISION_HISTORY = [
    ("4.5", "Fixed the dependency installer (it now streams the full pip log "
            "and verifies each package actually imports; the packaged .exe "
            "case is detected and explained). New LLM connections: connect to "
            "local servers (Ollama, LM Studio, Jan, GPT4All, LocalAI, vLLM, "
            "LMDeploy) and cloud platforms (Anthropic/Claude, OpenAI/ChatGPT) "
            "with auto-detect and a connection test; a connected model appears "
            "in the image/password dropdowns and runs with a fixed "
            "per-category instruction plus an optional custom one. The Import "
            "tab can now search Hugging Face in-tool."),
    ("4.4", "Files tab is now a resizable, scrollable table (with a full-path "
            "column, Protected & Restrictions). Modify PDF: a “Do nothing” "
            "option, restriction controls grey out when not applied, owner "
            "password can be fixed or random (saved to the CSV), restriction "
            "labels read “Allow/Disable …”, and blank page ranges auto-fill "
            "“all”. Models are now chosen from dropdowns of what is actually "
            "available (AI options disable with guidance when none); a new "
            "Setup tab detects and installs the optional dependencies "
            "(huggingface_hub / transformers / torch) with one click; each "
            "category’s details moved to its own tab; the Import tab lists "
            "reusable local models."),
    ("4.3", "New Models tab to manage AI models in one place: an Overview "
            "(shared models folder, environment/hardware, category rules), a "
            "sub-tab per category (Password, Image) to download / test / add "
            "your own model, and a Hugging Face import tab. Models are stored "
            "in a shared folder (each in its own subfolder with model.json), "
            "with hardware-aware recommendations and override warnings. "
            "Downloads need the optional 'huggingface_hub' package; image "
            "models need transformers + torch — the tab shows what's missing."),
    ("4.2", "Modify PDF can now set a new open password (fixed or random "
            "per file, written to modified_passwords.csv per output folder), "
            "apply permission restrictions (block copy/print/edit…), and set "
            "document properties (title/author/subject/keywords). The "
            "Inspector shows full properties and restrictions. UI polish: "
            "aligned Files columns with Protected & Restrictions columns; "
            "per-file password list is two-column and shows only protected "
            "files; compact search-&-replace editors; and the Modify PDF and "
            "Decompile tabs use a space-efficient two-column layout."),
    ("4.1", "Completed the v4 feature set. Advanced Modify: remove "
            "restrictions & password, search & replace text (literal/regex) "
            "and image (similarity match), AI image analysis, page-range and "
            "pages-to-keep, and a Validate mode. Password recovery: "
            "multi-threaded brute force (charset/length/mask, attempt/time "
            "limits, files in parallel), dependency-free candidate models "
            "(Markov / rule mangler) plus user models, and an encrypted reuse "
            "pool. AI models are optional and downloaded on demand into the "
            "project folder."),
    ("4.0", "Reorganised into a project-based, tabbed workflow. Projects "
            "(.paidproj) save all settings so work can be resumed; menu for "
            "New / Open / Save / Save As / Open Recent. Two activity "
            "categories — \"Modify PDF\" and \"Decompile to Text\" "
            "(LaTeX / Markdown) — each with its own output destination. New "
            "Files tab (multi-select + filter), Passwords tab (per-file + "
            "shared pool, used to open protected PDFs), and an Inspector tab "
            "(file info, permissions and a page preview)."),
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
