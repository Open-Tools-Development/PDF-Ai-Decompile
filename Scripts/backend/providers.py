#!/usr/bin/env python3
"""
backend/providers.py
====================
LLM **provider connections** (items 11, 12, 13) — connect the tool to local LLM
servers (Ollama, LM Studio, Jan, GPT4All, LocalAI, vLLM, LMDeploy …) and cloud
platforms (Anthropic / Claude, OpenAI / ChatGPT), then use them as AI "models"
for a category (image description, password candidates).

Design
------
* Most local tools and cloud platforms speak the **OpenAI-compatible** HTTP API
  (`/v1/chat/completions`, `/v1/models`) — one client covers them. Ollama also
  has a native API (`/api/chat`, `/api/tags`). Anthropic has its own API; we
  prefer the official ``anthropic`` SDK when installed, else raw HTTP.
* Two instruction layers per category (item 11): a **fixed** category
  instruction (`CATEGORY_LLM_INSTRUCTIONS`, unchangeable) that defines the
  task + output format, and an **optional user instruction** appended after it.
* Provider configs (including API keys) are stored **encrypted** in the per-user
  config folder (reuses the password-pool cipher).

No UI imports. HTTP uses the stdlib (urllib); the ``anthropic`` SDK is optional.
"""

from __future__ import annotations

import base64
import json
import os
import urllib.request

from . import appconfig
from .passwords import _decrypt, _encrypt, _get_key

# --------------------------------------------------------------------------- #
#  Provider catalogue                                                          #
# --------------------------------------------------------------------------- #
PROVIDER_TYPES = {
    "anthropic": {
        "name": "Anthropic (Claude)", "kind": "cloud", "api": "anthropic",
        "base_url": "https://api.anthropic.com", "needs_key": True,
        "default_model": "claude-opus-4-8",
        "help": "Cloud. Needs an Anthropic API key. Vision-capable.",
    },
    "openai": {
        "name": "OpenAI (ChatGPT)", "kind": "cloud", "api": "openai",
        "base_url": "https://api.openai.com/v1", "needs_key": True,
        "default_model": "gpt-4o-mini",
        "help": "Cloud. Needs an OpenAI API key. Vision via gpt-4o models.",
    },
    "ollama": {
        "name": "Ollama (local)", "kind": "local", "api": "ollama",
        "base_url": "http://localhost:11434", "needs_key": False,
        "default_model": "llama3.2",
        "help": "Local server. Run `ollama serve`. Vision via llava models.",
    },
    "openai_compatible": {
        "name": "OpenAI-compatible server", "kind": "local", "api": "openai",
        "base_url": "http://localhost:8000/v1", "needs_key": False,
        "default_model": "",
        "help": "Local OpenAI-compatible server: vLLM, LocalAI, LM Studio, "
                "Jan, GPT4All, LMDeploy, … Set the base URL + model.",
    },
}

# Common local servers probed by autodetect (name, base_url, list-path, api).
_LOCAL_PROBES = [
    ("Ollama", "http://localhost:11434", "/api/tags", "ollama"),
    ("LM Studio", "http://localhost:1234/v1", "/models", "openai"),
    ("Jan", "http://localhost:1337/v1", "/models", "openai"),
    ("GPT4All", "http://localhost:4891/v1", "/models", "openai"),
    ("LocalAI", "http://localhost:8080/v1", "/models", "openai"),
    ("vLLM", "http://localhost:8000/v1", "/models", "openai"),
]

# Fixed, per-category instruction (item 11.1) — not user-changeable.
CATEGORY_LLM_INSTRUCTIONS = {
    "image": ("You analyse an image taken from a PDF. Reply with ONE concise "
              "sentence (max 25 words) describing what the image shows. Output "
              "only the description — no preamble, no markdown."),
    "password": ("You generate likely password candidates from the given hints "
                 "(sample passwords, length, character set). Output candidate "
                 "passwords ONE PER LINE and nothing else."),
}


def list_provider_types() -> list:
    return [(k, v) for k, v in PROVIDER_TYPES.items()]


# --------------------------------------------------------------------------- #
#  Encrypted storage                                                           #
# --------------------------------------------------------------------------- #
def _store_path() -> str:
    return os.path.join(appconfig.user_config_dir(), ".providers.enc")


def load_providers() -> list:
    path = _store_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, "rb") as fh:
            blob = fh.read()
        return json.loads(_decrypt(blob, _get_key()).decode("utf-8"))
    except Exception:
        return []


def save_providers(providers: list):
    blob = _encrypt(json.dumps(providers).encode("utf-8"), _get_key())
    path = _store_path()
    tmp = path + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(blob)
    os.replace(tmp, path)
    if hasattr(os, "chmod"):
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


def add_provider(cfg: dict) -> dict:
    providers = load_providers()
    cfg = dict(cfg)
    cfg.setdefault("id", "prov-" + str(len(providers) + 1) + "-"
                   + "".join(c for c in (cfg.get("name") or "p") if c.isalnum()))
    providers = [p for p in providers if p.get("id") != cfg["id"]]
    providers.append(cfg)
    save_providers(providers)
    return cfg


def remove_provider(provider_id: str):
    save_providers([p for p in load_providers() if p.get("id") != provider_id])


def get_provider(provider_id: str):
    for p in load_providers():
        if p.get("id") == provider_id:
            return p
    return None


def providers_for_category(category: str) -> list:
    return [p for p in load_providers()
            if category in (p.get("categories") or [])]


# --------------------------------------------------------------------------- #
#  HTTP helpers                                                                #
# --------------------------------------------------------------------------- #
def _http(url, *, method="GET", headers=None, body=None, timeout=30):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _b64(png_bytes):
    return base64.standard_b64encode(png_bytes).decode("ascii")


# --------------------------------------------------------------------------- #
#  list_models / test_connection / chat                                        #
# --------------------------------------------------------------------------- #
def list_models(cfg: dict) -> list:
    api = cfg.get("api") or PROVIDER_TYPES.get(cfg.get("type"), {}).get("api")
    base = (cfg.get("base_url") or "").rstrip("/")
    if api == "ollama":
        data = _http(base + "/api/tags", timeout=10)
        return [m.get("name") for m in data.get("models", [])]
    if api == "anthropic":
        headers = {"x-api-key": cfg.get("api_key", ""),
                   "anthropic-version": "2023-06-01"}
        data = _http(base + "/v1/models", headers=headers, timeout=15)
        return [m.get("id") for m in data.get("data", [])]
    # openai-compatible
    headers = {}
    if cfg.get("api_key"):
        headers["Authorization"] = "Bearer " + cfg["api_key"]
    data = _http(base + "/models", headers=headers, timeout=15)
    return [m.get("id") for m in data.get("data", [])]


def test_connection(cfg: dict) -> tuple:
    """Return (ok, message)."""
    try:
        models = list_models(cfg)
        n = len(models)
        sample = ", ".join(models[:3]) if models else "(none listed)"
        return True, f"Connected. {n} model(s): {sample}"
    except Exception as exc:  # noqa: BLE001
        return False, f"Failed: {exc}"


def chat(cfg: dict, system: str, user: str, image_png=None,
         max_tokens=512) -> str:
    """Send one prompt; return the text reply."""
    api = cfg.get("api") or PROVIDER_TYPES.get(cfg.get("type"), {}).get("api")
    model = cfg.get("model") or PROVIDER_TYPES.get(cfg.get("type"), {}).get(
        "default_model", "")
    base = (cfg.get("base_url") or "").rstrip("/")

    if api == "anthropic":
        return _anthropic_chat(cfg, base, model, system, user, image_png,
                               max_tokens)
    if api == "ollama":
        msg = {"role": "user", "content": user}
        if image_png:
            msg["images"] = [_b64(image_png)]
        body = {"model": model, "messages": ([{"role": "system",
                                               "content": system}] if system
                                             else []) + [msg], "stream": False}
        data = _http(base + "/api/chat", method="POST", body=body,
                     headers={"content-type": "application/json"}, timeout=120)
        return (data.get("message") or {}).get("content", "")
    # openai-compatible
    headers = {"content-type": "application/json"}
    if cfg.get("api_key"):
        headers["Authorization"] = "Bearer " + cfg["api_key"]
    if image_png:
        content = [{"type": "text", "text": user},
                   {"type": "image_url",
                    "image_url": {"url": "data:image/png;base64,"
                                  + _b64(image_png)}}]
        umsg = {"role": "user", "content": content}
    else:
        umsg = {"role": "user", "content": user}
    msgs = ([{"role": "system", "content": system}] if system else []) + [umsg]
    body = {"model": model, "messages": msgs, "max_tokens": max_tokens}
    data = _http(base + "/chat/completions", method="POST", body=body,
                 headers=headers, timeout=120)
    return data["choices"][0]["message"]["content"]


def _anthropic_chat(cfg, base, model, system, user, image_png, max_tokens):
    content = []
    if image_png:
        content.append({"type": "image",
                        "source": {"type": "base64", "media_type": "image/png",
                                   "data": _b64(image_png)}})
    content.append({"type": "text", "text": user})
    # Prefer the official SDK (best practice); fall back to raw HTTP.
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=cfg.get("api_key"),
                                     base_url=base or None)
        kwargs = {"model": model or "claude-opus-4-8", "max_tokens": max_tokens,
                  "messages": [{"role": "user", "content": content}]}
        if system:
            kwargs["system"] = system
        msg = client.messages.create(**kwargs)
        return "".join(b.text for b in msg.content if b.type == "text")
    except ImportError:
        headers = {"x-api-key": cfg.get("api_key", ""),
                   "anthropic-version": "2023-06-01",
                   "content-type": "application/json"}
        body = {"model": model or "claude-opus-4-8", "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": content}]}
        if system:
            body["system"] = system
        data = _http(base + "/v1/messages", method="POST", headers=headers,
                     body=body, timeout=120)
        return "".join(b.get("text", "") for b in data.get("content", [])
                       if b.get("type") == "text")


# --------------------------------------------------------------------------- #
#  Autodetect local servers (item 12)                                          #
# --------------------------------------------------------------------------- #
def autodetect_local() -> list:
    """Probe well-known local ports; return reachable provider configs."""
    found = []
    for name, base, path, api in _LOCAL_PROBES:
        try:
            _http(base + path, timeout=1.5)
            found.append({"name": name, "type": "ollama" if api == "ollama"
                          else "openai_compatible", "api": api,
                          "base_url": base, "needs_key": False})
        except Exception:
            continue
    return found


# --------------------------------------------------------------------------- #
#  High-level helpers used by backend.models                                   #
# --------------------------------------------------------------------------- #
def caption_image(provider_id: str, png_bytes: bytes, user_instruction="") -> str:
    cfg = get_provider(provider_id)
    if not cfg:
        raise ValueError("unknown provider")
    system = CATEGORY_LLM_INSTRUCTIONS["image"]
    if user_instruction:
        system += "\n" + user_instruction
    return chat(cfg, system, "Describe this image.", image_png=png_bytes,
                max_tokens=120).strip()


def generate_passwords(provider_id: str, hints: dict, user_instruction="") -> list:
    cfg = get_provider(provider_id)
    if not cfg:
        return []
    system = CATEGORY_LLM_INSTRUCTIONS["password"]
    if user_instruction:
        system += "\n" + user_instruction
    samples = ", ".join((hints.get("samples") or [])[:20])
    prompt = (f"Samples: {samples}\nMin length: {hints.get('min_len', 1)}, "
              f"max length: {hints.get('max_len', 16)}. Generate up to "
              f"{hints.get('count', 50)} candidates.")
    try:
        text = chat(cfg, system, prompt, max_tokens=600)
    except Exception:
        return []
    return [ln.strip() for ln in text.splitlines() if ln.strip()]
