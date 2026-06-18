#!/usr/bin/env python3
"""
run_app.py
==========
Top-level launcher for PDF Ai Decompile.

It ensures the ``Scripts`` directory (this file's folder) is on ``sys.path`` so
the ``app`` and ``backend`` packages import cleanly, then starts the GUI. This
is also the entry script used by PyInstaller when building the standalone EXE.
"""

import os
import sys

# Make the package root (this folder) importable whether run from source,
# from another directory, or from inside a PyInstaller bundle.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from app.pdf_ai_decompile import main

if __name__ == "__main__":
    main()
