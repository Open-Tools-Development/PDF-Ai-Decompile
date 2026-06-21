#!/usr/bin/env python3
"""Smoke test for backend.passwords (Scratchpad temp)."""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "Scripts")))

import fitz
from backend import passwords as P

print("mask 'a?d':", list(P.mask_candidates("a?d"))[:3], "... count",
      len(list(P.mask_candidates("a?d"))))
print("length ab 1-2:", list(P.length_candidates("ab", 1, 2)))

work = tempfile.mkdtemp(prefix="paid_pwtest_")
enc = os.path.join(work, "enc.pdf")
d = fitz.open()
d.new_page().insert_text((72, 72), "secret content")
d.save(enc, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="42", owner_pw="o")
d.close()

print("\n== brute force (digits, len 1-2) for pw '42' ==")
res = P.crack_file(enc, config={"charset": "digits", "min_len": 1, "max_len": 2,
                                "threads": 4, "limit_type": "attempts",
                                "limit_value": 100000})
print("found:", res["found"], "| password:", repr(res["password"]),
      "| attempts:", res["attempts"], "| reason:", res["reason"])

print("\n== extra_candidates short-circuit ==")
res = P.crack_file(enc, config={"charset": "digits", "min_len": 4, "max_len": 4,
                                "threads": 2},
                   extra_candidates=["00", "99", "42"])
print("found:", res["found"], "| password:", repr(res["password"]),
      "| attempts:", res["attempts"])

print("\n== limit stops a hopeless search ==")
res = P.crack_file(enc, config={"charset": "lower", "min_len": 8, "max_len": 8,
                                "threads": 2, "limit_type": "attempts",
                                "limit_value": 300})
print("found:", res["found"], "| reason:", res["reason"], "| attempts:",
      res["attempts"])

print("\n== non-encrypted returns immediately ==")
plain = os.path.join(work, "plain.pdf")
d = fitz.open(); d.new_page(); d.save(plain); d.close()
res = P.crack_file(plain, config={})
print("found:", res["found"], "| reason:", res["reason"])

print("\n== hidden encrypted pool (isolated config dir) ==")
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="paid_cfg_")
# reload appconfig dir cache is none; user_config_dir reads env each call.
print("added (a,b,a):", P.add_to_hidden_pool(["a", "b", "a"]))
print("load:", P.load_hidden_pool())
print("added (b,c):", P.add_to_hidden_pool(["b", "c"]))
print("load:", P.load_hidden_pool())
pool_file = __import__("backend.appconfig", fromlist=["x"]).password_pool_path()
raw = open(pool_file, "rb").read()
print("on-disk is encrypted (no plaintext 'a\\nb'):",
      b"a\nb" not in raw, "| starts with magic:", raw[:9] == b"PAIDPOOL1")
print("\nALL_PW_OK")
