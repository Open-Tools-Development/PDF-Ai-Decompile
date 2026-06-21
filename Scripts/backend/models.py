#!/usr/bin/env python3
"""
backend/models.py
=================
The optional **AI-model framework** (items 10, 11, 13, 14). Two model kinds,
behind small, uniform interfaces so the rest of the tool never hard-depends on
heavy ML packages:

  * **password** — a *candidate generator*: ``generate(hints) -> iterable[str]``.
    There is no real "PDF-password-cracking" model; what works is generating
    likely guesses. Two built-ins ship with the tool and need **no download or
    dependencies**: a character-level **Markov** model and a **rule mangler**,
    both trained on the user's sample passwords. Users can also add their own
    generator (a .py file exposing ``generate(hints)``) or, later, a downloaded
    model.

  * **image** — an *image captioner*: ``caption(png_bytes) -> str`` for the
    "analyse image before removing" feature. A real Hugging Face model (e.g.
    BLIP) is used if ``transformers``/``torch`` are installed and the weights are
    present; otherwise a dependency-free heuristic describes the image.

Delivery is **download-on-demand**: curated models in ``MANIFEST`` are fetched
into the project's assets/models folder only when first used (verified, optional),
so the installer stays small and the tool runs fully offline without them.

Pure logic, no UI imports. Heavy imports (transformers, huggingface_hub) are
lazy and guarded.
"""

from __future__ import annotations

import importlib.util
import io
import os
import random

from . import project as projmod

# --------------------------------------------------------------------------- #
#  Curated catalogue                                                           #
# --------------------------------------------------------------------------- #
MANIFEST = {
    "pw-markov-builtin": {
        "type": "password", "source": "builtin", "name": "Markov (built-in)",
        "desc": "Learns from your sample passwords and generates likely "
                "variants. No download or dependencies.",
    },
    "pw-rules-builtin": {
        "type": "password", "source": "builtin", "name": "Rule mangler (built-in)",
        "desc": "Common mangling rules (case, leet, digit/symbol suffixes) on "
                "your sample passwords. No download or dependencies.",
    },
    "img-blip-base": {
        "type": "image", "source": "hf",
        "repo": "Salesforce/blip-image-captioning-base",
        "name": "BLIP caption (base)",
        "desc": "Image captioning (~990 MB). Downloaded on demand; needs "
                "transformers + torch. Falls back to a heuristic if absent.",
    },
}

# A tiny seed list so the rule mangler is useful even with no user samples.
_COMMON_SEEDS = ["password", "admin", "1234", "12345", "qwerty", "letmein",
                 "welcome", "iloveyou", "monkey", "dragon", "abc123"]
_LEET = {"a": "4", "e": "3", "i": "1", "o": "0", "s": "5", "t": "7"}


def list_models(mtype=None) -> list:
    return [(mid, meta) for mid, meta in MANIFEST.items()
            if mtype is None or meta.get("type") == mtype]


def model_meta(model_id) -> dict:
    return MANIFEST.get(model_id, {})


def models_dir(project, project_path) -> str:
    """Per-project folder for downloaded model weights (item 14)."""
    assets = projmod.project_assets_path(project, project_path)
    rel = project.get("models", {}).get("dir", "models")
    path = os.path.normpath(os.path.join(assets, rel))
    return path


def is_available(model_id, project=None, project_path=None) -> bool:
    """True if the model can be used right now (built-ins always; downloaded
    HF weights if present, or if transformers can fetch them at runtime)."""
    meta = MANIFEST.get(model_id)
    if not meta:
        # User-supplied path?
        return os.path.exists(model_id)
    if meta["source"] == "builtin":
        return True
    if project is not None and project_path is not None:
        local = os.path.join(models_dir(project, project_path), model_id)
        if os.path.isdir(local) and os.listdir(local):
            return True
    return _transformers_available()


def _transformers_available() -> bool:
    return (importlib.util.find_spec("transformers") is not None
            and importlib.util.find_spec("torch") is not None)


def download_model(model_id, project, project_path, progress=None) -> str:
    """Fetch a curated HF model into the project's models folder. Returns path.

    Raises with a clear message if huggingface_hub is unavailable.
    """
    meta = MANIFEST.get(model_id)
    if not meta:
        raise ValueError(f"unknown model id: {model_id}")
    if meta["source"] == "builtin":
        return ""   # nothing to download
    try:
        from huggingface_hub import snapshot_download
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "Downloading models needs the 'huggingface_hub' package "
            "(pip install huggingface_hub). " + str(exc))
    dest = os.path.join(models_dir(project, project_path), model_id)
    os.makedirs(dest, exist_ok=True)
    if progress:
        progress(f"Downloading {meta['repo']} → {dest} …")
    snapshot_download(repo_id=meta["repo"], local_dir=dest,
                      local_dir_use_symlinks=False)
    # Record it in the project so it is remembered (item 14).
    installed = project.setdefault("models", {}).setdefault("installed", [])
    if not any(m.get("id") == model_id for m in installed):
        installed.append({"id": model_id, "type": meta["type"],
                          "source": "hf", "path": dest})
    return dest


# --------------------------------------------------------------------------- #
#  Password candidate generators                                               #
# --------------------------------------------------------------------------- #
def _rule_variants(samples, limit):
    suffixes = ["", "1", "12", "123", "1234", "!", "@", "01", "2023", "2024",
                "2025", "00", "99", "#"]
    out = []
    seen = set()

    def emit(s):
        if s and s not in seen:
            seen.add(s)
            out.append(s)

    for base in (samples or _COMMON_SEEDS):
        forms = {base, base.lower(), base.upper(), base.capitalize()}
        leet = "".join(_LEET.get(c.lower(), c) for c in base)
        forms.add(leet)
        for f in list(forms):
            for suf in suffixes:
                emit(f + suf)
                if len(out) >= limit:
                    return out
    return out


def _markov_generate(samples, count, min_len, max_len):
    """Order-2 character Markov model trained on samples; yields candidates."""
    if not samples:
        return []
    model = {}
    starts = []
    for s in samples:
        if not s:
            continue
        starts.append(s[:2] if len(s) >= 2 else s + "\n")
        padded = s + "\n"
        for i in range(len(padded) - 2):
            key = padded[i:i + 2]
            model.setdefault(key, []).append(padded[i + 2])
    if not model:
        return []
    rng = random.Random(1234)
    out, seen = [], set()
    attempts = 0
    while len(out) < count and attempts < count * 20:
        attempts += 1
        cur = rng.choice(starts)
        s = cur
        while len(s) < max_len:
            nxts = model.get(s[-2:])
            if not nxts:
                break
            nc = rng.choice(nxts)
            if nc == "\n":
                break
            s += nc
        if min_len <= len(s) <= max_len and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def make_password_generator(model_id, hints):
    """Return an iterable of candidate passwords for ``model_id`` given hints.

    ``hints``: ``{samples, min_len, max_len, count}``.
    """
    samples = list(hints.get("samples") or [])
    min_len = int(hints.get("min_len", 1))
    max_len = int(hints.get("max_len", 16))
    count = int(hints.get("count", 5000))

    meta = MANIFEST.get(model_id)
    if model_id == "pw-markov-builtin":
        return _markov_generate(samples, count, min_len, max_len)
    if model_id == "pw-rules-builtin":
        return _rule_variants(samples, count)
    # A user-supplied generator: a .py file exposing generate(hints).
    if meta is None and os.path.exists(model_id) and model_id.endswith(".py"):
        gen = _load_user_module(model_id)
        if gen and hasattr(gen, "generate"):
            try:
                return list(gen.generate(hints))
            except Exception:
                return []
    return []


def _load_user_module(path):
    try:
        spec = importlib.util.spec_from_file_location("user_pw_model", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


# --------------------------------------------------------------------------- #
#  Image captioner                                                             #
# --------------------------------------------------------------------------- #
def make_image_captioner(model_id="img-blip-base", project=None,
                         project_path=None, user_model=None):
    """Return ``caption(png_bytes) -> str``. Uses a real model if available,
    else a dependency-free heuristic. ``user_model`` (a local HF model dir or a
    Hugging Face repo id) overrides ``model_id`` when given."""
    real = None
    if _transformers_available():
        real = _try_load_blip(user_model or model_id, project, project_path)

    def caption(png_bytes):
        if real is not None:
            try:
                return real(png_bytes)
            except Exception:
                pass
        return _heuristic_caption(png_bytes)

    return caption


def _try_load_blip(model_id, project, project_path):
    try:
        from transformers import (BlipProcessor,
                                  BlipForConditionalGeneration)
        from PIL import Image
        meta = MANIFEST.get(model_id, {})
        if meta:
            src = meta.get("repo", "Salesforce/blip-image-captioning-base")
                local = os.path.join(models_dir(project, project_path), model_id)
                if os.path.isdir(local) and os.listdir(local):
                    src = local
        else:
            # A user-supplied local dir or Hugging Face repo id.
            src = model_id
        processor = BlipProcessor.from_pretrained(src)
        model = BlipForConditionalGeneration.from_pretrained(src)

        def run(png_bytes):
            img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
            inputs = processor(img, return_tensors="pt")
            out = model.generate(**inputs, max_new_tokens=30)
            return processor.decode(out[0], skip_special_tokens=True)
        return run
    except Exception:
        return None


def _heuristic_caption(png_bytes):
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
        w, h = img.size
        small = img.resize((1, 1))
        r, g, b = small.getpixel((0, 0))
        color = _color_name(r, g, b)
        shape = ("wide" if w > h * 1.3 else "tall" if h > w * 1.3 else "square")
        return (f"[no caption model] {w}×{h} {shape} image, "
                f"mostly {color}")
    except Exception:
        return "[no caption model] image"


def _color_name(r, g, b):
    if max(r, g, b) - min(r, g, b) < 24:
        if r > 200:
            return "white/light"
        if r < 60:
            return "black/dark"
        return "grey"
    if r >= g and r >= b:
        return "red/warm"
    if g >= r and g >= b:
        return "green"
    return "blue/cool"
