#!/usr/bin/env python3
"""End-to-end: project with cracking + advanced modify + models (Scratchpad)."""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "Scripts")))
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="paid_cfg_")   # isolate config

import fitz
from backend import project as P, runner, models, passwords

# --- model generators (dependency-free) ---
print("== models ==")
print("password models:", [m for m, _ in models.list_models("password")])
print("image models:", [m for m, _ in models.list_models("image")])
markov = list(models.make_password_generator(
    "pw-markov-builtin", {"samples": ["spring2024", "summer2024"],
                          "min_len": 4, "max_len": 12, "count": 5}))
print("markov sample:", markov[:5])
rules = list(models.make_password_generator(
    "pw-rules-builtin", {"samples": ["admin"], "count": 8}))
print("rule sample:", rules[:8])
cap = models.make_image_captioner("img-blip-base")
from PIL import Image
import io
buf = io.BytesIO(); Image.new("RGB", (120, 40), (30, 30, 200)).save(buf, "PNG")
print("caption (fallback):", cap(buf.getvalue()))

# --- build a project with a locked PDF whose pw is '37' ---
work = tempfile.mkdtemp(prefix="paid_int_")
src = os.path.join(work, "locked_doc.pdf")
d = fitz.open()
for i in range(3):
    d.new_page().insert_text((72, 72), f"Hello World, page {i+1}.", fontsize=14)
d.save(src, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="37", owner_pw="o")
d.close()

proj = P.new_project("Integration")
proj["files"].append(P.make_file_entry(src))
# Enable cracking (brute force digits 1-2 finds '37').
cr = proj["passwords"]["cracking"]
cr["enabled"] = True
cr["method"] = "both"
cr["use_hidden_pool"] = True
cr["bruteforce"].update({"charset": "digits", "min_len": 1, "max_len": 2,
                         "threads": 4, "limit_type": "attempts",
                         "limit_value": 100000})
cr["model"]["selected"] = ["pw-markov-builtin", "pw-rules-builtin"]
# Modify with advanced options: replace text, keep pages 1-2, analyse images.
proj["modify_pdf"].update({
    "enabled": True, "mode": "execute",
    "search_replace_text": [{"find": "Hello", "replace": "Hi", "regex": False}],
    "page_range": "all", "keep_pages": "1-2",
    "image_ai_analysis": {"enabled": False, "model": None},
})
proj["output"]["modify"] = {"dest": "folder",
                            "folder": os.path.join(work, "mod"),
                            "suffix": "_mod"}
# Decompile markdown.
proj["decompile"].update({"enabled": True, "formats": ["markdown"]})
proj["output"]["decompile"] = {"dest": "folder", "folder": os.path.join(work, "txt")}

logs = []
res = runner.run(proj, log=lambda m: logs.append(m), progress=lambda f: None)
print("\n== run log ==")
print("\n".join(logs))
print("result:", res)

entry = proj["files"][0]
print("\nrecovered password:", repr(entry["password"]), "| source:",
      entry["password_source"])
print("hidden pool now contains '37':", "37" in passwords.load_hidden_pool())
mod = os.path.join(work, "mod"); txt = os.path.join(work, "txt")
print("modified outputs:", os.listdir(mod) if os.path.isdir(mod) else "NONE")
print("md outputs:", os.listdir(txt) if os.path.isdir(txt) else "NONE")
# Verify modify result: pages kept = 2, text replaced.
mf = os.path.join(mod, "locked_doc_mod.pdf")
c = fitz.open(mf)
print("modified pages:", c.page_count, "| page0 has 'Hi':",
      "Hi" in c[0].get_text("text"), "| has 'Hello':",
      "Hello" in c[0].get_text("text"))
c.close()
print("\nINTEGRATION_OK")
