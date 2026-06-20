#!/usr/bin/env python3
"""
backend/runner.py
=================
The headless batch runner that turns a **project** into outputs. Extracted from
the GUI so it can be unit-tested: given a project dict, it resolves each
selected file's password (per-file value, then the shared pool), runs the
enabled jobs ("Modify PDF" and/or "Decompile to Text" formats) into the
configured output destinations, and reports progress through callbacks.

It never overwrites the source PDF, and it transparently handles locked files
by working on an unlocked temporary copy when a password is known. Files that
stay locked are skipped and flagged (the Inspector surfaces why).
"""

from __future__ import annotations

import os

from . import pdf_info, project as proj
from .pdf_remove import remove_images_from_pdf
from .pdf_to_latex import convert_pdf_to_latex
from .pdf_to_markdown import convert_pdf_to_markdown

JOB_LABELS = {"modify": "Modify PDF", "latex": "Decompile → LaTeX",
              "markdown": "Decompile → Markdown"}


def jobs_for(project: dict) -> list:
    """Which jobs the project's enabled categories imply."""
    jobs = []
    if project.get("modify_pdf", {}).get("enabled"):
        jobs.append("modify")
    dec = project.get("decompile", {})
    if dec.get("enabled"):
        for fmt in dec.get("formats", []):
            if fmt in ("latex", "markdown"):
                jobs.append(fmt)
    return jobs


def selected_files(project: dict) -> list:
    return [f for f in project.get("files", []) if f.get("selected", True)]


def resolve_password(file_entry: dict, project: dict) -> dict:
    """Find a working password for a file (per-file value, then the pool)."""
    path = file_entry["path"]
    pw_cfg = project.get("passwords", {})
    per_file = pw_cfg.get("per_file", {})
    specific = per_file.get(path) or per_file.get(os.path.abspath(path))

    candidates = []
    if specific:
        candidates.append(specific)
    if file_entry.get("password"):
        candidates.append(file_entry["password"])
    candidates += [p for p in pw_cfg.get("pool", []) if p]

    return pdf_info.try_passwords(path, candidates)


def _target_dir(path: str, dest_cfg: dict) -> str:
    if dest_cfg.get("dest") == "folder" and dest_cfg.get("folder"):
        return dest_cfg["folder"]
    return os.path.dirname(os.path.abspath(path))


def run(project: dict, *, log=None, progress=None, stop=None) -> dict:
    """Execute the project. Returns ``{ok, fail, skip}`` counts.

    ``log(str)`` / ``progress(float 0..1)`` / ``stop()->bool`` are optional
    callbacks so a GUI can stream output and cancel.
    """
    log = log or (lambda _m: None)
    progress = progress or (lambda _f: None)
    stop = stop or (lambda: False)

    files = selected_files(project)
    jobs = jobs_for(project)
    if not files:
        log("No files selected.")
        return {"ok": 0, "fail": 0, "skip": 0}
    if not jobs:
        log("No operations enabled (turn on Modify PDF and/or Decompile).")
        return {"ok": 0, "fail": 0, "skip": 0}

    validate = project.get("modify_pdf", {}).get("mode") == "validate"
    total = max(1, len(files) * max(1, len(jobs)))
    step = ok = fail = skip = 0

    for fentry in files:
        if stop():
            break
        path = fentry["path"]
        name = os.path.basename(path)

        pres = resolve_password(fentry, project)
        if pres.get("error"):
            log(f"  SKIP {name}: cannot open ({pres['error']})")
            skip += len(jobs); step += len(jobs); progress(step / total)
            continue
        if pres["needs_password"] and not pres["opened"]:
            log(f"  SKIP {name}: locked (no working password found)")
            fentry["password_source"] = "none"
            skip += len(jobs); step += len(jobs); progress(step / total)
            continue
        working_pw = pres["password"] if pres["needs_password"] else None
        if pres["needs_password"]:
            fentry["password"] = working_pw
            fentry["password_source"] = "provided/pool"

        stem, ext = os.path.splitext(name)
        tmp = None
        try:
            work_path = path
            if pres["needs_password"]:
                # Backends open PDFs without a password; give them an unlocked copy.
                tmp = pdf_info.make_decrypted_copy(path, working_pw)
                work_path = tmp

            for job in jobs:
                if stop():
                    break
                try:
                    _run_one(job, project, path, work_path, stem, ext,
                             validate, log)
                    ok += 1
                except Exception as exc:  # noqa: BLE001
                    fail += 1
                    log(f"  ERROR {name} [{JOB_LABELS.get(job, job)}]: {exc}")
                step += 1
                progress(step / total)
        finally:
            if tmp and os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    log(f"Done. {ok} succeeded, {fail} failed, {skip} skipped.")
    return {"ok": ok, "fail": fail, "skip": skip}


def _run_one(job, project, src_path, work_path, stem, ext, validate, log):
    name = os.path.basename(src_path)

    if job == "modify":
        mcfg = project.get("modify_pdf", {})
        ocfg = project.get("output", {}).get("modify", {})
        target = _target_dir(src_path, ocfg)
        os.makedirs(target, exist_ok=True)
        suffix = ocfg.get("suffix", "_noimg")
        out_name = f"{stem}{suffix}{ext}"
        out_path = os.path.join(target, out_name)
        # Never overwrite the original.
        if os.path.abspath(out_path) == os.path.abspath(src_path):
            out_path = os.path.join(target, f"{stem}_noimg{ext}")
        if validate:
            mode = ("images + figures" if mcfg.get("remove_vector")
                    else "images only")
            log(f"  VALIDATE {name}: would remove {mode} -> "
                f"{os.path.basename(out_path)}")
            return
        removed, remaining = remove_images_from_pdf(
            work_path, out_path, remove_vector=mcfg.get("remove_vector", False))
        note = (f"{removed} image(s) removed" if remaining == 0
                else f"{removed} removed, {remaining} not located")
        log(f"  OK  {name} -> {os.path.basename(out_path)} ({note})")
        return

    # Decompile jobs (latex / markdown).
    dcfg = project.get("decompile", {})
    ocfg = project.get("output", {}).get("decompile", {})
    target = _target_dir(src_path, ocfg)
    os.makedirs(target, exist_ok=True)
    prefix = dcfg.get("out_prefix", "") or ""
    out_basename = f"{prefix}{stem}" if prefix else stem
    math_mode = dcfg.get("math_mode", "text")
    plen = dcfg.get("name_prefix_len", 9)

    if job == "latex":
        tex = convert_pdf_to_latex(work_path, target, math_mode=math_mode,
                                   name_prefix_len=plen,
                                   out_basename=out_basename)
        log(f"  OK  {name} -> {os.path.basename(tex)} (+ Latex_Resource)")
    elif job == "markdown":
        md = convert_pdf_to_markdown(work_path, target, math_mode=math_mode,
                                     name_prefix_len=plen,
                                     out_basename=out_basename)
        log(f"  OK  {name} -> {os.path.basename(md)}")
