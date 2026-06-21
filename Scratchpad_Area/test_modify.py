#!/usr/bin/env python3
"""Smoke test for backend.pdf_modify (Scratchpad temp)."""
import io
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "Scripts")))

import fitz
from PIL import Image
from backend import pdf_modify as M

work = tempfile.mkdtemp(prefix="paid_modtest_")
ref_png = os.path.join(work, "red.png")
Image.new("RGB", (60, 60), (220, 30, 30)).save(ref_png)

src = os.path.join(work, "src.pdf")
doc = fitz.open()
for i in range(3):
    pg = doc.new_page()
    pg.insert_text((72, 72), f"Hello World, page {i+1}.", fontsize=14)
    if i == 0:
        pg.insert_image(fitz.Rect(72, 120, 172, 220), filename=ref_png)
doc.save(src)
doc.close()

print("parse_page_range('1-2,3', 5):", M.parse_page_range("1-2,3", 5))
print("parse_page_range('all', 3):", M.parse_page_range("all", 3))

print("\n== validate (no write) ==")
rep = M.apply_modifications(
    src, None, validate=True, remove_images=True,
    text_replacements=[{"find": "Hello", "replace": "Goodbye", "regex": False}],
    image_analyzer=lambda png: "a red square",
)
print("validated:", rep["validated"], "| would-remove imgs:",
      rep["images_removed"], "| text reps:", rep["text_replacements"],
      "| analyses:", len(rep["image_analyses"]),
      "| caption:", rep["image_analyses"][0]["caption"])

print("\n== execute: text replace + image delete + keep pages 1-2 ==")
out = os.path.join(work, "out.pdf")
rep = M.apply_modifications(
    src, out,
    text_replacements=[{"find": "Hello", "replace": "Goodbye", "regex": False}],
    image_replacements=[{"image": ref_png, "match_pct": 80, "action": "delete",
                         "replacement": ""}],
    keep_pages="1-2",
    log=lambda m: print(m),
)
print("output:", os.path.basename(rep["output"]), "| text reps:",
      rep["text_replacements"], "| image reps:", rep["image_replacements"],
      "| pages kept:", rep["pages_kept"])

chk = fitz.open(out)
txt = chk[0].get_text("text")
imgs = sum(len(p.get_images(full=True)) for p in chk)
print("page0 has 'Goodbye':", "Goodbye" in txt, "| has 'Hello':", "Hello" in txt)
print("total images after delete:", imgs, "| page count:", chk.page_count)
chk.close()

print("\n== regex replace ==")
out2 = os.path.join(work, "out2.pdf")
M.apply_modifications(src, out2,
                      text_replacements=[{"find": r"page \d+", "replace": "PAGE_X",
                                          "regex": True}])
chk = fitz.open(out2)
print("page0 regex result has 'PAGE_X':", "PAGE_X" in chk[0].get_text("text"))
chk.close()

print("\n== encrypted input + remove_restrictions ==")
enc = os.path.join(work, "enc.pdf")
doc = fitz.open(src)
doc.save(enc, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="pw", owner_pw="o")
doc.close()
out3 = os.path.join(work, "out3.pdf")
rep = M.apply_modifications(enc, out3, password="pw", remove_restrictions=True,
                            remove_images=True)
u = fitz.open(out3)
print("unlocked output needs_pass:", u.needs_pass, "| images:",
      sum(len(p.get_images(full=True)) for p in u))
u.close()
print("\nALL_MODIFY_OK")
