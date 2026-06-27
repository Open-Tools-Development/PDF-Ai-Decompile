#!/usr/bin/env python3
"""
backend/pdf_modify.py
=====================
The extended **Modify PDF** pipeline (v4.x). One entry point,
``apply_modifications``, performs any combination of:

  * remove images (raster, or images + vector figures) — reuses pdf_remove,
  * remove restrictions & password (saves an unencrypted copy),
  * search & replace text (literal or regular expression),
  * search & replace image (match an embedded image to a reference image by
    similarity %, then delete or replace it),
  * AI image analysis (caption each image in place via a pluggable analyzer),
  * restrict the operation to a **page range**, and choose which **pages to
    keep** in the output.

It can also run in **validate** mode: it computes what *would* change (counts +
image captions) without writing an output file — used by the Inspector and the
Modify "Validate" run mode.

Pure logic, no UI imports. Text/image replacement in PDFs is inherently
best-effort (a PDF is not a word processor); positions/fonts are approximated.
"""

from __future__ import annotations

import io
import os
import re
import secrets
import string

import fitz  # PyMuPDF

from .pdf_remove import _apply_redactions

# Permission name -> PyMuPDF bit (allowed when the bit is set).
PERM_BITS = {
    "print": getattr(fitz, "PDF_PERM_PRINT", 4),
    "modify": getattr(fitz, "PDF_PERM_MODIFY", 8),
    "copy": getattr(fitz, "PDF_PERM_COPY", 16),
    "annotate": getattr(fitz, "PDF_PERM_ANNOTATE", 32),
    "fill_forms": getattr(fitz, "PDF_PERM_FORM", 256),
    "accessibility": getattr(fitz, "PDF_PERM_ACCESSIBILITY", 512),
    "assemble": getattr(fitz, "PDF_PERM_ASSEMBLE", 1024),
    "print_hq": getattr(fitz, "PDF_PERM_PRINT_HQ", 2048),
}
_ALL_PERMS = sum(PERM_BITS.values())


def generate_password(length: int = 12) -> str:
    """A reasonably strong random password."""
    alphabet = string.ascii_letters + string.digits + "!@#$%*-_+="
    return "".join(secrets.choice(alphabet) for _ in range(max(4, length)))


def _permissions_int(allowed: dict) -> int:
    """Build a permission bitmask; a flag allowed unless explicitly False."""
    val = 0
    for name, bit in PERM_BITS.items():
        if allowed.get(name, True):
            val |= bit
    return val


def _resolve_security(security):
    """Resolve a security config into PyMuPDF save kwargs + an info dict.

    Returns ``(save_kwargs, info)`` where ``save_kwargs`` is empty (no
    encryption) or has ``encryption/user_pw/owner_pw/permissions``.
    """
    none = {"encryption": getattr(fitz, "PDF_ENCRYPT_NONE", 0)}
    if not security:
        return none, {}
    mode = security.get("set_user_password", "none")
    restrict = bool(security.get("restrict"))
    length = int(security.get("random_length", 12))

    user_pw = None
    if mode == "fixed":
        user_pw = security.get("user_password") or None
    elif mode == "random":
        user_pw = generate_password(length)

    if not user_pw and not restrict:
        return none, {}

    owner_pw = None
    perms = _ALL_PERMS
    if restrict:
        perms = _permissions_int(security.get("permissions", {}))
        owner_mode = security.get("owner_pw_mode", "random")
        if owner_mode == "fixed":
            owner_pw = security.get("owner_password") or generate_password(length)
        else:   # "random" or "auto" → a distinct random owner password
            owner_pw = generate_password(length)
    if not owner_pw:
        owner_pw = user_pw   # owner == user when only a user password is set

    save_kwargs = {
        "encryption": getattr(fitz, "PDF_ENCRYPT_AES_256", 0),
        "user_pw": user_pw or "",
        "owner_pw": owner_pw or "",
        "permissions": perms,
    }
    info = {"user_password": user_pw, "owner_password": owner_pw,
            "restricted": restrict, "permissions_int": perms}
    return save_kwargs, info


_META_KEYS = ("title", "author", "subject", "keywords", "creator", "producer")


def _apply_metadata(doc, metadata):
    """Set provided (non-empty) document properties. Returns the keys set."""
    if not metadata:
        return []
    current = dict(doc.metadata or {})
    changed = []
    for k in _META_KEYS:
        v = metadata.get(k)
        if v:
            current[k] = v
            changed.append(k)
    if changed:
        try:
            doc.set_metadata(current)
        except Exception:
            return []
    return changed


# --------------------------------------------------------------------------- #
#  Page ranges                                                                 #
# --------------------------------------------------------------------------- #
def parse_page_range(spec, page_count) -> list:
    """Parse a 1-based range spec like ``"1-3,5"`` into 0-based indices.

    ``"all"`` / ``""`` / ``"*"`` → every page. Out-of-range values are ignored.
    """
    if spec is None:
        return list(range(page_count))
    s = str(spec).strip().lower()
    if s in ("", "all", "*"):
        return list(range(page_count))
    out = set()
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            if "-" in part:
                a, b = part.split("-", 1)
                a, b = int(a), int(b)
                for n in range(min(a, b), max(a, b) + 1):
                    if 1 <= n <= page_count:
                        out.add(n - 1)
            else:
                n = int(part)
                if 1 <= n <= page_count:
                    out.add(n - 1)
        except ValueError:
            continue
    return sorted(out)


# --------------------------------------------------------------------------- #
#  Helpers                                                                     #
# --------------------------------------------------------------------------- #
def _authenticate(doc, password):
    if doc.needs_pass:
        for cand in ([password] if password is not None else []) + [""]:
            try:
                if cand is not None and doc.authenticate(cand):
                    return True
            except Exception:
                pass
        return False
    return True


def _image_png(doc, xref):
    """Return PNG bytes for an embedded image xref (or None)."""
    try:
        pix = fitz.Pixmap(doc, xref)
        if pix.n > 4:  # CMYK / alpha -> RGB
            pix = fitz.Pixmap(fitz.csRGB, pix)
        return pix.tobytes("png")
    except Exception:
        return None


def _similarity_pct(png_bytes, ref_path):
    """Rough 0..100 similarity between an image and a reference file."""
    try:
        from PIL import Image
        a = Image.open(io.BytesIO(png_bytes)).convert("L").resize((64, 64))
        b = Image.open(ref_path).convert("L").resize((64, 64))
        pa, pb = list(a.getdata()), list(b.getdata())
        diff = sum(abs(x - y) for x, y in zip(pa, pb)) / (len(pa) * 255.0)
        return (1.0 - diff) * 100.0
    except Exception:
        return 0.0


def _replace_text_on_page(page, replacements, log):
    """Redact matched text and write the replacement in its place. Returns count."""
    targets = []   # (rect, new_text)
    for rep in replacements:
        find = rep.get("find", "")
        repl = rep.get("replace", "")
        if not find:
            continue
        if rep.get("regex"):
            text = page.get_text("text")
            seen = set()
            for m in re.finditer(find, text):
                literal = m.group(0)
                if not literal or literal in seen:
                    continue
                seen.add(literal)
                new_text = re.sub(find, repl, literal)
                for rect in page.search_for(literal):
                    targets.append((rect, new_text))
        else:
            for rect in page.search_for(find):
                targets.append((rect, repl))
    if not targets:
        return 0
    for rect, new_text in targets:
        fontsize = max(6.0, min(rect.height * 0.8, 18.0))
        try:
            page.add_redact_annot(rect, text=new_text, fontsize=fontsize,
                                  fontname="helv", text_color=(0, 0, 0),
                                  fill=(1, 1, 1))
        except TypeError:
            page.add_redact_annot(rect)
    try:
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE,
                              graphics=fitz.PDF_REDACT_LINE_ART_NONE,
                              text=fitz.PDF_REDACT_TEXT_REMOVE)
    except (TypeError, AttributeError):
        page.apply_redactions()
    if log:
        log(f"      page {page.number + 1}: {len(targets)} text replacement(s)")
    return len(targets)


def _replace_images_on_page(doc, page, specs, log):
    """Match embedded images to reference images; delete or replace. Count."""
    actions = []   # (rect, action, replacement_path)
    for img in page.get_images(full=True):
        xref = img[0]
        png = _image_png(doc, xref)
        if png is None:
            continue
        for spec in specs:
            ref = spec.get("image")
            if not ref or not os.path.exists(ref):
                continue
            need = float(spec.get("match_pct", 90))
            if _similarity_pct(png, ref) >= need:
                for rect in page.get_image_rects(xref):
                    actions.append((rect, spec.get("action", "delete"),
                                    spec.get("replacement", "")))
                break
    if not actions:
        return 0
    for rect, _action, _rep in actions:
        page.add_redact_annot(rect)
    try:
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_REMOVE,
                              graphics=fitz.PDF_REDACT_LINE_ART_NONE,
                              text=fitz.PDF_REDACT_TEXT_NONE)
    except (TypeError, AttributeError):
        page.apply_redactions()
    for rect, action, rep in actions:
        if action == "replace" and rep and os.path.exists(rep):
            try:
                page.insert_image(rect, filename=rep)
            except Exception:
                pass
    if log:
        log(f"      page {page.number + 1}: {len(actions)} image "
            f"replacement(s)/removal(s)")
    return len(actions)


def _analyze_images_on_page(doc, page, analyzer, stamp, report, log):
    """Caption each image (in place) via ``analyzer(png_bytes) -> str``. Count."""
    n = 0
    for img in page.get_images(full=True):
        xref = img[0]
        png = _image_png(doc, xref)
        if png is None:
            continue
        try:
            caption = analyzer(png) if analyzer else f"image (xref {xref})"
        except Exception as exc:  # noqa: BLE001
            caption = f"(analysis failed: {exc})"
        rects = page.get_image_rects(xref)
        bbox = list(rects[0]) if rects else None
        report.append({"page": page.number + 1, "caption": caption,
                       "bbox": bbox})
        if stamp and rects:
            try:
                page.add_text_annot(rects[0].tl, caption)
            except Exception:
                pass
        n += 1
    if n and log:
        log(f"      page {page.number + 1}: analysed {n} image(s)")
    return n


def _remove_images_on_page(page, remove_vector):
    n_imgs = len(page.get_images(full=True))
    n_draws = len(page.get_drawings()) if remove_vector else 0
    if n_imgs == 0 and n_draws == 0:
        return 0
    try:
        page.add_redact_annot(page.rect, fill=False, cross_out=False)
    except TypeError:
        page.add_redact_annot(page.rect, fill=False)
    _apply_redactions(page, remove_vector)
    return n_imgs


# --------------------------------------------------------------------------- #
#  Main entry point                                                            #
# --------------------------------------------------------------------------- #
def apply_modifications(input_path, output_path=None, *, password=None,
                        remove_images=False, remove_vector=False,
                        remove_restrictions=False, text_replacements=None,
                        image_replacements=None, image_analyzer=None,
                        stamp_analysis=True, process_pages="all",
                        keep_pages="all", security=None, metadata=None,
                        validate=False, log=None) -> dict:
    """Apply the requested modifications and (unless ``validate``) save the PDF.

    Returns a report dict. ``image_analyzer`` is an optional callable
    ``png_bytes -> caption`` (see backend.models). The output is always written
    unencrypted (so a previously locked/restricted file becomes usable).
    """
    log = log or (lambda _m: None)
    text_replacements = text_replacements or []
    image_replacements = image_replacements or []

    doc = fitz.open(input_path)
    report = {
        "output": None, "validated": validate,
        "images_removed": 0, "text_replacements": 0,
        "image_replacements": 0, "image_analyses": [],
        "restrictions_removed": bool(remove_restrictions),
        "pages_processed": [], "pages_kept": None, "error": None,
        "set_password": None, "owner_password": None, "restricted": False,
        "metadata_set": [],
    }
    try:
        if not _authenticate(doc, password):
            report["error"] = "could not authenticate (wrong password)"
            return report

        page_count = doc.page_count
        proc = parse_page_range(process_pages, page_count)
        report["pages_processed"] = [i + 1 for i in proc]

        for i in proc:
            page = doc[i]
            if text_replacements:
                report["text_replacements"] += _replace_text_on_page(
                    page, text_replacements, log)
            if image_replacements:
                report["image_replacements"] += _replace_images_on_page(
                    doc, page, image_replacements, log)
            if image_analyzer is not None:
                _analyze_images_on_page(doc, page, image_analyzer,
                                        stamp_analysis and not validate,
                                        report["image_analyses"], log)
            if remove_images:
                report["images_removed"] += _remove_images_on_page(
                    page, remove_vector)

        keep = parse_page_range(keep_pages, page_count)
        if len(keep) != page_count and keep:
            doc.select(keep)
        report["pages_kept"] = doc.page_count

        save_kwargs, sec_info = _resolve_security(security)
        report["set_password"] = sec_info.get("user_password")
        report["owner_password"] = sec_info.get("owner_password")
        report["restricted"] = sec_info.get("restricted", False)

        if validate:
            extra = ""
            if sec_info:
                extra = (" + set "
                         + ("open password" if sec_info.get("user_password")
                            else "owner password")
                         + (" with restrictions" if sec_info.get("restricted")
                            else ""))
            log("  VALIDATE: "
                f"{report['images_removed']} image(s) would be removed, "
                f"{report['text_replacements']} text + "
                f"{report['image_replacements']} image replacement(s), "
                f"{len(report['image_analyses'])} image(s) analysed, "
                f"{report['pages_kept']} page(s) kept{extra}.")
            return report

        if output_path is None:
            raise ValueError("output_path required when not validating")
        out_parent = os.path.dirname(os.path.abspath(output_path))
        if out_parent:
            os.makedirs(out_parent, exist_ok=True)
        report["metadata_set"] = _apply_metadata(doc, metadata)
        # Default save is unencrypted (drops password + owner restrictions);
        # if a security config is given, the new password/restrictions apply.
        doc.save(output_path, garbage=4, deflate=True, clean=True,
                 **save_kwargs)
        report["output"] = output_path
        return report
    finally:
        doc.close()


def extract_pages(input_path, output_path, pages_spec):
    """Write a copy of ``input_path`` containing only ``pages_spec`` pages.

    Used to apply a page range to the Decompile category (the converters parse
    the whole document, so we feed them a page-subset PDF). ``input_path`` is
    assumed already unlocked. Returns ``output_path``.
    """
    doc = fitz.open(input_path)
    try:
        pages = parse_page_range(pages_spec, doc.page_count)
        if pages and len(pages) != doc.page_count:
            doc.select(pages)
        out_parent = os.path.dirname(os.path.abspath(output_path))
        if out_parent:
            os.makedirs(out_parent, exist_ok=True)
        doc.save(output_path, garbage=3, deflate=True)
    finally:
        doc.close()
    return output_path


def is_page_subset(pages_spec) -> bool:
    return str(pages_spec).strip().lower() not in ("", "all", "*")


def has_advanced_options(modify_cfg) -> bool:
    """True if the Modify config needs the extended pipeline (vs simple removal)."""
    sec = modify_cfg.get("security") or {}
    meta = modify_cfg.get("metadata") or {}
    return bool(
        modify_cfg.get("remove_restrictions_and_password")
        or modify_cfg.get("search_replace_text")
        or modify_cfg.get("search_replace_image")
        or (modify_cfg.get("image_ai_analysis") or {}).get("enabled")
        or (modify_cfg.get("page_range", "all") not in ("all", "", None))
        or (modify_cfg.get("keep_pages", "all") not in ("all", "", None))
        or sec.get("set_user_password", "none") != "none"
        or sec.get("restrict")
        or any(meta.get(k) for k in _META_KEYS)
    )
