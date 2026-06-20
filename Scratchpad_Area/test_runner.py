#!/usr/bin/env python3
"""Headless smoke test for backend.pdf_info + backend.runner (Scratchpad temp)."""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.normpath(os.path.join(HERE, "..", "Scripts"))
sys.path.insert(0, SCRIPTS)

import fitz
from backend import pdf_info, runner, project as P

work = tempfile.mkdtemp(prefix="paid_test_")
plain = os.path.join(work, "plain_paper.pdf")
locked = os.path.join(work, "locked_paper.pdf")

# Build a simple 2-page text PDF.
doc = fitz.open()
for i in range(2):
    page = doc.new_page()
    page.insert_text((72, 72), f"Hello World page {i+1}.\nThis is a test paper.",
                     fontsize=14)
doc.save(plain)
# Encrypted copy (user password "letmein", restrict printing).
perm = int(fitz.PDF_PERM_ACCESSIBILITY | fitz.PDF_PERM_COPY)
doc.save(locked, encryption=fitz.PDF_ENCRYPT_AES_256,
         user_pw="letmein", owner_pw="owner", permissions=perm)
doc.close()

print("== scan_pdf(plain) ==")
i1 = pdf_info.scan_pdf(plain)
print("pages:", i1["page_count"], "| encrypted:", i1["encrypted"],
      "| opened:", i1["opened"], "| size:", i1["size_human"])

print("== scan_pdf(locked) no pw ==")
i2 = pdf_info.scan_pdf(locked)
print("encrypted:", i2["encrypted"], "| needs_password:", i2["needs_password"],
      "| opened:", i2["opened"], "| pages:", i2["page_count"])

print("== scan_pdf(locked) with right pw ==")
i3 = pdf_info.scan_pdf(locked, password="letmein")
print("opened:", i3["opened"], "| pages:", i3["page_count"],
      "| pw_used:", repr(i3["password_used"]), "| perms:", i3["permissions"])

print("== try_passwords(locked) from pool ==")
tp = pdf_info.try_passwords(locked, ["nope", "letmein", "x"])
print("opened:", tp["opened"], "| password:", repr(tp["password"]))

print("== render_page_png(locked) ==")
png = pdf_info.render_page_png(locked, 0, password="letmein", zoom=1.0)
print("png bytes:", len(png), "| header ok:", png[:8] == b"\x89PNG\r\n\x1a\n")

print("== runner: decompile markdown + modify, both files, pool has pw ==")
project = P.new_project("Smoke Test")
project["files"].append(P.make_file_entry(plain))
project["files"].append(P.make_file_entry(locked))
project["passwords"]["pool"] = ["letmein"]
project["decompile"]["enabled"] = True
project["decompile"]["formats"] = ["markdown"]
project["modify_pdf"]["enabled"] = True
project["output"]["modify"] = {"dest": "folder", "folder": os.path.join(work, "mod"),
                               "suffix": "_noimg"}
project["output"]["decompile"] = {"dest": "folder", "folder": os.path.join(work, "txt")}

logs = []
res = runner.run(project, log=lambda m: logs.append(m),
                 progress=lambda f: None)
print("\n".join("  " + l for l in logs))
print("result:", res)

# Verify outputs exist.
txt = os.path.join(work, "txt")
mod = os.path.join(work, "mod")
print("md outputs:", sorted(os.listdir(txt)) if os.path.isdir(txt) else "NONE")
print("modified outputs:", sorted(os.listdir(mod)) if os.path.isdir(mod) else "NONE")

# Confirm the locked file's discovered password was recorded on its entry.
locked_entry = project["files"][1]
print("locked entry password recorded:", repr(locked_entry["password"]),
      "| source:", locked_entry["password_source"])
print("ALL_OK")
