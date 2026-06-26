#!/usr/bin/env python3
"""Smoke test for Modify security/metadata + per-folder password CSV."""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "Scripts")))
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="paid_cfg_")

import fitz
from backend import pdf_modify as M, project as P, runner

work = tempfile.mkdtemp(prefix="paid_sec_")


def make(name):
    p = os.path.join(work, name)
    d = fitz.open(); d.new_page().insert_text((72, 72), "content"); d.save(p)
    d.close(); return p


print("== set random open password + metadata ==")
src = make("a.pdf"); out = os.path.join(work, "a_out.pdf")
rep = M.apply_modifications(
    src, out, remove_images=False,
    security={"set_user_password": "random", "random_length": 10},
    metadata={"title": "My Title", "author": "Nisha"})
print("set_password:", repr(rep["set_password"]), "| meta set:", rep["metadata_set"])
d = fitz.open(out)
print("output needs_pass:", d.needs_pass, "| auth works:",
      bool(d.authenticate(rep["set_password"])))
print("title after auth:", d.metadata.get("title"), "| author:",
      d.metadata.get("author"))
d.close()

print("\n== restrictions: deny copy + print ==")
src = make("b.pdf"); out = os.path.join(work, "b_out.pdf")
rep = M.apply_modifications(
    src, out, remove_images=False,
    security={"set_user_password": "none", "restrict": True,
              "owner_password": "ownerpw",
              "permissions": {"copy": False, "print": False, "modify": True,
                              "annotate": True, "fill_forms": True,
                              "accessibility": True, "assemble": True,
                              "print_hq": False}})
print("restricted:", rep["restricted"], "| owner:", repr(rep["owner_password"]))
d = fitz.open(out)
# user pw empty -> opens freely; check permissions deny copy/print.
perms = d.permissions
print("opens freely:", not d.needs_pass)
print("copy allowed:", bool(perms & fitz.PDF_PERM_COPY),
      "| print allowed:", bool(perms & fitz.PDF_PERM_PRINT),
      "| modify allowed:", bool(perms & fitz.PDF_PERM_MODIFY))
d.close()

print("\n== runner: 2 files, random password each -> one CSV in folder ==")
proj = P.new_project("Sec")
f1 = make("doc1.pdf"); f2 = make("doc2.pdf")
proj["files"] += [P.make_file_entry(f1), P.make_file_entry(f2)]
proj["modify_pdf"]["enabled"] = True
proj["modify_pdf"]["security"]["set_user_password"] = "random"
proj["output"]["modify"] = {"dest": "folder", "folder": os.path.join(work, "secout"),
                            "suffix": "_p"}
logs = []
res = runner.run(proj, log=lambda m: logs.append(m))
print("\n".join(l for l in logs if "CSV" in l or "Wrote" in l or "OK" in l))
csvp = os.path.join(work, "secout", "modified_passwords.csv")
print("csv exists:", os.path.exists(csvp))
if os.path.exists(csvp):
    print("csv contents:")
    print(open(csvp, encoding="utf-8").read().strip())
print("\nALL_SECURITY_OK")
