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
import json
import os
import platform
import random
import sys

from . import appconfig

# --------------------------------------------------------------------------- #
#  Categories (item 6.1 / 6.5) — one per "atomic activity" the tool needs      #
# --------------------------------------------------------------------------- #
CATEGORIES = {
    "password": {
        "name": "Password candidate generator",
        "summary": "Generates likely password guesses from your hints; the "
                   "cracking engine then tests each against the PDF. (No model "
                   "truly 'cracks' a PDF — it only proposes candidates.)",
        "io": "Input: hints {samples, min_len, max_len, count}. "
              "Output: an iterable of candidate password strings.",
        "user_contract": "A Python .py file exposing `generate(hints) -> "
                         "iterable[str]`.",
        "changeable": False,
    },
    "image": {
        "name": "Image description (captioning)",
        "summary": "Describes what an image contains in plain text so you can "
                   "decide whether to remove or replace it. Reusable later in "
                   "Decompile to Text.",
        "io": "Input: image bytes (PNG). Output: a short text caption.",
        "user_contract": "A local Hugging Face model folder, or a HF repo id, "
                         "loadable by transformers for image-to-text.",
        "changeable": False,
    },
}

# --------------------------------------------------------------------------- #
#  Curated catalogue                                                           #
# --------------------------------------------------------------------------- #
MANIFEST = {
    "pw-markov-builtin": {
        "type": "password", "source": "builtin", "name": "Markov (built-in)",
        "desc": "Learns from your sample passwords and generates likely "
                "variants. No download or dependencies.",
        "size_mb": 0, "requirements": [], "min_ram_gb": 0,
    },
    "pw-rules-builtin": {
        "type": "password", "source": "builtin", "name": "Rule mangler (built-in)",
        "desc": "Common mangling rules (case, leet, digit/symbol suffixes) on "
                "your sample passwords. No download or dependencies.",
        "size_mb": 0, "requirements": [], "min_ram_gb": 0,
    },
    "img-blip-base": {
        "type": "image", "source": "hf",
        "repo": "Salesforce/blip-image-captioning-base",
        "url": "https://huggingface.co/Salesforce/blip-image-captioning-base",
        "name": "BLIP caption (base)",
        "desc": "Image captioning. Downloaded on demand; needs "
                "transformers + torch. Falls back to a heuristic if absent.",
        "size_mb": 990, "requirements": ["transformers", "torch"],
        "min_ram_gb": 4,
    },
    "img-blip-large": {
        "type": "image", "source": "hf",
        "repo": "Salesforce/blip-image-captioning-large",
        "url": "https://huggingface.co/Salesforce/blip-image-captioning-large",
        "name": "BLIP caption (large)",
        "desc": "Higher-quality captioning; larger. Needs transformers + torch.",
        "size_mb": 1880, "requirements": ["transformers", "torch"],
        "min_ram_gb": 8,
    },
}

# A few open sources users can browse for more models (item 6.6 / 6.7).
MODEL_SOURCES = [
    ("Hugging Face", "https://huggingface.co/models"),
    ("Hugging Face — image-to-text",
     "https://huggingface.co/models?pipeline_tag=image-to-text"),
]

# A tiny seed list so the rule mangler is useful even with no user samples.
_COMMON_SEEDS = ["password", "admin", "1234", "12345", "qwerty", "letmein",
                 "welcome", "iloveyou", "monkey", "dragon", "abc123"]
_LEET = {"a": "4", "e": "3", "i": "1", "o": "0", "s": "5", "t": "7"}


# --------------------------------------------------------------------------- #
#  Catalogue access                                                            #
# --------------------------------------------------------------------------- #
def category_meta(category) -> dict:
    return CATEGORIES.get(category, {})


def list_models(mtype=None) -> list:
    """Curated models (built-in + downloadable) for a category, or all."""
    return [(mid, meta) for mid, meta in MANIFEST.items()
            if mtype is None or meta.get("type") == mtype]


def model_meta(model_id) -> dict:
    return MANIFEST.get(model_id, {})


def _transformers_available() -> bool:
    return (importlib.util.find_spec("transformers") is not None
            and importlib.util.find_spec("torch") is not None)


def huggingface_hub_available() -> bool:
    return importlib.util.find_spec("huggingface_hub") is not None


# --------------------------------------------------------------------------- #
#  Storage: a shared root, one folder + model.json per model (item 6.2.1)      #
# --------------------------------------------------------------------------- #
def models_root() -> str:
    return appconfig.models_root()


def model_folder(model_id, root=None) -> str:
    return os.path.join(root or models_root(), _safe(model_id))


def _safe(name):
    return "".join(c if (c.isalnum() or c in "-_.") else "_" for c in str(name))


def is_builtin(model_id) -> bool:
    return MANIFEST.get(model_id, {}).get("source") == "builtin"


def is_installed(model_id, root=None) -> bool:
    folder = model_folder(model_id, root)
    return os.path.isdir(folder) and bool(os.listdir(folder))


def install_status(model_id, root=None) -> str:
    """'built-in' | 'installed' | 'needs-deps' | 'available'."""
    if is_builtin(model_id):
        return "built-in"
    if is_installed(model_id, root):
        return "installed"
    meta = MANIFEST.get(model_id, {})
    if meta.get("requirements") and not all(
            importlib.util.find_spec(r) for r in meta["requirements"]):
        return "needs-deps"
    return "available"


def download_model(model_id, progress=None, root=None) -> str:
    """Fetch a curated HF model into its own folder; write model.json. Returns
    the folder. Raises with a clear message if huggingface_hub is missing."""
    meta = MANIFEST.get(model_id)
    if not meta:
        raise ValueError(f"unknown model id: {model_id}")
    if meta["source"] == "builtin":
        return ""
    try:
        from huggingface_hub import snapshot_download
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "Downloading models needs the 'huggingface_hub' package. Install "
            "it with:  pip install huggingface_hub  (" + str(exc) + ")")
    dest = model_folder(model_id, root)
    os.makedirs(dest, exist_ok=True)
    if progress:
        progress(f"Downloading {meta['repo']} → {dest} …")
    snapshot_download(repo_id=meta["repo"], local_dir=dest,
                      local_dir_use_symlinks=False)
    _write_model_config(dest, {"id": model_id, "type": meta["type"],
                               "source": "hf", "repo": meta.get("repo"),
                               "name": meta.get("name")})
    if progress:
        progress(f"Downloaded {model_id}.")
    return dest


def _write_model_config(folder, cfg):
    try:
        with open(os.path.join(folder, "model.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2)
    except Exception:
        pass


# --------------------------------------------------------------------------- #
#  User-supplied models (item 6.4)                                             #
# --------------------------------------------------------------------------- #
def _user_models_path(root=None) -> str:
    return os.path.join(root or models_root(), "user_models.json")


def list_user_models(category=None, root=None) -> list:
    try:
        with open(_user_models_path(root), encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        data = []
    return [m for m in data
            if category is None or m.get("category") == category]


def register_user_model(category, name, source, root=None) -> dict:
    """Register a user's own model. ``source`` is a .py path (password) or a
    folder/HF id (image)."""
    data = list_user_models(root=root)
    entry = {"id": "user-" + _safe(name or os.path.basename(str(source))),
             "category": category, "name": name or source, "source": "user",
             "path": source}
    data = [m for m in data if m.get("id") != entry["id"]]
    data.append(entry)
    try:
        with open(_user_models_path(root), "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
    except Exception:
        pass
    return entry


def import_hf_model(repo, category, progress=None, root=None) -> dict:
    """Download any Hugging Face repo into the models root and register it as a
    user model in ``category`` (item 6.6)."""
    try:
        from huggingface_hub import snapshot_download
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "Importing needs the 'huggingface_hub' package. Install it with:  "
            "pip install huggingface_hub  (" + str(exc) + ")")
    dest = os.path.join(root or models_root(), _safe(repo))
    os.makedirs(dest, exist_ok=True)
    if progress:
        progress(f"Downloading {repo} → {dest} …")
    snapshot_download(repo_id=repo, local_dir=dest,
                      local_dir_use_symlinks=False)
    _write_model_config(dest, {"id": "user-" + _safe(repo), "type": category,
                               "source": "hf-import", "repo": repo})
    if progress:
        progress(f"Imported {repo}.")
    return register_user_model(category, repo, dest, root=root)


def remove_user_model(model_id, root=None):
    data = [m for m in list_user_models(root=root) if m.get("id") != model_id]
    try:
        with open(_user_models_path(root), "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
    except Exception:
        pass


def resolve_model_source(model_id, root=None):
    """Map a model id (curated or user) to a usable source path/repo id."""
    for m in list_user_models(root=root):
        if m.get("id") == model_id:
            return m.get("path")
    if is_installed(model_id, root):
        return model_folder(model_id, root)
    meta = MANIFEST.get(model_id, {})
    return meta.get("repo") or model_id


# --------------------------------------------------------------------------- #
#  Hardware detection + applicability (item 6.7)                               #
# --------------------------------------------------------------------------- #
def hardware_info() -> dict:
    info = {"cpu_count": os.cpu_count() or 1, "ram_gb": None, "gpu": False,
            "gpu_name": "", "platform": platform.platform()}
    try:
        if sys.platform.startswith("win"):
            import ctypes

            class _MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong),
                            ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            st = _MS(); st.dwLength = ctypes.sizeof(st)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
            info["ram_gb"] = round(st.ullTotalPhys / (1024 ** 3), 1)
        else:
            info["ram_gb"] = round(
                os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
                / (1024 ** 3), 1)
    except Exception:
        pass
    try:
        if importlib.util.find_spec("torch"):
            import torch
            if torch.cuda.is_available():
                info["gpu"] = True
                info["gpu_name"] = torch.cuda.get_device_name(0)
    except Exception:
        pass
    return info


def applicable(model_id_or_meta, hw=None) -> tuple:
    """Return (ok, [reasons]) whether a model is recommended for this PC."""
    meta = (model_id_or_meta if isinstance(model_id_or_meta, dict)
            else MANIFEST.get(model_id_or_meta, {}))
    hw = hw if hw is not None else hardware_info()
    reasons = []
    for req in meta.get("requirements", []):
        if not importlib.util.find_spec(req):
            reasons.append(f"needs '{req}' (pip install {req})")
    min_ram = meta.get("min_ram_gb")
    if min_ram and hw.get("ram_gb") and hw["ram_gb"] < min_ram:
        reasons.append(f"needs ~{min_ram} GB RAM (you have {hw['ram_gb']})")
    return (not reasons, reasons)


# --------------------------------------------------------------------------- #
#  Basic self-test (items 6.3 / 6.4)                                           #
# --------------------------------------------------------------------------- #
def self_test(model_id, category=None, source=None) -> tuple:
    """Run a minimal test for a model. Returns (ok, message)."""
    category = category or MANIFEST.get(model_id, {}).get("type")
    try:
        if category == "password":
            gen = make_password_generator(
                source or model_id,
                {"samples": ["Spring2024", "letmein"], "min_len": 1,
                 "max_len": 16, "count": 5})
            cands = list(gen)[:5]
            if cands:
                return True, "Generated: " + ", ".join(cands)
            return False, "No candidates were generated."
        if category == "image":
            cap = make_image_captioner(model_id, user_model=source)
            from PIL import Image
            buf = io.BytesIO()
            Image.new("RGB", (96, 64), (60, 120, 200)).save(buf, "PNG")
            return True, "Caption: " + cap(buf.getvalue())
        return False, f"Unknown category: {category}"
    except Exception as exc:  # noqa: BLE001
        return False, f"Test failed: {exc}"


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

    if model_id == "pw-markov-builtin":
        return _markov_generate(samples, count, min_len, max_len)
    if model_id == "pw-rules-builtin":
        return _rule_variants(samples, count)
    # A registered user model id, or a direct .py path exposing generate(hints).
    source = model_id
    if model_id not in MANIFEST:
        source = resolve_model_source(model_id) or model_id
    if isinstance(source, str) and source.endswith(".py") \
            and os.path.exists(source):
        gen = _load_user_module(source)
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
def make_image_captioner(model_id="img-blip-base", user_model=None):
    """Return ``caption(png_bytes) -> str``. Uses a real model if available,
    else a dependency-free heuristic. ``user_model`` (a local HF model dir or a
    Hugging Face repo id) overrides ``model_id`` when given."""
    real = None
    if _transformers_available():
        real = _try_load_blip(user_model or model_id)

    def caption(png_bytes):
        if real is not None:
            try:
                return real(png_bytes)
            except Exception:
                pass
        return _heuristic_caption(png_bytes)

    return caption


def _try_load_blip(model_id):
    try:
        from transformers import (BlipProcessor,
                                  BlipForConditionalGeneration)
        from PIL import Image
        meta = MANIFEST.get(model_id, {})
        if meta:
            # Prefer a downloaded local copy, else the HF repo id.
            src = meta.get("repo", "Salesforce/blip-image-captioning-base")
            if is_installed(model_id):
                src = model_folder(model_id)
        else:
            # A registered user model, a local dir, or a Hugging Face repo id.
            src = resolve_model_source(model_id) or model_id
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
