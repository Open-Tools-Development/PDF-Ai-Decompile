#!/usr/bin/env python3
"""
PDF Ai Decompile  -  main application (CustomTkinter GUI)
==========================================================
A desktop tool that can:
  * modify a PDF by removing images (raster-only, or images + vector figures),
  * convert a PDF to a compilable IEEE LaTeX project, or
  * convert a PDF to a full-text Markdown file (no images).

Authors: see app.about_info.AUTHORS (Jerry James & Nisha).  License: GPL-3.0.

The heavy lifting lives in sibling modules (pdf_remove, pdf_to_latex,
pdf_to_markdown, pdf_common); this file is the UI and the batch runner.
"""

import os
import sys
import queue
import threading
import traceback

import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox

from app import about_info
from backend.pdf_remove import remove_images_from_pdf
from backend.pdf_to_latex import convert_pdf_to_latex
from backend.pdf_to_markdown import convert_pdf_to_markdown


# --------------------------------------------------------------------------- #
#  Helpers                                                                     #
# --------------------------------------------------------------------------- #
def resource_path(rel):
    """Resolve a bundled asset (icon/splash) path.

    In a PyInstaller one-file exe the assets are unpacked to ``sys._MEIPASS``.
    Running from source, this file lives in ``Scripts/app/`` and the assets are
    in ``Scripts/assets/`` — i.e. one level up, then into ``assets``.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        # Try the bundle root first, then an assets/ subfolder.
        for cand in (os.path.join(meipass, rel),
                     os.path.join(meipass, "assets", rel)):
            if os.path.exists(cand):
                return cand
        return os.path.join(meipass, rel)
    here = os.path.dirname(os.path.abspath(__file__))          # .../Scripts/app
    scripts = os.path.dirname(here)                            # .../Scripts
    return os.path.join(scripts, "assets", rel)


def close_pyi_splash():
    """Close the PyInstaller native splash (if running as a frozen exe)."""
    try:
        import pyi_splash  # only exists in the frozen exe
        pyi_splash.close()
    except Exception:
        pass


def find_pdfs_in_folder(folder, recursive=False):
    found = []
    if recursive:
        for root, _dirs, files in os.walk(folder):
            for name in files:
                if name.lower().endswith(".pdf"):
                    found.append(os.path.join(root, name))
    else:
        for name in os.listdir(folder):
            full = os.path.join(folder, name)
            if os.path.isfile(full) and name.lower().endswith(".pdf"):
                found.append(full)
    return sorted(found)


# --------------------------------------------------------------------------- #
#  Splash (shown when running from source; the exe uses PyInstaller's splash)  #
# --------------------------------------------------------------------------- #
def show_source_splash(duration_ms=1800):
    if getattr(sys, "frozen", False):
        return  # exe already shows the native splash
    splash_img = resource_path("splash.png")
    if not os.path.exists(splash_img):
        return None
    try:
        top = ctk.CTkToplevel()
        top.overrideredirect(True)
        img = tk.PhotoImage(file=splash_img)
        w, h = img.width(), img.height()
        sw = top.winfo_screenwidth()
        sh = top.winfo_screenheight()
        top.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")
        lbl = tk.Label(top, image=img, borderwidth=0)
        lbl.image = img
        lbl.pack()
        top.after(duration_ms, top.destroy)
        top.update()
        return top
    except Exception:
        return None


# --------------------------------------------------------------------------- #
#  About dialog                                                                #
# --------------------------------------------------------------------------- #
class AboutDialog(ctk.CTkToplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title(f"About {about_info.APP_NAME}")
        self.geometry("640x640")
        self.resizable(False, True)
        self.after(50, self.grab_set)

        header = ctk.CTkFrame(self, corner_radius=0)
        header.pack(fill="x")
        try:
            from PIL import Image
            ico = ctk.CTkImage(Image.open(resource_path("icon_preview.png")),
                               size=(64, 64))
            ctk.CTkLabel(header, image=ico, text="").pack(side="left",
                                                          padx=14, pady=12)
        except Exception:
            pass
        title_box = ctk.CTkFrame(header, fg_color="transparent")
        title_box.pack(side="left", pady=12)
        ctk.CTkLabel(title_box, text=about_info.APP_NAME,
                     font=ctk.CTkFont(size=22, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(title_box, text=about_info.TAGLINE,
                     text_color=("#0284c7", "#38bdf8")).pack(anchor="w")

        body = ctk.CTkScrollableFrame(self)
        body.pack(fill="both", expand=True, padx=14, pady=14)

        def section(title):
            ctk.CTkLabel(body, text=title,
                         font=ctk.CTkFont(size=15, weight="bold"),
                         anchor="w").pack(fill="x", pady=(12, 4))

        def para(text):
            ctk.CTkLabel(body, text=text, justify="left", anchor="w",
                         wraplength=560).pack(fill="x", pady=2)

        para(f"Version: {about_info.VERSION}")
        para(f"Build: {about_info.build_date_string()}")
        para(f"Author{'s' if len(about_info.AUTHORS) > 1 else ''}: "
             f"{about_info.authors_string()}")
        para(f"Organisation: {about_info.ORG}")
        para(f"License: {about_info.LICENSE}")
        para(about_info.COPYRIGHT)
        para(f"Project: {about_info.PROJECT_URL}")

        section("About")
        para(about_info.DESCRIPTION)

        section("Features")
        for f in about_info.FEATURES:
            para("\u2022  " + f)

        section("How to use")
        for h in about_info.HOW_TO:
            para(h)

        section("Notes")
        for n in about_info.NOTES:
            para("\u2022  " + n)

        section("Revision history")
        for ver, note in about_info.REVISION_HISTORY:
            para(f"v{ver} \u2014 {note}")

        section("This program is free software")
        para("It is distributed under the GNU General Public License v3.0, "
             "in the hope that it will be useful, but WITHOUT ANY WARRANTY; "
             "without even the implied warranty of MERCHANTABILITY or FITNESS "
             "FOR A PARTICULAR PURPOSE. See the LICENSE file for details.")

        ctk.CTkButton(self, text="Close", command=self.destroy).pack(pady=10)


# --------------------------------------------------------------------------- #
#  Main application                                                            #
# --------------------------------------------------------------------------- #
class App(ctk.CTk):
    # Operation metadata: key -> (label, produces_pdf)
    OPERATIONS = [
        ("modify", "Modify PDF  (remove images / figures)", True),
        ("latex", "Convert PDF \u2192 LaTeX", False),
        ("markdown", "Convert PDF \u2192 Markdown (full text)", False),
    ]

    # Math-mode option metadata (label, value, explanation).
    MATH_MODES = [
        ("Rebuild as LaTeX math text", "text",
         "Equations become editable LaTeX (compiles). Approximate \u2014 complex "
         "math may need a manual check. Best for editing later."),
        ("Improve inline math only", "inline",
         "Recovers inline symbols/subscripts; leaves big display equations as "
         "plain text. Lightest touch."),
        ("Hybrid (text + equation images)", "hybrid",
         "Inline math as text, plus exact images for display equations. Good "
         "balance of editable text and correct equations."),
        ("Equation images (exact)", "image",
         "Every display equation is inserted as an exact image. Looks perfect "
         "but equations are not editable text."),
    ]

    DEFAULT_REMOVE_SUFFIX = "_noimg"
    DEFAULT_CONV_PREFIX = ""        # optional name prefix for .tex/.md outputs

    def __init__(self):
        super().__init__()
        self.title(f"{about_info.APP_NAME}  v{about_info.VERSION}")
        # Larger default window so the options panel needs no scrolling.
        self.geometry("1280x880")
        self.minsize(1180, 820)

        self.pdf_paths = []
        self.msg_queue = queue.Queue()
        self.worker = None

        # ---- State ----
        # Operations are now independent toggles (any combination).
        self.op_vars = {
            "modify": tk.BooleanVar(value=False),
            "latex": tk.BooleanVar(value=False),
            "markdown": tk.BooleanVar(value=False),
        }
        self.recursive_var = tk.BooleanVar(value=False)

        # Common output destination shared by all operations.
        self.dest = tk.StringVar(value="beside")      # beside | folder
        self.output_dir = tk.StringVar(value="")

        # Modify-PDF sub-options.
        self.remove_mode = tk.StringVar(value="images")   # images | all
        # Filename suffix to protect the original PDF (item 3).
        self.remove_suffix = tk.StringVar(value=self.DEFAULT_REMOVE_SUFFIX)

        # LaTeX/Markdown sub-options.
        self.math_mode = tk.StringVar(value="text")
        self.prefix_len = tk.StringVar(value="9")
        # Optional output-name prefix for converted files (editable, default).
        self.conv_prefix = tk.StringVar(value=self.DEFAULT_CONV_PREFIX)

        self._set_window_icon()
        self._build_ui()
        self.after(120, self._poll_queue)

    def _set_window_icon(self):
        """Set the title-bar / taskbar icon for the main window."""
        try:
            ico = resource_path("icon.ico")
            if os.path.exists(ico):
                self.iconbitmap(ico)
        except Exception:
            pass
        try:
            from PIL import Image, ImageTk
            png = resource_path("icon_preview.png")
            if os.path.exists(png):
                self._icon_img = ImageTk.PhotoImage(Image.open(png))
                self.iconphoto(True, self._icon_img)
        except Exception:
            pass

    # ------------------------------- layout ------------------------------- #
    def _build_ui(self):
        self.grid_columnconfigure(0, weight=2)
        self.grid_columnconfigure(1, weight=3)
        self.grid_rowconfigure(1, weight=1)

        # ---- Header ----
        header = ctk.CTkFrame(self, corner_radius=0)
        header.grid(row=0, column=0, columnspan=2, sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        htext = ctk.CTkFrame(header, fg_color="transparent")
        htext.grid(row=0, column=0, sticky="w", padx=16, pady=10)
        ctk.CTkLabel(htext, text=about_info.APP_NAME,
                     font=ctk.CTkFont(size=20, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(htext, text=about_info.TAGLINE,
                     text_color=("#0284c7", "#38bdf8")).pack(anchor="w")
        ctk.CTkButton(header, text="About / Help", width=120,
                      command=self._open_about).grid(row=0, column=1,
                                                     padx=16, pady=10)

        # ---- Left column: file queue ----
        left = ctk.CTkFrame(self)
        left.grid(row=1, column=0, sticky="nsew", padx=(12, 6), pady=12)
        left.grid_rowconfigure(2, weight=1)
        left.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(left, text="1.  PDFs to process",
                     font=ctk.CTkFont(size=15, weight="bold")
                     ).grid(row=0, column=0, sticky="w", padx=12, pady=(12, 4))

        btnrow = ctk.CTkFrame(left, fg_color="transparent")
        btnrow.grid(row=1, column=0, sticky="ew", padx=10)
        ctk.CTkButton(btnrow, text="Add PDF File(s)\u2026", width=130,
                      command=self.add_files).pack(side="left", padx=4, pady=4)
        ctk.CTkButton(btnrow, text="Add Folder\u2026", width=110,
                      command=self.add_folder).pack(side="left", padx=4)
        ctk.CTkCheckBox(btnrow, text="Subfolders",
                        variable=self.recursive_var).pack(side="left", padx=8)

        list_wrap = ctk.CTkFrame(left)
        list_wrap.grid(row=2, column=0, sticky="nsew", padx=10, pady=8)
        list_wrap.grid_rowconfigure(0, weight=1)
        list_wrap.grid_columnconfigure(0, weight=1)
        self.listbox = tk.Listbox(
            list_wrap, selectmode=tk.EXTENDED, activestyle="none",
            background="#1d2433", foreground="#e2e8f0",
            selectbackground="#38bdf8", selectforeground="#0f172a",
            highlightthickness=0, borderwidth=0, font=("Segoe UI", 10),
        )
        ys = ctk.CTkScrollbar(list_wrap, command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=ys.set)
        self.listbox.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")

        delrow = ctk.CTkFrame(left, fg_color="transparent")
        delrow.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 10))
        self.count_label = ctk.CTkLabel(delrow, text="Queued: 0")
        self.count_label.pack(side="left", padx=4)
        ctk.CTkButton(delrow, text="Clear", width=70, fg_color="gray30",
                      hover_color="gray25",
                      command=self.clear_list).pack(side="right", padx=4)
        ctk.CTkButton(delrow, text="Remove selected", width=130,
                      fg_color="gray30", hover_color="gray25",
                      command=self.remove_selected).pack(side="right", padx=4)

        # ---- Right column: operations + options (scrollable as a safety net) #
        right = ctk.CTkScrollableFrame(self, label_text="")
        right.grid(row=1, column=1, sticky="nsew", padx=(6, 12), pady=12)
        right.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(right, text="2.  Operations  (enable any combination)",
                     font=ctk.CTkFont(size=15, weight="bold")
                     ).grid(row=0, column=0, sticky="w", pady=(4, 2))
        ctk.CTkLabel(right,
                     text="Turn on one or more. Each runs on every PDF.",
                     text_color="gray", anchor="w"
                     ).grid(row=1, column=0, sticky="w", pady=(0, 6))

        ops = ctk.CTkFrame(right)
        ops.grid(row=2, column=0, sticky="ew", pady=4)
        for key, label, _pdf in self.OPERATIONS:
            ctk.CTkCheckBox(ops, text=label, variable=self.op_vars[key],
                            command=self._refresh_panels
                            ).pack(anchor="w", padx=10, pady=6)

        ctk.CTkLabel(right, text="3.  Options",
                     font=ctk.CTkFont(size=15, weight="bold")
                     ).grid(row=3, column=0, sticky="w", pady=(12, 2))
        self.options_holder = ctk.CTkFrame(right, fg_color="transparent")
        self.options_holder.grid(row=4, column=0, sticky="ew")
        # Two columns so all options fit without vertical scrolling: shared +
        # remove options on the left, the taller convert options on the right.
        self.options_holder.grid_columnconfigure(0, weight=1, uniform="opt")
        self.options_holder.grid_columnconfigure(1, weight=1, uniform="opt")

        self._build_common_panel()      # shared: destination + folder
        self._build_modify_panel()      # Modify-PDF sub-options
        self._build_latex_panel()       # latex/markdown shared sub-options

        # ---- Run + progress ----
        runbar = ctk.CTkFrame(self)
        runbar.grid(row=2, column=0, columnspan=2, sticky="ew",
                    padx=12, pady=(0, 6))
        runbar.grid_columnconfigure(1, weight=1)
        self.run_btn = ctk.CTkButton(runbar, text="Start", width=140,
                                     height=38,
                                     font=ctk.CTkFont(size=15, weight="bold"),
                                     command=self.start_processing)
        self.run_btn.grid(row=0, column=0, padx=10, pady=10)
        self.progress = ctk.CTkProgressBar(runbar)
        self.progress.set(0)
        self.progress.grid(row=0, column=1, sticky="ew", padx=10)
        self.status_lbl = ctk.CTkLabel(runbar, text="Ready", width=120)
        self.status_lbl.grid(row=0, column=2, padx=10)

        # ---- Log ----
        logframe = ctk.CTkFrame(self)
        logframe.grid(row=3, column=0, columnspan=2, sticky="nsew",
                      padx=12, pady=(0, 12))
        self.grid_rowconfigure(3, weight=1)
        logframe.grid_rowconfigure(1, weight=1)
        logframe.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(logframe, text="Log", anchor="w"
                     ).grid(row=0, column=0, sticky="w", padx=10, pady=(8, 0))
        self.log = ctk.CTkTextbox(logframe, height=120, wrap="word")
        self.log.grid(row=1, column=0, sticky="nsew", padx=10, pady=8)
        self.log.configure(state="disabled")

        self._refresh_panels()
        self._log(f"{about_info.APP_NAME} v{about_info.VERSION} ready. "
                  "Enable one or more operations, then click Start.")

    # ---- common (shared) options panel ----
    def _build_common_panel(self):
        p = ctk.CTkFrame(self.options_holder)
        ctk.CTkLabel(p, text="Output location (shared by all operations)",
                     font=ctk.CTkFont(size=13, weight="bold"), anchor="w"
                     ).pack(fill="x", padx=10, pady=(10, 4))
        ctk.CTkRadioButton(p, text="Beside each PDF",
                           variable=self.dest, value="beside",
                           command=self._refresh_panels
                           ).pack(anchor="w", padx=16, pady=3)
        ctk.CTkRadioButton(p, text="In one chosen output folder",
                           variable=self.dest, value="folder",
                           command=self._refresh_panels
                           ).pack(anchor="w", padx=16, pady=3)

        self.folder_row = ctk.CTkFrame(p, fg_color="transparent")
        self.folder_row.pack(fill="x", padx=10, pady=(2, 8))
        self.folder_row.grid_columnconfigure(0, weight=1)
        self.out_entry = ctk.CTkEntry(self.folder_row,
                                      textvariable=self.output_dir,
                                      placeholder_text="Choose a folder\u2026")
        self.out_entry.grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(self.folder_row, text="Browse\u2026", width=90,
                      command=self.choose_output).grid(row=0, column=1,
                                                       padx=(8, 0))
        self.common_panel = p

    # ---- Modify-PDF sub-options ----
    def _build_modify_panel(self):
        p = ctk.CTkFrame(self.options_holder)
        ctk.CTkLabel(p, text="Modify PDF \u2014 options",
                     font=ctk.CTkFont(size=13, weight="bold"), anchor="w"
                     ).pack(fill="x", padx=10, pady=(10, 2))
        ctk.CTkRadioButton(
            p, text="Remove images only (keep charts, tables, layout)",
            variable=self.remove_mode, value="images"
        ).pack(anchor="w", padx=16, pady=3)
        ctk.CTkRadioButton(
            p, text="Remove images + figures/charts (text-only result)",
            variable=self.remove_mode, value="all"
        ).pack(anchor="w", padx=16, pady=3)

        # Filename suffix (mandatory when writing beside the PDF).
        self.suffix_row = ctk.CTkFrame(p, fg_color="transparent")
        self.suffix_row.pack(fill="x", padx=10, pady=(6, 2))
        ctk.CTkLabel(self.suffix_row, text="Add to file name (end):",
                     anchor="w").pack(side="left", padx=(0, 6))
        ctk.CTkEntry(self.suffix_row, textvariable=self.remove_suffix,
                     width=120).pack(side="left")
        self.suffix_hint = ctk.CTkLabel(
            p, text="", anchor="w", justify="left", wraplength=270,
            font=ctk.CTkFont(size=11), text_color="gray")
        self.suffix_hint.pack(fill="x", padx=10, pady=(0, 8))
        self.modify_panel = p

    # ---- LaTeX/Markdown shared sub-options (math + naming) ----
    def _build_math_mode_selector(self, parent):
        box = ctk.CTkFrame(parent, fg_color=("gray92", "gray16"))
        ctk.CTkLabel(box, text="Equation handling (LaTeX)",
                     font=ctk.CTkFont(size=13, weight="bold"), anchor="w"
                     ).pack(fill="x", padx=10, pady=(6, 0))
        for label, value, expl in self.MATH_MODES:
            row = ctk.CTkFrame(box, fg_color="transparent")
            row.pack(fill="x", padx=8, pady=0)
            rb = ctk.CTkRadioButton(row, text=label, variable=self.math_mode,
                                    value=value)
            rb.pack(side="left", anchor="w")
            # Compact: short explanation as an info tooltip-style label to the
            # right keeps height down while staying visible.
            ctk.CTkLabel(box, text=expl, anchor="w", justify="left",
                         wraplength=270, font=ctk.CTkFont(size=10),
                         text_color="gray").pack(anchor="w", padx=(30, 4),
                                                 pady=(0, 1))
        ctk.CTkLabel(
            box,
            text="Trade-off: text = editable but approximate; images = exact. "
                 "Default: LaTeX text.",
            anchor="w", justify="left", wraplength=270,
            font=ctk.CTkFont(size=10, slant="italic"),
            text_color=("#0284c7", "#38bdf8")
        ).pack(fill="x", padx=10, pady=(2, 6))
        return box

    def _build_latex_panel(self):
        p = ctk.CTkFrame(self.options_holder)
        ctk.CTkLabel(p, text="Convert \u2014 options (LaTeX / Markdown)",
                     font=ctk.CTkFont(size=13, weight="bold"), anchor="w"
                     ).pack(fill="x", padx=10, pady=(10, 2))

        self._build_math_mode_selector(p).pack(fill="x", padx=6, pady=(2, 6))

        # Optional output-name prefix for the .tex / .md files.
        pref_row = ctk.CTkFrame(p, fg_color="transparent")
        pref_row.pack(fill="x", padx=10, pady=(2, 0))
        ctk.CTkLabel(pref_row, text="Output name prefix (optional):",
                     anchor="w").pack(side="left", padx=(0, 6))
        ctk.CTkEntry(pref_row, textvariable=self.conv_prefix, width=140,
                     placeholder_text="(none)").pack(side="left")

        # Image-name prefix length.
        plen_row = ctk.CTkFrame(p, fg_color="transparent")
        plen_row.pack(fill="x", padx=10, pady=(6, 0))
        ctk.CTkLabel(plen_row, text="Image name prefix length:",
                     anchor="w").pack(side="left", padx=(0, 6))
        ctk.CTkEntry(plen_row, textvariable=self.prefix_len, width=54).pack(
            side="left")
        ctk.CTkLabel(plen_row, text="letters from PDF name (default 9, 0=full)",
                     text_color="gray", font=ctk.CTkFont(size=11)).pack(
            side="left", padx=8)
        ctk.CTkLabel(
            p, text="Images are named like  Prefix_3_Fig-2.png  (unique number "
                    "+ figure number), so multiple PDFs can share one folder.",
            anchor="w", justify="left", wraplength=270, text_color="gray",
            font=ctk.CTkFont(size=11)
        ).pack(fill="x", padx=10, pady=(4, 8))
        self.latex_panel = p

    # ---- dynamic show/hide ----
    def _selected_ops(self):
        return [k for k in ("modify", "latex", "markdown")
                if self.op_vars[k].get()]

    def _refresh_panels(self):
        ops = self._selected_ops()
        self.common_panel.grid_forget()
        self.modify_panel.grid_forget()
        self.latex_panel.grid_forget()

        # Left column: shared output options, then Modify-PDF options beneath.
        left_row = 0
        if ops:
            self.common_panel.grid(row=left_row, column=0, sticky="new",
                                   padx=(0, 5), pady=(0, 6))
            left_row += 1
        if self.dest.get() == "folder":
            self.folder_row.pack(fill="x", padx=10, pady=(2, 8))
        else:
            self.folder_row.pack_forget()

        if "modify" in ops:
            self.modify_panel.grid(row=left_row, column=0, sticky="new",
                                   padx=(0, 5), pady=(0, 6))
            left_row += 1
            self._update_suffix_hint()

        # Right column: the taller convert options (LaTeX/Markdown).
        if "latex" in ops or "markdown" in ops:
            self.latex_panel.grid(row=0, column=1, rowspan=max(1, left_row),
                                  sticky="new", padx=(5, 0), pady=(0, 6))

    def _update_suffix_hint(self):
        beside = self.dest.get() == "beside"
        if beside:
            self.suffix_hint.configure(
                text="Required: writing beside each PDF, so a suffix is needed "
                     "to avoid overwriting the original (e.g. \"_noimg\").")
        else:
            self.suffix_hint.configure(
                text="Optional: outputs go to a separate folder, so the "
                     "original is safe. Leave blank to keep the same name.")

    # ----------------------------- list ops ------------------------------- #
    def _refresh_list(self):
        self.listbox.delete(0, tk.END)
        for p in self.pdf_paths:
            self.listbox.insert(tk.END, p)
        self.count_label.configure(text=f"Queued: {len(self.pdf_paths)}")

    def _add_paths(self, paths):
        added = 0
        for p in paths:
            ap = os.path.abspath(p)
            if ap not in self.pdf_paths:
                self.pdf_paths.append(ap)
                added += 1
        self.pdf_paths.sort()
        self._refresh_list()
        return added

    def add_files(self):
        paths = filedialog.askopenfilenames(
            title="Select PDF file(s)",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")])
        if paths:
            self._log(f"Added {self._add_paths(paths)} file(s).")

    def add_folder(self):
        folder = filedialog.askdirectory(title="Select a folder with PDFs")
        if not folder:
            return
        found = find_pdfs_in_folder(folder, self.recursive_var.get())
        if not found:
            messagebox.showinfo(about_info.APP_NAME, "No PDFs found there.")
            return
        self._log(f"Found {len(found)} PDF(s); added "
                  f"{self._add_paths(found)} new.")

    def remove_selected(self):
        for index in reversed(list(self.listbox.curselection())):
            del self.pdf_paths[index]
        self._refresh_list()

    def clear_list(self):
        self.pdf_paths.clear()
        self._refresh_list()

    def choose_output(self):
        folder = filedialog.askdirectory(title="Select output folder")
        if folder:
            self.output_dir.set(folder)

    # ------------------------------ logging ------------------------------- #
    def _log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _open_about(self):
        AboutDialog(self)

    # ---------------------------- processing ------------------------------ #
    def start_processing(self):
        if not self.pdf_paths:
            messagebox.showwarning(about_info.APP_NAME,
                                   "Add at least one PDF first.")
            return
        ops = self._selected_ops()
        if not ops:
            messagebox.showerror(
                about_info.APP_NAME,
                "Please enable at least one operation (Modify PDF, Convert "
                "to LaTeX, or Convert to Markdown) before starting.")
            return

        dest = self.dest.get()
        out_dir = self.output_dir.get().strip()
        if dest == "folder":
            if not out_dir:
                messagebox.showwarning(about_info.APP_NAME,
                                       "Choose an output folder, or switch to "
                                       "\"Beside each PDF\".")
                return
            try:
                os.makedirs(out_dir, exist_ok=True)
            except Exception as exc:  # noqa: BLE001
                messagebox.showerror(about_info.APP_NAME,
                                     f"Cannot create output folder:\n{exc}")
                return

        # --- Validate the Modify-PDF suffix rule (item 3) ---
        remove_suffix = self.remove_suffix.get().strip()
        if "modify" in ops and dest == "beside" and not remove_suffix:
            messagebox.showerror(
                about_info.APP_NAME,
                "When 'Modify PDF' writes beside each PDF, you must add a "
                "suffix to the file name so the original PDF is not "
                "overwritten (e.g. \"_noimg\").")
            return

        # --- Validate image-name prefix length (LaTeX) ---
        prefix_len = 9
        if "latex" in ops:
            raw = self.prefix_len.get().strip()
            if raw:
                try:
                    prefix_len = int(raw)
                    if prefix_len < 0 or prefix_len > 40:
                        raise ValueError
                except ValueError:
                    messagebox.showerror(
                        about_info.APP_NAME,
                        "Image name prefix length must be a whole number "
                        "between 0 and 40 (0 = use the full PDF name).")
                    return

        cfg = {
            "ops": ops,
            "dest": dest,
            "out_dir": out_dir,
            "remove_vector": self.remove_mode.get() == "all",
            "remove_suffix": remove_suffix,
            "math_mode": self.math_mode.get(),
            "prefix_len": prefix_len,
            "conv_prefix": self.conv_prefix.get().strip(),
            "files": list(self.pdf_paths),
        }

        self.run_btn.configure(state="disabled")
        self.progress.configure(mode="determinate")
        self.progress.set(0)
        self.status_lbl.configure(text="Working\u2026")
        self._log("-" * 60)
        names = {"modify": "Modify PDF", "latex": "Convert to LaTeX",
                 "markdown": "Convert to Markdown"}
        self._log("Operations: " + ", ".join(names[o] for o in ops)
                  + f"  |  {len(cfg['files'])} file(s)")
        if "modify" in ops:
            self._log("  Modify PDF — remove " + ("images + figures (text-only)"
                      if cfg["remove_vector"] else "images only")
                      + (f"  | suffix: '{remove_suffix}'" if remove_suffix
                         else "  | suffix: (none)"))
        if "latex" in ops:
            mm = dict((v, l) for l, v, _ in self.MATH_MODES).get(
                cfg["math_mode"], cfg["math_mode"])
            self._log(f"  Equations: {mm}  | image prefix length: {prefix_len}")
        if cfg["conv_prefix"]:
            self._log(f"  Output name prefix: '{cfg['conv_prefix']}'")
        self._log("  Output: " + ("beside each PDF" if dest == "beside"
                                   else out_dir))

        self.worker = threading.Thread(target=self._worker, args=(cfg,),
                                       daemon=True)
        self.worker.start()

    def _target_dir_for(self, src_path, cfg):
        if cfg["dest"] == "beside":
            return os.path.dirname(os.path.abspath(src_path))
        return cfg["out_dir"]

    def _conv_out_dir(self, base_dir, op_subfolder=None):
        return base_dir

    def _worker(self, cfg):
        ok = fail = 0
        files = cfg["files"]
        ops = cfg["ops"]
        total = len(files) * max(1, len(ops))
        step = 0
        prefix = cfg.get("conv_prefix", "")

        def named(stem):
            return f"{prefix}{stem}" if prefix else stem

        for path in files:
            base = os.path.basename(path)
            stem, ext = os.path.splitext(base)
            target_dir = self._target_dir_for(path, cfg)
            try:
                os.makedirs(target_dir, exist_ok=True)
            except Exception as exc:  # noqa: BLE001
                self.msg_queue.put(("log", f"  ERROR {base}: {exc}"))
                step += len(ops)
                self.msg_queue.put(("progress", step / total))
                fail += len(ops)
                continue

            for op in ops:
                try:
                    if op == "modify":
                        suffix = cfg["remove_suffix"]
                        out_name = f"{stem}{suffix}{ext}"
                        out_path = os.path.join(target_dir, out_name)
                        # Never overwrite the source.
                        if os.path.abspath(out_path) == os.path.abspath(path):
                            out_path = os.path.join(
                                target_dir, f"{stem}{self.DEFAULT_REMOVE_SUFFIX}{ext}")
                        removed, remaining = remove_images_from_pdf(
                            path, out_path, remove_vector=cfg["remove_vector"])
                        note = (f"{removed} image(s) removed" if remaining == 0
                                else f"{removed} removed, {remaining} not located")
                        self.msg_queue.put((
                            "log", f"  OK  {base} -> "
                            f"{os.path.basename(out_path)} ({note})"))
                    elif op == "latex":
                        tex = convert_pdf_to_latex(
                            path, target_dir,
                            math_mode=cfg.get("math_mode", "text"),
                            name_prefix_len=cfg.get("prefix_len", 9),
                            out_basename=named(stem))
                        self.msg_queue.put((
                            "log", f"  OK  {base} -> "
                            f"{os.path.basename(tex)} (+ Latex_Resource)"))
                    elif op == "markdown":
                        md = convert_pdf_to_markdown(
                            path, target_dir,
                            math_mode=cfg.get("math_mode", "text"),
                            name_prefix_len=cfg.get("prefix_len", 9),
                            out_basename=named(stem))
                        self.msg_queue.put((
                            "log", f"  OK  {base} -> {os.path.basename(md)}"))
                    ok += 1
                except Exception as exc:  # noqa: BLE001
                    fail += 1
                    self.msg_queue.put(("log", f"  ERROR {base} [{op}]: {exc}"))
                    sys.stderr.write(traceback.format_exc() + "\n")
                step += 1
                self.msg_queue.put(("progress", step / total))
        self.msg_queue.put(("done", (ok, fail)))

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.msg_queue.get_nowait()
                if kind == "log":
                    self._log(payload)
                elif kind == "progress":
                    self.progress.set(payload)
                elif kind == "done":
                    ok, fail = payload
                    self._log("-" * 60)
                    self._log(f"Done. {ok} succeeded, {fail} failed.")
                    self.run_btn.configure(state="normal")
                    self.status_lbl.configure(
                        text="Done" if fail == 0 else "Done (errors)")
                    if fail == 0:
                        messagebox.showinfo(about_info.APP_NAME,
                                            f"Finished. {ok} output(s) created.")
                    else:
                        messagebox.showwarning(
                            about_info.APP_NAME,
                            f"Finished: {ok} ok, {fail} failed. See the log.")
        except queue.Empty:
            pass
        self.after(120, self._poll_queue)


def main():
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")
    close_pyi_splash()
    app = App()
    show_source_splash()
    app.mainloop()


if __name__ == "__main__":
    main()
