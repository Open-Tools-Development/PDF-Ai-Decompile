#!/usr/bin/env python3
"""
backend/pdf_info.py
===================
Headless PDF inspection, password handling and page rendering — the logic
behind the **Inspector** tab and the common **password** pre-processing step.
No UI imports, so it is safe to unit-test.

What it provides:
  * ``scan_pdf``          — size, page count, encryption, permissions, metadata.
  * ``try_passwords``     — find a working password from a list of candidates.
  * ``make_decrypted_copy``— write an unlocked temp copy so the other backends
                            (which open PDFs without a password) can process a
                            locked file; also the basis of "remove restrictions
                            & password" later.
  * ``render_page_png``   — render one page to PNG bytes for the preview.
"""

from __future__ import annotations

import os
import tempfile

import fitz  # PyMuPDF


# PDF permission bits (owner-password restrictions). True == allowed.
_PERM_BITS = [
    ("print",         getattr(fitz, "PDF_PERM_PRINT", 4)),
    ("modify",        getattr(fitz, "PDF_PERM_MODIFY", 8)),
    ("copy",          getattr(fitz, "PDF_PERM_COPY", 16)),
    ("annotate",      getattr(fitz, "PDF_PERM_ANNOTATE", 32)),
    ("fill_forms",    getattr(fitz, "PDF_PERM_FORM", 256)),
    ("accessibility", getattr(fitz, "PDF_PERM_ACCESSIBILITY", 512)),
    ("assemble",      getattr(fitz, "PDF_PERM_ASSEMBLE", 1024)),
    ("print_hq",      getattr(fitz, "PDF_PERM_PRINT_HQ", 2048)),
]


def human_size(num_bytes) -> str:
    if num_bytes is None:
        return "—"
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _permissions(doc) -> dict:
    try:
        bits = int(doc.permissions)
    except Exception:
        return {}
    return {name: bool(bits & bit) for name, bit in _PERM_BITS}


def _candidate_list(password):
    """Build a de-duplicated candidate list, always trying the empty password."""
    cands = []
    for c in ([password] if password is not None else []) + [""]:
        if c is not None and c not in cands:
            cands.append(c)
    return cands


def scan_pdf(path: str, password=None) -> dict:
    """Return a dict describing ``path`` (best-effort; never raises)."""
    info = {
        "path": path,
        "name": os.path.basename(path),
        "size_bytes": None,
        "size_human": "—",
        "encrypted": None,       # is the file encrypted at all?
        "needs_password": None,  # still locked after trying candidates?
        "opened": False,         # could we read it?
        "password_used": None,   # the candidate that worked (may be "")
        "page_count": None,
        "permissions": None,
        "metadata": None,
        "error": None,
    }
    try:
        info["size_bytes"] = os.path.getsize(path)
        info["size_human"] = human_size(info["size_bytes"])
    except Exception:
        pass

    try:
        doc = fitz.open(path)
    except Exception as exc:  # noqa: BLE001
        info["error"] = str(exc)
        return info

    try:
        info["encrypted"] = bool(doc.is_encrypted)
        # NOTE: in PyMuPDF >= ~1.27, doc.needs_pass stays truthy even after a
        # successful authenticate(); trust the authenticate() return value.
        required = bool(doc.needs_pass)
        opened = not required
        if required:
            for cand in _candidate_list(password):
                try:
                    if doc.authenticate(cand):
                        info["password_used"] = cand
                        opened = True
                        break
                except Exception:
                    pass
        info["needs_password"] = required
        info["opened"] = opened
        if opened:
            info["page_count"] = doc.page_count
            info["permissions"] = _permissions(doc)
            try:
                info["metadata"] = dict(doc.metadata or {})
            except Exception:
                info["metadata"] = None
    finally:
        doc.close()
    return info


def try_passwords(path: str, candidates) -> dict:
    """Try to open ``path`` with each candidate (empty password tried first).

    Returns ``{needs_password, password, opened, error}``. ``password`` is the
    working candidate (possibly ``""``) or ``None`` if none worked.
    """
    res = {"needs_password": False, "password": None, "opened": False,
           "error": None}
    try:
        doc = fitz.open(path)
    except Exception as exc:  # noqa: BLE001
        res["error"] = str(exc)
        return res
    try:
        if not doc.needs_pass:
            res["opened"] = True
            return res
        res["needs_password"] = True
        seen = []
        for cand in [""] + list(candidates or []):
            if cand is None or cand in seen:
                continue
            seen.append(cand)
            try:
                if doc.authenticate(cand):
                    res["password"] = cand
                    res["opened"] = True
                    break
            except Exception:
                pass
    finally:
        doc.close()
    return res


def make_decrypted_copy(path: str, password=None, out_path=None) -> str:
    """Write an unlocked copy of ``path`` and return its path.

    Used so backends that open PDFs without a password can still process a
    locked file. Raises ``ValueError`` if it cannot authenticate.
    """
    doc = fitz.open(path)
    try:
        if doc.needs_pass:
            ok = False
            for cand in _candidate_list(password):
                try:
                    if doc.authenticate(cand):
                        ok = True
                        break
                except Exception:
                    pass
            if not ok:   # needs_pass can stay truthy after success; trust `ok`
                raise ValueError("could not authenticate PDF with the "
                                 "given password")
        if out_path is None:
            fd, out_path = tempfile.mkstemp(suffix=".pdf",
                                            prefix="paid_unlocked_")
            os.close(fd)
        # Saving with no encryption drops the password and owner restrictions.
        doc.save(out_path, encryption=getattr(fitz, "PDF_ENCRYPT_NONE", 0),
                 garbage=3, deflate=True)
    finally:
        doc.close()
    return out_path


def render_page_png(path: str, page_index: int = 0, password=None,
                    zoom: float = 1.5) -> bytes:
    """Render one page to PNG bytes (for the Inspector preview)."""
    doc = fitz.open(path)
    try:
        if doc.needs_pass:
            authed = False
            for cand in _candidate_list(password):
                try:
                    if doc.authenticate(cand):
                        authed = True
                        break
                except Exception:
                    pass
            if not authed:   # needs_pass can stay truthy after success
                raise ValueError("PDF is locked; supply the password")
        page = doc[page_index]
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        return pix.tobytes("png")
    finally:
        doc.close()
