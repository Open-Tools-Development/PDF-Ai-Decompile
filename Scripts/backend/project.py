#!/usr/bin/env python3
"""
backend/project.py
==================
The **project** concept for PDF Ai Decompile. A project bundles everything the
user has set up — the file list, all "Modify PDF" and "Decompile to Text"
settings, passwords (and any recovered ones), and AI-model references — into a
single human-readable JSON file so the user can close the tool and resume later.

Key ideas
---------
* One project == one ``.paidproj`` JSON file with a friendly ``name``.
* Paths are stored **relative to the project file's folder** whenever possible
  (same drive), so a project folder can be copied to a new location and still
  work; absolute paths are used only when no relative path exists.
* A sibling **project folder** (named after the project) holds heavy assets such
  as downloaded AI models, referenced from the project file by relative path.
* Pure logic, no UI imports.  Opening a project also records it in the per-user
  recent-projects list (see ``backend.appconfig``).

The schema is versioned (``schema_version``) and forward-compatible: loading
merges saved values over the current defaults so older project files keep
working as new options are added.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from . import appconfig

PROJECT_EXT = ".paidproj"
SCHEMA_VERSION = 1


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- #
#  Default project document                                                    #
# --------------------------------------------------------------------------- #
def default_project(name: str = "Untitled Project") -> dict:
    """Return a fresh project dict with all settings at their defaults.

    This is the single source of truth for the project schema; every option the
    UI can set has a home here so it round-trips through save/load.
    """
    now = _now_iso()
    return {
        "schema_version": SCHEMA_VERSION,
        "app": "PDF Ai Decompile",
        "project": {
            "name": name,
            "created": now,
            "modified": now,
            # Relative path (to the project file) of the project's asset folder.
            "assets_dir": name_to_folder(name),
        },

        # The PDF pool.  Each entry carries per-file selection + discovered info
        # so the Files tab and Inspector can render without re-scanning.
        "files": [],   # see make_file_entry()

        # Shared output destinations (one per activity category).
        "output": {
            "modify":    {"dest": "beside", "folder": "", "suffix": "_noimg"},
            "decompile": {"dest": "beside", "folder": ""},
        },

        # Category 1 — Modify PDF.
        "modify_pdf": {
            "enabled": False,             # is this category part of the run?
            "mode": "execute",            # execute | validate (preview-only)
            "remove_images": True,
            "remove_vector": False,
            "remove_restrictions_and_password": False,
            "search_replace_text": [],    # [{find, replace, regex}]
            "search_replace_image": [],   # [{image, match_pct, action, replacement}]
            "image_ai_analysis": {"enabled": False, "model": None},
            "page_range": "all",          # "all" | "1-3,5" (process which pages)
            "keep_pages": "all",          # "all" | "1-3,5" (pages kept in output)
        },

        # Category 2 — Decompile to Text.
        "decompile": {
            "enabled": False,                   # is this category part of the run?
            "formats": ["latex", "markdown"],   # any subset
            "math_mode": "text",                # text | inline | hybrid | image
            "name_prefix_len": 9,
            "out_prefix": "",
            "page_range": "all",
        },

        # Common pre-processing — passwords & unlocking.
        "passwords": {
            "pool": [],            # project-level candidate passwords
            "per_file": {},        # {file_path_key: password}
            "cracking": {
                "enabled": False,
                "method": "bruteforce",       # bruteforce | model | both
                "use_hidden_pool": False,     # also try the encrypted global pool
                "parallel_files": False,      # crack files concurrently vs serial
                "bruteforce": {
                    "charset": "lower+digits",  # named preset or literal chars
                    "min_len": 1,
                    "max_len": 6,
                    "pattern": "",              # optional mask, e.g. ??d?d
                    "threads": 4,
                    "limit_type": "attempts",   # attempts | time | infinite
                    "limit_value": 1000000,
                },
                "model": {
                    "selected": [],   # ids from the curated model list
                    "user_models": [],  # [{id, path}] user-supplied generators
                },
            },
        },

        # AI models referenced by this project (passwords + image analysis).
        "models": {
            "dir": "models",   # relative to the project assets folder
            "installed": [],   # [{id, type, source, path, sha256}]
        },
    }


def make_file_entry(path: str) -> dict:
    """A single PDF pool entry with selection + (later) discovered info."""
    return {
        "path": path,
        "selected": True,
        "password": None,          # confirmed working password, if any
        "password_source": None,   # provided | pool | bruteforce | model | none
        "info": {                  # filled in by the Inspector / scanner
            "page_count": None,
            "size_bytes": None,
            "encrypted": None,
            "permissions": None,
        },
    }


def name_to_folder(name: str) -> str:
    """Turn a project name into a safe folder name (used for the assets dir)."""
    safe = "".join(c if (c.isalnum() or c in " -_") else "_"
                   for c in name).strip()
    return (safe or "project").replace(" ", "_")


# --------------------------------------------------------------------------- #
#  Relative-path round-tripping                                                 #
# --------------------------------------------------------------------------- #
def _relativize(path: str, base_dir: str) -> str:
    """Store ``path`` relative to ``base_dir`` when possible, else absolute."""
    if not path:
        return path
    ap = os.path.abspath(path)
    try:
        rel = os.path.relpath(ap, base_dir)
    except ValueError:
        return ap            # different drive on Windows -> keep absolute
    # Keep it relative even if it walks up, but bail if it is clearly absolute.
    return rel


def _resolve(path: str, base_dir: str) -> str:
    if not path:
        return path
    if os.path.isabs(path):
        return path
    return os.path.normpath(os.path.join(base_dir, path))


def _map_paths(project: dict, fn, base_dir: str) -> dict:
    """Apply ``fn(path, base_dir)`` to every stored path in a copy of project."""
    import copy
    p = copy.deepcopy(project)

    for entry in p.get("files", []):
        if entry.get("path"):
            entry["path"] = fn(entry["path"], base_dir)

    out = p.get("output", {})
    for cat in ("modify", "decompile"):
        folder = out.get(cat, {}).get("folder")
        if folder:
            out[cat]["folder"] = fn(folder, base_dir)

    for sri in p.get("modify_pdf", {}).get("search_replace_image", []):
        for k in ("image", "replacement"):
            if sri.get(k):
                sri[k] = fn(sri[k], base_dir)

    for m in p.get("models", {}).get("installed", []):
        if m.get("path"):
            m["path"] = fn(m["path"], base_dir)

    # per_file password keys are absolute file paths -> re-key them too.
    pf = p.get("passwords", {}).get("per_file", {})
    if pf:
        p["passwords"]["per_file"] = {fn(k, base_dir): v for k, v in pf.items()}

    return p


# --------------------------------------------------------------------------- #
#  Save / load / save-as                                                        #
# --------------------------------------------------------------------------- #
def new_project(name: str = "Untitled Project") -> dict:
    return default_project(name)


def save_project(project: dict, path: str, record_recent: bool = True) -> str:
    """Write the project to ``path`` (paths relativized to its folder)."""
    if not path.lower().endswith(PROJECT_EXT):
        path += PROJECT_EXT
    path = os.path.abspath(path)
    base_dir = os.path.dirname(path)
    os.makedirs(base_dir, exist_ok=True)

    project = dict(project)
    project.setdefault("project", {})
    project["project"]["modified"] = _now_iso()
    project["schema_version"] = SCHEMA_VERSION

    to_write = _map_paths(project, _relativize, base_dir)

    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(to_write, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, path)

    if record_recent:
        appconfig.add_recent_project(
            project.get("project", {}).get("name", "Untitled"), path)
    return path


def save_project_as(project: dict, new_path: str) -> tuple[dict, str]:
    """Save under a new path and (re)name the project after the new file."""
    if not new_path.lower().endswith(PROJECT_EXT):
        new_path += PROJECT_EXT
    project = dict(project)
    project.setdefault("project", {})
    # Name the project after the new file stem (item 3 / item 14).
    stem = os.path.splitext(os.path.basename(new_path))[0]
    project["project"]["name"] = stem
    project["project"]["assets_dir"] = name_to_folder(stem)
    out_path = save_project(project, new_path)
    return project, out_path


def load_project(path: str, record_recent: bool = True) -> dict:
    """Load a project, resolving relative paths and filling new defaults."""
    path = os.path.abspath(path)
    base_dir = os.path.dirname(path)
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    project = _merge_defaults(data)
    project = _map_paths(project, _resolve, base_dir)

    if record_recent:
        appconfig.add_recent_project(
            project.get("project", {}).get("name", "Untitled"), path)
    return project


def _merge_defaults(data: dict) -> dict:
    """Deep-merge a loaded project over current defaults (forward-compat)."""
    base = default_project(
        (data.get("project", {}) or {}).get("name", "Untitled Project"))

    def merge(dst, src):
        for k, v in src.items():
            if isinstance(v, dict) and isinstance(dst.get(k), dict):
                merge(dst[k], v)
            else:
                dst[k] = v
        return dst

    return merge(base, data if isinstance(data, dict) else {})


def project_assets_path(project: dict, project_file_path: str) -> str:
    """Absolute path to the project's asset folder (models, etc.)."""
    base_dir = os.path.dirname(os.path.abspath(project_file_path))
    rel = project.get("project", {}).get("assets_dir") or \
        name_to_folder(project.get("project", {}).get("name", "project"))
    return os.path.normpath(os.path.join(base_dir, rel))
