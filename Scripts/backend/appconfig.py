#!/usr/bin/env python3
"""
backend/appconfig.py
====================
Tool-wide (not project-specific) configuration that lives in a per-user folder,
outside the repository and outside any single project. This is where the app
remembers things between runs and between projects:

  * the **recent projects** list (for the "Open Recent" menu),
  * the last opened project,
  * the location of the hidden, encrypted password pool (managed by
    ``backend.passwords`` in a later phase),
  * any other general, machine-local preferences.

Design rules
------------
* Pure logic, no UI imports (safe to call headless / from tests).
* Cross-platform user-config directory:
    - Windows : %APPDATA%\\PDF-Ai-Decompile
    - macOS   : ~/Library/Application Support/PDF-Ai-Decompile
    - Linux   : $XDG_CONFIG_HOME/PDF-Ai-Decompile  (else ~/.config/...)
* Everything is plain JSON so it is easy to read/debug, except the password
  pool which is stored separately and encrypted.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

APP_DIR_NAME = "PDF-Ai-Decompile"
CONFIG_FILENAME = "config.json"
PASSWORD_POOL_FILENAME = ".pwpool.enc"   # hidden, encrypted (managed elsewhere)
CONFIG_SCHEMA_VERSION = 1
MAX_RECENT = 12


# --------------------------------------------------------------------------- #
#  Locations                                                                   #
# --------------------------------------------------------------------------- #
def user_config_dir() -> str:
    """Return (and create) the per-user config directory for the tool."""
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.join(os.path.expanduser("~"), "Library",
                            "Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or \
            os.path.join(os.path.expanduser("~"), ".config")
    path = os.path.join(base, APP_DIR_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def config_path() -> str:
    return os.path.join(user_config_dir(), CONFIG_FILENAME)


def password_pool_path() -> str:
    """Path to the hidden, encrypted global password pool file."""
    return os.path.join(user_config_dir(), PASSWORD_POOL_FILENAME)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- #
#  Load / save                                                                 #
# --------------------------------------------------------------------------- #
def default_config() -> dict:
    return {
        "schema_version": CONFIG_SCHEMA_VERSION,
        "recent_projects": [],   # [{"name", "path", "opened"}], newest first
        "last_project": None,
    }


def load_config() -> dict:
    """Load the tool config, returning defaults if missing/unreadable."""
    path = config_path()
    if not os.path.exists(path):
        return default_config()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return default_config()
        # Merge over defaults so new keys appear for old config files.
        cfg = default_config()
        cfg.update(data)
        cfg.setdefault("recent_projects", [])
        return cfg
    except Exception:
        return default_config()


def save_config(cfg: dict) -> str:
    path = config_path()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, path)   # atomic on the same filesystem
    return path


# --------------------------------------------------------------------------- #
#  Recent-projects helpers                                                      #
# --------------------------------------------------------------------------- #
def add_recent_project(name: str, project_path: str, cfg: dict | None = None,
                       save: bool = True) -> dict:
    """Record a project as most-recently-opened (de-duplicated by path)."""
    cfg = cfg if cfg is not None else load_config()
    ap = os.path.abspath(project_path)
    recents = [r for r in cfg.get("recent_projects", [])
               if os.path.abspath(r.get("path", "")) != ap]
    recents.insert(0, {"name": name, "path": ap, "opened": _now_iso()})
    cfg["recent_projects"] = recents[:MAX_RECENT]
    cfg["last_project"] = ap
    if save:
        save_config(cfg)
    return cfg


def recent_projects(cfg: dict | None = None, prune_missing: bool = True) -> list:
    """Return the recent-projects list, optionally dropping deleted files."""
    cfg = cfg if cfg is not None else load_config()
    recents = cfg.get("recent_projects", [])
    if prune_missing:
        recents = [r for r in recents if os.path.exists(r.get("path", ""))]
    return recents


def forget_recent_project(project_path: str, cfg: dict | None = None,
                          save: bool = True) -> dict:
    cfg = cfg if cfg is not None else load_config()
    ap = os.path.abspath(project_path)
    cfg["recent_projects"] = [r for r in cfg.get("recent_projects", [])
                              if os.path.abspath(r.get("path", "")) != ap]
    if cfg.get("last_project") and os.path.abspath(cfg["last_project"]) == ap:
        cfg["last_project"] = None
    if save:
        save_config(cfg)
    return cfg
