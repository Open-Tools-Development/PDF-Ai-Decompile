#!/usr/bin/env python3
"""
backend/runner.py
=================
The headless batch runner that turns a **project** into outputs. Extracted from
the GUI so it can be unit-tested.

Per run it: (1) optionally recovers passwords for locked files (pool / hidden
pool / brute force / model guesses — see ``backend.passwords`` and
``backend.models``), (2) for each selected file resolves a working password and
unlocks a temporary copy if needed, then (3) runs the enabled jobs — "Modify
PDF" (via ``backend.pdf_modify``) and/or "Decompile to Text" — into the
configured output destinations. It never overwrites the source PDF; files that
stay locked are skipped and flagged. Every confirmed password is recorded
(de-duplicated) into the hidden encrypted reuse pool.
"""

from __future__ import annotations

import os
import threading

from . import pdf_info, pdf_modify, passwords, models
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


def _record_password(pw):
    """Remember a confirmed/provided password in the hidden encrypted pool."""
    if pw:
        try:
            passwords.add_to_hidden_pool([pw])
        except Exception:
            pass


# --------------------------------------------------------------------------- #
#  Password recovery (pool → hidden pool → brute force / model)                #
# --------------------------------------------------------------------------- #
def recover_password(fentry: dict, project: dict, *, stop=None, log=None) -> dict:
    """Resolve or crack a file's password. Returns
    ``{needs_password, opened, password, source, attempts?}``."""
    log = log or (lambda _m: None)
    stop = stop or (lambda: False)
    name = os.path.basename(fentry["path"])

    res = resolve_password(fentry, project)
    if res.get("error"):
        return {"needs_password": None, "opened": False, "password": None,
                "source": "error", "error": res["error"]}
    if not res["needs_password"]:
        return {"needs_password": False, "opened": True, "password": None,
                "source": "none"}
    if res["opened"]:
        _record_password(res["password"])
        return {"needs_password": True, "opened": True,
                "password": res["password"], "source": "provided/pool"}

    cr = project.get("passwords", {}).get("cracking", {})
    if not cr.get("enabled"):
        return {"needs_password": True, "opened": False, "password": None,
                "source": "none"}

    # Build the candidate pool that precedes brute force.
    extra = []
    if cr.get("use_hidden_pool"):
        extra += passwords.load_hidden_pool()
    extra += [p for p in project.get("passwords", {}).get("pool", []) if p]

    method = cr.get("method", "bruteforce")
    bf = dict(cr.get("bruteforce", {}))
    if method in ("model", "both"):
        hints = {"samples": list(dict.fromkeys(extra)),
                 "min_len": int(bf.get("min_len", 1)),
                 "max_len": int(bf.get("max_len", 16)), "count": 5000}
        mc = cr.get("model", {})
        for mid in mc.get("selected", []):
            try:
                extra += list(models.make_password_generator(mid, hints))
            except Exception:
                pass
        for um in mc.get("user_models", []):
            p = um.get("path") if isinstance(um, dict) else um
            if p:
                try:
                    extra += list(models.make_password_generator(p, hints))
                except Exception:
                    pass
    if method == "model":
        bf["skip_bruteforce"] = True

    log(f"  CRACK {name}: trying (method={method})…")
    result = passwords.crack_file(
        fentry["path"], config=bf, extra_candidates=extra, stop=stop,
        on_progress=lambda a: log(f"    …{a} tried") if a % 5000 == 0 else None)
    if result["found"]:
        _record_password(result["password"])
        log(f"  CRACK {name}: FOUND \"{result['password']}\" "
            f"in {result['attempts']} attempt(s)")
        return {"needs_password": True, "opened": True,
                "password": result["password"], "source": "cracked",
                "attempts": result["attempts"]}
    log(f"  CRACK {name}: not found ({result['reason']}, "
        f"{result['attempts']} attempt(s))")
    return {"needs_password": True, "opened": False, "password": None,
            "source": "none", "attempts": result["attempts"]}


def recovery_pass(project: dict, *, stop=None, log=None):
    """Recover passwords for all selected files before processing.

    Honours ``cracking.parallel_files`` (crack files concurrently vs serially).
    """
    log = log or (lambda _m: None)
    stop = stop or (lambda: False)
    cr = project.get("passwords", {}).get("cracking", {})
    if not cr.get("enabled"):
        return
    files = selected_files(project)

    def do(f):
        if stop():
            return
        r = recover_password(f, project, stop=stop, log=log)
        if r.get("opened") and r.get("password"):
            f["password"] = r["password"]
            f["password_source"] = r.get("source")
        elif r.get("needs_password") and not r.get("opened"):
            f["password_source"] = "none"

    if cr.get("parallel_files") and len(files) > 1:
        ts = [threading.Thread(target=do, args=(f,), daemon=True)
              for f in files]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
    else:
        for f in files:
            if stop():
                break
            do(f)


def _target_dir(path: str, dest_cfg: dict) -> str:
    if dest_cfg.get("dest") == "folder" and dest_cfg.get("folder"):
        return dest_cfg["folder"]
    return os.path.dirname(os.path.abspath(path))


# --------------------------------------------------------------------------- #
#  Run                                                                          #
# --------------------------------------------------------------------------- #
def run(project: dict, *, log=None, progress=None, stop=None,
        project_path=None) -> dict:
    """Execute the project. Returns ``{ok, fail, skip}`` counts."""
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

    # Optional password-recovery pre-pass (cracking).
    recovery_pass(project, stop=stop, log=log)

    # Build the image analyzer once (if AI image analysis is on).
    analyzer = None
    mcfg = project.get("modify_pdf", {})
    if "modify" in jobs and (mcfg.get("image_ai_analysis") or {}).get("enabled"):
        ai = mcfg.get("image_ai_analysis") or {}
        mid = ai.get("model") or "img-blip-base"
        user_model = (ai.get("user_model") or "").strip() or None
        try:
            analyzer = models.make_image_captioner(mid, user_model=user_model)
        except Exception:
            analyzer = None

    validate = mcfg.get("mode") == "validate"
    total = max(1, len(files) * max(1, len(jobs)))
    step = ok = fail = skip = 0
    csv_rows = {}   # output_folder -> [(file, open_pw, owner_pw, restricted)]

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
            log(f"  SKIP {name}: locked (no working password)")
            fentry["password_source"] = "none"
            skip += len(jobs); step += len(jobs); progress(step / total)
            continue
        working_pw = pres["password"] if pres["needs_password"] else None
        if pres["needs_password"]:
            fentry["password"] = working_pw
            if fentry.get("password_source") not in ("cracked",):
                fentry["password_source"] = "provided/pool"
            _record_password(working_pw)

        stem, ext = os.path.splitext(name)
        tmp = None
        try:
            work_path = path
            if pres["needs_password"]:
                tmp = pdf_info.make_decrypted_copy(path, working_pw)
                work_path = tmp

            for job in jobs:
                if stop():
                    break
                try:
                    _run_one(job, project, path, work_path, stem, ext,
                             validate, analyzer, log, csv_rows)
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

    _write_password_csvs(csv_rows, log)
    log(f"Done. {ok} succeeded, {fail} failed, {skip} skipped.")
    return {"ok": ok, "fail": fail, "skip": skip}


def _write_password_csvs(csv_rows, log):
    """One ``modified_passwords.csv`` per output folder (item 3.1)."""
    import csv
    for folder, rows in csv_rows.items():
        if not rows:
            continue
        path = os.path.join(folder, "modified_passwords.csv")
        try:
            exists = os.path.exists(path)
            with open(path, "a", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                if not exists:
                    w.writerow(["file", "open_password", "owner_password",
                                "restricted"])
                w.writerows(rows)
            log(f"  Wrote {os.path.basename(path)} ({len(rows)} entr"
                f"{'y' if len(rows) == 1 else 'ies'}) in {folder}")
        except Exception as exc:  # noqa: BLE001
            log(f"  WARN could not write password CSV in {folder}: {exc}")


def _run_one(job, project, src_path, work_path, stem, ext, validate, analyzer,
             log, csv_rows=None):
    name = os.path.basename(src_path)

    if job == "modify":
        mcfg = project.get("modify_pdf", {})
        ocfg = project.get("output", {}).get("modify", {})
        target = _target_dir(src_path, ocfg)
        os.makedirs(target, exist_ok=True)
        suffix = ocfg.get("suffix", "_noimg")
        out_path = os.path.join(target, f"{stem}{suffix}{ext}")
        if os.path.abspath(out_path) == os.path.abspath(src_path):
            out_path = os.path.join(target, f"{stem}_noimg{ext}")

        remove_images = mcfg.get("remove_images", True)
        # "Do nothing" (item 6): no removal and no other action → skip.
        if (not remove_images and analyzer is None
                and not pdf_modify.has_advanced_options(mcfg)):
            log(f"  {name}: Modify has no actions selected — skipped")
            return

        if pdf_modify.has_advanced_options(mcfg) or analyzer is not None:
            rep = pdf_modify.apply_modifications(
                work_path, None if validate else out_path,
                remove_images=mcfg.get("remove_images", True),
                remove_vector=mcfg.get("remove_vector", False),
                remove_restrictions=mcfg.get(
                    "remove_restrictions_and_password", False),
                text_replacements=mcfg.get("search_replace_text") or [],
                image_replacements=mcfg.get("search_replace_image") or [],
                image_analyzer=analyzer,
                process_pages=mcfg.get("page_range", "all"),
                keep_pages=mcfg.get("keep_pages", "all"),
                security=mcfg.get("security"), metadata=mcfg.get("metadata"),
                validate=validate, log=log)
            if rep.get("error"):
                raise RuntimeError(rep["error"])
            if validate:
                return
            # Record any new password for the per-folder CSV.
            if csv_rows is not None and (rep.get("set_password")
                                         or rep.get("owner_password")):
                csv_rows.setdefault(target, []).append(
                    [os.path.basename(out_path), rep.get("set_password") or "",
                     rep.get("owner_password") or "",
                     "yes" if rep.get("restricted") else "no"])
            sec = ""
            if rep.get("set_password") or rep.get("owner_password"):
                sec = " +password"
                if rep.get("restricted"):
                    sec += "/restrictions"
            log(f"  OK  {name} -> {os.path.basename(out_path)} "
                f"(imgs:{rep['images_removed']} text:{rep['text_replacements']} "
                f"imgreps:{rep['image_replacements']} pages:{rep['pages_kept']}"
                f"{sec})")
            return

        # Simple, well-tested image-removal path.
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

    # Apply a page range by converting a page-subset copy.
    page_range = dcfg.get("page_range", "all")
    conv_input = work_path
    sub_tmp = None
    if pdf_modify.is_page_subset(page_range):
        import tempfile
        fd, sub_tmp = tempfile.mkstemp(suffix=".pdf", prefix="paid_pages_")
        os.close(fd)
        pdf_modify.extract_pages(work_path, sub_tmp, page_range)
        conv_input = sub_tmp

    try:
        if job == "latex":
            tex = convert_pdf_to_latex(conv_input, target, math_mode=math_mode,
                                       name_prefix_len=plen,
                                       out_basename=out_basename)
            log(f"  OK  {name} -> {os.path.basename(tex)} (+ Latex_Resource)")
        elif job == "markdown":
            md = convert_pdf_to_markdown(conv_input, target, math_mode=math_mode,
                                         name_prefix_len=plen,
                                         out_basename=out_basename)
            log(f"  OK  {name} -> {os.path.basename(md)}")
    finally:
        if sub_tmp and os.path.exists(sub_tmp):
            try:
                os.remove(sub_tmp)
            except OSError:
                pass
