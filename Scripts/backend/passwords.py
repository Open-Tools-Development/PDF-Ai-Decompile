#!/usr/bin/env python3
"""
backend/passwords.py
====================
Password discovery for protected PDFs — the engine behind the **Passwords** tab
(item 10). Two layers:

  * **Verification / brute force** — test candidate passwords against a PDF.
    Candidates come from (a) a caller-supplied list (per-file value, the project
    pool, the hidden reuse pool, and any model-generated guesses), then (b) a
    brute-force stream built from a charset+length or a mask pattern. Testing is
    multi-threaded; limits can be by attempts, by time, or unbounded.

  * **Hidden reuse pool** — every password the tool confirms or the user supplies
    is stored, de-duplicated, in a hidden, encrypted file in the per-user config
    folder. When cracking is enabled it is tried first next time. The encryption
    is a self-contained, dependency-free authenticated stream cipher
    (SHA-256 keystream + HMAC); it is obfuscation-grade for a *local* file, not a
    vault for high-value secrets.

Responsible use: only recover passwords for PDFs you are authorised to open.

Pure logic, no UI imports.
"""

from __future__ import annotations

import hashlib
import hmac
import itertools
import os
import string
import threading
import time

import fitz  # PyMuPDF

from . import appconfig

# --------------------------------------------------------------------------- #
#  Charsets and masks                                                          #
# --------------------------------------------------------------------------- #
_SYMBOLS = "!@#$%^&*()-_=+[]{};:,.<>?/"
CHARSET_PRESETS = {
    "digits": string.digits,
    "lower": string.ascii_lowercase,
    "upper": string.ascii_uppercase,
    "letters": string.ascii_letters,
    "lower+digits": string.ascii_lowercase + string.digits,
    "alnum": string.ascii_letters + string.digits,
    "all": string.ascii_letters + string.digits + _SYMBOLS,
}
# Mask tokens: ?d digit, ?l lower, ?u upper, ?s symbol, ?a alnum. Other chars
# are literal. Use ?? for a literal '?'.
_MASK_SETS = {
    "d": string.digits,
    "l": string.ascii_lowercase,
    "u": string.ascii_uppercase,
    "s": _SYMBOLS,
    "a": string.ascii_letters + string.digits,
    "?": "?",
}


def resolve_charset(spec: str) -> str:
    """A preset name, or the literal characters themselves."""
    if not spec:
        return CHARSET_PRESETS["lower+digits"]
    return CHARSET_PRESETS.get(spec, spec)


def mask_candidates(pattern: str):
    """Yield every string matching a mask like ``v?d?d`` (v + two digits)."""
    sets = []
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "?" and i + 1 < len(pattern):
            tok = pattern[i + 1]
            sets.append(_MASK_SETS.get(tok, tok))
            i += 2
        else:
            sets.append(ch)   # literal single character
            i += 1
    for combo in itertools.product(*sets):
        yield "".join(combo)


def length_candidates(charset: str, min_len: int, max_len: int):
    """Yield every string over ``charset`` with length in [min_len, max_len]."""
    chars = list(dict.fromkeys(charset))   # de-dup, keep order
    for n in range(max(1, min_len), max(min_len, max_len) + 1):
        for combo in itertools.product(chars, repeat=n):
            yield "".join(combo)


def brute_force_stream(config: dict):
    """Build the brute-force candidate stream from a cracking config dict."""
    if (config or {}).get("skip_bruteforce"):
        return   # model-only mode: candidates come from extra_candidates only
    pattern = (config or {}).get("pattern", "")
    if pattern:
        yield from mask_candidates(pattern)
        return
    charset = resolve_charset((config or {}).get("charset", "lower+digits"))
    yield from length_candidates(charset,
                                 int((config or {}).get("min_len", 1)),
                                 int((config or {}).get("max_len", 4)))


# --------------------------------------------------------------------------- #
#  Cracking a single file                                                      #
# --------------------------------------------------------------------------- #
def crack_file(path: str, *, config=None, extra_candidates=(), stop=None,
               on_progress=None) -> dict:
    """Find a working password for ``path``.

    Tries ``extra_candidates`` first (pool / hidden pool / model guesses), then
    the brute-force stream. Returns
    ``{found, password, attempts, elapsed, reason}``.
    """
    config = config or {}
    stop = stop or (lambda: False)
    threads = max(1, int(config.get("threads", 4)))
    limit_type = config.get("limit_type", "attempts")
    limit_value = int(config.get("limit_value", 1_000_000))

    # If the file isn't actually locked, we're done immediately.
    try:
        probe = fitz.open(path)
        if not probe.needs_pass:
            probe.close()
            return {"found": True, "password": None, "attempts": 0,
                    "elapsed": 0.0, "reason": "not-encrypted"}
        probe.close()
    except Exception as exc:  # noqa: BLE001
        return {"found": False, "password": None, "attempts": 0,
                "elapsed": 0.0, "reason": f"open-error: {exc}"}

    def candidate_gen():
        seen = set()
        for c in extra_candidates:
            if c is None or c in seen:
                continue
            seen.add(c)
            yield c
        for c in brute_force_stream(config):
            yield c

    it = candidate_gen()
    lock = threading.Lock()
    found_evt = threading.Event()
    exhausted_evt = threading.Event()
    state = {"password": None, "attempts": 0}
    start = time.time()

    def limit_reached():
        if found_evt.is_set() or exhausted_evt.is_set() or stop():
            return True
        if limit_type == "attempts" and state["attempts"] >= limit_value:
            return True
        if limit_type == "time" and (time.time() - start) >= limit_value:
            return True
        return False

    def worker():
        try:
            doc = fitz.open(path)
        except Exception:
            return
        try:
            while not limit_reached():
                with lock:
                    if found_evt.is_set() or exhausted_evt.is_set():
                        break
                    try:
                        cand = next(it)
                    except StopIteration:
                        exhausted_evt.set()
                        break
                    state["attempts"] += 1
                    att = state["attempts"]
                try:
                    if doc.authenticate(cand):
                        with lock:
                            state["password"] = cand
                        found_evt.set()
                        break
                except Exception:
                    pass
                if on_progress and att % 500 == 0:
                    on_progress(att)
        finally:
            doc.close()

    ts = [threading.Thread(target=worker, daemon=True) for _ in range(threads)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()

    elapsed = time.time() - start
    if found_evt.is_set():
        reason = "found"
    elif stop():
        reason = "stopped"
    elif exhausted_evt.is_set():
        reason = "exhausted"
    else:
        reason = f"limit-{limit_type}"
    return {"found": found_evt.is_set(), "password": state["password"],
            "attempts": state["attempts"], "elapsed": elapsed, "reason": reason}


# --------------------------------------------------------------------------- #
#  Hidden, encrypted reuse pool                                                #
# --------------------------------------------------------------------------- #
_MAGIC = b"PAIDPOOL1"


def _key_path() -> str:
    return os.path.join(appconfig.user_config_dir(), ".poolkey")


def _get_key() -> bytes:
    path = _key_path()
    if os.path.exists(path):
        try:
            with open(path, "rb") as fh:
                k = fh.read()
            if len(k) >= 32:
                return k[:32]
        except Exception:
            pass
    key = os.urandom(32)
    try:
        with open(path, "wb") as fh:
            fh.write(key)
        if hasattr(os, "chmod"):
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
    except Exception:
        pass
    return key


def _keystream_xor(data: bytes, key: bytes, nonce: bytes) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < len(data):
        block = hashlib.sha256(key + nonce + counter.to_bytes(8, "big")).digest()
        out.extend(block)
        counter += 1
    return bytes(b ^ k for b, k in zip(data, out))


def _encrypt(data: bytes, key: bytes) -> bytes:
    nonce = os.urandom(16)
    ct = _keystream_xor(data, key, nonce)
    tag = hmac.new(key, nonce + ct, hashlib.sha256).digest()
    return _MAGIC + nonce + tag + ct


def _decrypt(blob: bytes, key: bytes) -> bytes:
    if blob[:len(_MAGIC)] != _MAGIC:
        raise ValueError("bad pool file")
    off = len(_MAGIC)
    nonce = blob[off:off + 16]
    tag = blob[off + 16:off + 48]
    ct = blob[off + 48:]
    if not hmac.compare_digest(tag, hmac.new(key, nonce + ct,
                                             hashlib.sha256).digest()):
        raise ValueError("pool integrity check failed")
    return _keystream_xor(ct, key, nonce)


def load_hidden_pool() -> list:
    """Return the de-duplicated list of stored passwords (newest last)."""
    path = appconfig.password_pool_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, "rb") as fh:
            blob = fh.read()
        text = _decrypt(blob, _get_key()).decode("utf-8")
        return [ln for ln in text.split("\n") if ln != ""]
    except Exception:
        return []


def add_to_hidden_pool(passwords) -> int:
    """Add passwords (de-duplicated) to the hidden pool. Returns how many added."""
    existing = load_hidden_pool()
    have = set(existing)
    added = []
    for p in passwords:
        if p and p not in have:
            have.add(p)
            added.append(p)
    if not added:
        return 0
    merged = existing + added
    blob = _encrypt("\n".join(merged).encode("utf-8"), _get_key())
    path = appconfig.password_pool_path()
    tmp = path + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(blob)
    os.replace(tmp, path)
    if hasattr(os, "chmod"):
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    return len(added)
