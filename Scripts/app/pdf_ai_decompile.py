#!/usr/bin/env python3
"""
PDF Ai Decompile  -  main application (CustomTkinter GUI)
==========================================================
A desktop tool, organised around **projects** and two activity categories:

  * **Modify PDF**         — modify a PDF by removing images (raster, or images
                             + vector figures); never overwrites the source.
  * **Decompile to Text**  — rebuild a PDF into text formats (LaTeX, Markdown).

Everything the user sets up (file pool + selection, output destinations, per-file
and pool passwords, options) lives in a single ``.paidproj`` JSON project file so
work can be saved and resumed. The window is tabbed:

  Files · Modify PDF · Decompile to Text · Passwords · Inspector

Authors: see app.about_info.AUTHORS (Jerry James & Nisha).  License: GPL-3.0.

The heavy lifting lives in ``backend`` (project, appconfig, pdf_info, runner,
pdf_remove, pdf_to_latex, pdf_to_markdown); this file is UI + orchestration.
"""

import io
import os
import sys
import queue
import threading
import traceback

import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox

from app import about_info
from backend import appconfig
from backend import project as projmod
from backend import pdf_info
from backend import runner
from backend import models


# --------------------------------------------------------------------------- #
#  Helpers                                                                     #
# --------------------------------------------------------------------------- #
def resource_path(rel):
    """Resolve a bundled asset (icon/splash) path."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        for cand in (os.path.join(meipass, rel),
                     os.path.join(meipass, "assets", rel)):
            if os.path.exists(cand):
                return cand
        return os.path.join(meipass, rel)
    here = os.path.dirname(os.path.abspath(__file__))          # .../Scripts/app
    scripts = os.path.dirname(here)                            # .../Scripts
    return os.path.join(scripts, "assets", rel)


def close_pyi_splash():
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


def show_source_splash(duration_ms=1800):
    if getattr(sys, "frozen", False):
        return
    splash_img = resource_path("splash.png")
    if not os.path.exists(splash_img):
        return None
    try:
        top = ctk.CTkToplevel()
        top.overrideredirect(True)
        img = tk.PhotoImage(file=splash_img)
        w, h = img.width(), img.height()
        sw, sh = top.winfo_screenwidth(), top.winfo_screenheight()
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

        def para(text):
            ctk.CTkLabel(body, text=text, justify="left", anchor="w",
                         wraplength=560).pack(fill="x", pady=2)

        def section(title):
            ctk.CTkLabel(body, text=title,
                         font=ctk.CTkFont(size=15, weight="bold"),
                         anchor="w").pack(fill="x", pady=(12, 4))

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
            para("•  " + f)
        section("How to use")
        for h in about_info.HOW_TO:
            para(h)
        section("Notes")
        for n in about_info.NOTES:
            para("•  " + n)
        section("Revision history")
        for ver, note in about_info.REVISION_HISTORY:
            para(f"v{ver} — {note}")

        ctk.CTkButton(self, text="Close", command=self.destroy).pack(pady=10)


# --------------------------------------------------------------------------- #
#  Main application                                                            #
# --------------------------------------------------------------------------- #
class App(ctk.CTk):
    MATH_MODES = [
        ("Rebuild as LaTeX math text", "text"),
        ("Improve inline math only", "inline"),
        ("Hybrid (text + equation images)", "hybrid"),
        ("Equation images (exact)", "image"),
    ]
    PREVIEW_PAGE_CAP = 40   # safety cap for the Inspector preview

    def __init__(self):
        super().__init__()
        self.geometry("1320x900")
        self.minsize(1180, 820)

        self.project = projmod.new_project("Untitled Project")
        self.project_path = None
        self.msg_queue = queue.Queue()
        self.worker = None
        self._stop_flag = False
        self._preview_imgs = []          # keep CTkImage refs alive
        self._file_rows = []             # current Files-tab rows
        self._perfile_vars = {}          # path -> StringVar (Passwords tab)

        # ---- tk variables bound to settings (gathered into project on save/run)
        self.proj_name = tk.StringVar(value=self.project["project"]["name"])
        self.dest_modify = tk.StringVar(value="beside")
        self.folder_modify = tk.StringVar(value="")
        self.suffix = tk.StringVar(value="_noimg")
        self.dest_dec = tk.StringVar(value="beside")
        self.folder_dec = tk.StringVar(value="")
        self.modify_enabled = tk.BooleanVar(value=False)
        self.modify_mode = tk.StringVar(value="execute")
        self.remove_mode = tk.StringVar(value="images")   # images | all
        self.dec_enabled = tk.BooleanVar(value=False)
        self.fmt_latex = tk.BooleanVar(value=True)
        self.fmt_md = tk.BooleanVar(value=True)
        self.math_mode = tk.StringVar(value="text")
        self.prefix_len = tk.StringVar(value="9")
        self.out_prefix = tk.StringVar(value="")

        # Advanced Modify options.
        self.remove_restrictions = tk.BooleanVar(value=False)
        self.ai_analysis_enabled = tk.BooleanVar(value=False)
        self.ai_model = tk.StringVar(value="img-blip-base")
        self.ai_user_model = tk.StringVar(value="")
        self.process_pages = tk.StringVar(value="all")
        self.keep_pages = tk.StringVar(value="all")
        self.dec_pages = tk.StringVar(value="all")   # Decompile page range

        # Output security + document properties.
        self.sec_pw_mode = tk.StringVar(value="none")    # none|fixed|random
        self.sec_user_pw = tk.StringVar(value="")
        self.sec_restrict = tk.BooleanVar(value=False)
        self.sec_owner_pw = tk.StringVar(value="")
        self.sec_perms = {name: tk.BooleanVar(value=True)
                          for name in ("print", "copy", "modify", "annotate",
                                       "fill_forms", "accessibility",
                                       "assemble", "print_hq")}
        self.meta_title = tk.StringVar(value="")
        self.meta_author = tk.StringVar(value="")
        self.meta_subject = tk.StringVar(value="")
        self.meta_keywords = tk.StringVar(value="")

        # Models tab.
        self.models_root_var = tk.StringVar(value="")
        self.import_repo = tk.StringVar(value="")
        self.import_category = tk.StringVar(value="image")
        self._cat_user_inputs = {}   # category -> (name_var, source_var)
        self._text_rep_rows = []     # (find_var, replace_var, regex_var)
        self._img_rep_rows = []      # (image_var, pct_var, action_var, repl_var)

        # Password cracking config.
        self.crack_enabled = tk.BooleanVar(value=False)
        self.crack_method = tk.StringVar(value="bruteforce")
        self.crack_use_hidden = tk.BooleanVar(value=False)
        self.crack_parallel = tk.BooleanVar(value=False)
        self.bf_charset = tk.StringVar(value="lower+digits")
        self.bf_min = tk.StringVar(value="1")
        self.bf_max = tk.StringVar(value="4")
        self.bf_pattern = tk.StringVar(value="")
        self.bf_threads = tk.StringVar(value="4")
        self.bf_limit_type = tk.StringVar(value="attempts")
        self.bf_limit_value = tk.StringVar(value="1000000")
        self.user_model_path = tk.StringVar(value="")
        self._pw_model_vars = {}     # model_id -> BooleanVar

        # Files-tab filter.
        self.filter_field = tk.StringVar(value="Name")
        self.filter_value = tk.StringVar(value="")

        # Inspector.
        self.insp_file = tk.StringVar(value="")
        self.insp_mode = tk.StringVar(value="info")       # info | preview
        self._insp_paths = []

        self.proj_name.trace_add("write", lambda *_: self._update_title())

        self._set_window_icon()
        self._build_menu()
        self._build_ui()
        self._apply_project_to_ui()
        self.after(120, self._poll_queue)

    # ------------------------------------------------------------------ icon
    def _set_window_icon(self):
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

    # ------------------------------------------------------------------ menu
    def _build_menu(self):
        """Native menu bar (best effort); a header toolbar is the fallback."""
        self._has_native_menu = False
        try:
            menubar = tk.Menu(self)
            pm = tk.Menu(menubar, tearoff=0)
            pm.add_command(label="New Project", accelerator="Ctrl+N",
                           command=self.new_project)
            pm.add_command(label="Open Project…", accelerator="Ctrl+O",
                           command=self.open_project)
            pm.add_command(label="Save", accelerator="Ctrl+S",
                           command=self.save_project)
            pm.add_command(label="Save As…", command=self.save_project_as)
            self.recent_menu = tk.Menu(pm, tearoff=0,
                                       postcommand=self._rebuild_recent_menu)
            pm.add_cascade(label="Open Recent", menu=self.recent_menu)
            pm.add_separator()
            pm.add_command(label="Exit", command=self._on_close)
            menubar.add_cascade(label="Project", menu=pm)

            hm = tk.Menu(menubar, tearoff=0)
            hm.add_command(label="About / Help", command=self._open_about)
            menubar.add_cascade(label="Help", menu=hm)

            self.configure(menu=menubar)
            self._has_native_menu = True
        except Exception:
            self.recent_menu = None

        self.bind_all("<Control-n>", lambda e: self.new_project())
        self.bind_all("<Control-o>", lambda e: self.open_project())
        self.bind_all("<Control-s>", lambda e: self.save_project())
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _rebuild_recent_menu(self):
        if not getattr(self, "recent_menu", None):
            return
        self.recent_menu.delete(0, "end")
        recents = appconfig.recent_projects()
        if not recents:
            self.recent_menu.add_command(label="(none)", state="disabled")
            return
        for r in recents:
            path = r.get("path", "")
            label = f"{r.get('name', 'Project')}  —  {path}"
            self.recent_menu.add_command(
                label=label, command=lambda p=path: self.open_project(p))

    # ------------------------------------------------------------------ layout
    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # ---- Header (identity + project name + toolbar) ----
        header = ctk.CTkFrame(self, corner_radius=0)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(2, weight=1)

        htext = ctk.CTkFrame(header, fg_color="transparent")
        htext.grid(row=0, column=0, sticky="w", padx=14, pady=8)
        ctk.CTkLabel(htext, text=about_info.APP_NAME,
                     font=ctk.CTkFont(size=18, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(htext, text=about_info.TAGLINE,
                     text_color=("#0284c7", "#38bdf8"),
                     font=ctk.CTkFont(size=11)).pack(anchor="w")

        namebox = ctk.CTkFrame(header, fg_color="transparent")
        namebox.grid(row=0, column=1, sticky="w", padx=10)
        ctk.CTkLabel(namebox, text="Project:").pack(side="left", padx=(0, 6))
        ctk.CTkEntry(namebox, textvariable=self.proj_name, width=220).pack(
            side="left")

        toolbar = ctk.CTkFrame(header, fg_color="transparent")
        toolbar.grid(row=0, column=3, sticky="e", padx=12, pady=8)
        for txt, cmd in (("New", self.new_project),
                         ("Open", self.open_project),
                         ("Save", self.save_project),
                         ("Save As", self.save_project_as),
                         ("Recent ▾", self._popup_recent),
                         ("About", self._open_about)):
            ctk.CTkButton(toolbar, text=txt, width=72, command=cmd).pack(
                side="left", padx=3)

        # ---- Tabview ----
        self.tabview = ctk.CTkTabview(self)
        self.tabview.grid(row=1, column=0, sticky="nsew", padx=12, pady=(8, 4))
        for name in ("Files", "Modify PDF", "Decompile to Text",
                     "Passwords", "Models", "Inspector"):
            self.tabview.add(name)
        self._build_files_tab(self.tabview.tab("Files"))
        self._build_modify_tab(self.tabview.tab("Modify PDF"))
        self._build_decompile_tab(self.tabview.tab("Decompile to Text"))
        self._build_passwords_tab(self.tabview.tab("Passwords"))
        self._build_models_tab(self.tabview.tab("Models"))
        self._build_inspector_tab(self.tabview.tab("Inspector"))

        # ---- Run bar ----
        runbar = ctk.CTkFrame(self)
        runbar.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 6))
        runbar.grid_columnconfigure(2, weight=1)
        self.run_btn = ctk.CTkButton(runbar, text="Run", width=130, height=36,
                                     font=ctk.CTkFont(size=15, weight="bold"),
                                     command=self.start_processing)
        self.run_btn.grid(row=0, column=0, padx=10, pady=8)
        self.stop_btn = ctk.CTkButton(runbar, text="Stop", width=80,
                                      fg_color="gray30", hover_color="gray25",
                                      command=self._request_stop, state="disabled")
        self.stop_btn.grid(row=0, column=1, padx=4)
        self.progress = ctk.CTkProgressBar(runbar)
        self.progress.set(0)
        self.progress.grid(row=0, column=2, sticky="ew", padx=10)
        self.status_lbl = ctk.CTkLabel(runbar, text="Ready", width=130)
        self.status_lbl.grid(row=0, column=3, padx=10)

        # ---- Log ----
        logframe = ctk.CTkFrame(self)
        logframe.grid(row=3, column=0, sticky="nsew", padx=12, pady=(0, 12))
        self.grid_rowconfigure(3, weight=0)
        logframe.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(logframe, text="Log", anchor="w").grid(
            row=0, column=0, sticky="w", padx=10, pady=(6, 0))
        self.log = ctk.CTkTextbox(logframe, height=120, wrap="word")
        self.log.grid(row=1, column=0, sticky="nsew", padx=10, pady=8)
        self.log.configure(state="disabled")

    # ============================ Files tab ============================ #
    def _build_files_tab(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(3, weight=1)

        btnrow = ctk.CTkFrame(tab, fg_color="transparent")
        btnrow.grid(row=0, column=0, sticky="ew", pady=(6, 2))
        ctk.CTkButton(btnrow, text="Add PDF File(s)…", width=130,
                      command=self.add_files).pack(side="left", padx=4)
        ctk.CTkButton(btnrow, text="Add Folder…", width=110,
                      command=self.add_folder).pack(side="left", padx=4)
        self.recursive_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(btnrow, text="Subfolders",
                        variable=self.recursive_var).pack(side="left", padx=8)
        ctk.CTkButton(btnrow, text="Select all", width=80,
                      command=lambda: self._select_all_files(True)).pack(
            side="left", padx=(18, 4))
        ctk.CTkButton(btnrow, text="Deselect all", width=90,
                      command=lambda: self._select_all_files(False)).pack(
            side="left", padx=4)
        ctk.CTkButton(btnrow, text="Clear list", width=80, fg_color="gray30",
                      hover_color="gray25", command=self.clear_files).pack(
            side="right", padx=4)

        filt = ctk.CTkFrame(tab, fg_color="transparent")
        filt.grid(row=1, column=0, sticky="ew", pady=2)
        ctk.CTkLabel(filt, text="Filter:").pack(side="left", padx=(4, 4))
        ctk.CTkOptionMenu(filt, width=110, variable=self.filter_field,
                          values=["Name", "Path", "Size ≥ MB",
                                  "Pages ≥"]).pack(side="left")
        ctk.CTkEntry(filt, textvariable=self.filter_value, width=180,
                     placeholder_text="value…").pack(side="left", padx=6)
        ctk.CTkButton(filt, text="Apply", width=70,
                      command=self._render_files).pack(side="left", padx=2)
        ctk.CTkButton(filt, text="Reset", width=64, fg_color="gray30",
                      hover_color="gray25",
                      command=self._reset_filter).pack(side="left", padx=2)

        # Header + rows share one grid (in the scrollable frame) so columns
        # stay aligned regardless of file-name length.
        self.files_frame = ctk.CTkScrollableFrame(tab, label_text="")
        self.files_frame.grid(row=2, column=0, sticky="nsew", pady=(4, 4))
        self.files_count = ctk.CTkLabel(tab, text="Queued: 0  |  selected: 0",
                                        anchor="w")
        self.files_count.grid(row=3, column=0, sticky="w", padx=4, pady=(0, 4))

    # Column layout shared by the Files-tab header and every data row.
    FILE_COLS = [("✓", 30, 0), ("File name", 300, 1), ("Size", 80, 0),
                 ("Pages", 60, 0), ("Protected", 110, 0),
                 ("Restrictions", 170, 0), ("", 34, 0)]
    _PERM_SHORT = {"print": "print", "copy": "copy", "modify": "edit",
                   "annotate": "annot", "fill_forms": "forms",
                   "accessibility": "a11y", "assemble": "assemble",
                   "print_hq": "hi-print"}

    @staticmethod
    def _ellipsize(text, limit=44):
        return text if len(text) <= limit else "…" + text[-(limit - 1):]

    def _reset_filter(self):
        self.filter_value.set("")
        self.filter_field.set("Name")
        self._render_files()

    def _filtered_files(self):
        field = self.filter_field.get()
        val = self.filter_value.get().strip()
        files = self.project["files"]
        if not val:
            return files
        out = []
        for e in files:
            info = e.get("info", {})
            try:
                if field == "Name":
                    if val.lower() in os.path.basename(e["path"]).lower():
                        out.append(e)
                elif field == "Path":
                    if val.lower() in e["path"].lower():
                        out.append(e)
                elif field.startswith("Size"):
                    sb = info.get("size_bytes")
                    if sb is not None and sb >= float(val) * 1024 * 1024:
                        out.append(e)
                elif field.startswith("Pages"):
                    pc = info.get("page_count")
                    if pc is not None and pc >= int(float(val)):
                        out.append(e)
            except ValueError:
                return files   # bad numeric input -> show everything
        return out

    def _protected_text(self, info):
        if not info.get("encrypted"):
            return "No"
        if info.get("needs_password") and not info.get("opened"):
            return "Yes \U0001F512"
        return "Yes"

    def _restrictions_text(self, info):
        perms = info.get("permissions")
        if perms is None:
            return "?" if info.get("encrypted") else "—"
        denied = [self._PERM_SHORT.get(k, k) for k, v in perms.items() if not v]
        return "no " + ", ".join(sorted(denied)) if denied else "—"

    def _render_files(self):
        for child in self.files_frame.winfo_children():
            child.destroy()
        self._file_rows = []
        for col, (_t, w, weight) in enumerate(self.FILE_COLS):
            self.files_frame.grid_columnconfigure(col, minsize=w, weight=weight)
        # Header row.
        for col, (txt, _w, _wt) in enumerate(self.FILE_COLS):
            ctk.CTkLabel(self.files_frame, text=txt, anchor="w",
                         font=ctk.CTkFont(size=11, weight="bold")).grid(
                row=0, column=col, sticky="w", padx=4, pady=(0, 4))

        entries = self._filtered_files()
        for i, e in enumerate(entries, start=1):
            info = e.get("info", {})
            var = tk.BooleanVar(value=e.get("selected", True))
            ctk.CTkCheckBox(self.files_frame, text="", width=24, variable=var,
                            command=lambda en=e, v=var: self._set_selected(en, v)
                            ).grid(row=i, column=0, padx=4, pady=1)
            ctk.CTkLabel(self.files_frame,
                         text=self._ellipsize(os.path.basename(e["path"])),
                         anchor="w").grid(row=i, column=1, sticky="w", padx=4)
            ctk.CTkLabel(self.files_frame,
                         text=pdf_info.human_size(info.get("size_bytes")),
                         anchor="w").grid(row=i, column=2, sticky="w", padx=4)
            pc = info.get("page_count")
            ctk.CTkLabel(self.files_frame, text=("?" if pc is None else str(pc)),
                         anchor="w").grid(row=i, column=3, sticky="w", padx=4)
            ctk.CTkLabel(self.files_frame, text=self._protected_text(info),
                         anchor="w").grid(row=i, column=4, sticky="w", padx=4)
            ctk.CTkLabel(self.files_frame, text=self._restrictions_text(info),
                         anchor="w", font=ctk.CTkFont(size=11)).grid(
                row=i, column=5, sticky="w", padx=4)
            ctk.CTkButton(self.files_frame, text="✕", width=28,
                          fg_color="gray30", hover_color="#b91c1c",
                          command=lambda en=e: self._remove_file(en)).grid(
                row=i, column=6, padx=4, pady=1)
            self._file_rows.append((e, var))
        self._update_file_count()

    def _update_file_count(self):
        total = len(self.project["files"])
        sel = sum(1 for e in self.project["files"] if e.get("selected", True))
        self.files_count.configure(text=f"Queued: {total}  |  selected: {sel}")

    def _set_selected(self, entry, var):
        entry["selected"] = bool(var.get())
        self._update_file_count()

    def _select_all_files(self, value):
        for e in self.project["files"]:
            e["selected"] = value
        self._render_files()

    def _remove_file(self, entry):
        self.project["files"] = [e for e in self.project["files"] if e is not entry]
        self._after_files_changed()

    def clear_files(self):
        self.project["files"] = []
        self._after_files_changed()

    def add_files(self):
        paths = filedialog.askopenfilenames(
            title="Select PDF file(s)",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")])
        if paths:
            self._add_paths(paths)

    def add_folder(self):
        folder = filedialog.askdirectory(title="Select a folder with PDFs")
        if not folder:
            return
        found = find_pdfs_in_folder(folder, self.recursive_var.get())
        if not found:
            messagebox.showinfo(about_info.APP_NAME, "No PDFs found there.")
            return
        self._add_paths(found)

    def _add_paths(self, paths):
        existing = {os.path.abspath(e["path"]) for e in self.project["files"]}
        added = 0
        for p in paths:
            ap = os.path.abspath(p)
            if ap in existing:
                continue
            entry = projmod.make_file_entry(ap)
            try:
                scan = pdf_info.scan_pdf(ap)
                entry["info"] = {
                    "page_count": scan.get("page_count"),
                    "size_bytes": scan.get("size_bytes"),
                    "encrypted": scan.get("encrypted"),
                    "needs_password": scan.get("needs_password"),
                    "opened": scan.get("opened"),
                    "permissions": scan.get("permissions"),
                }
            except Exception:
                pass
            self.project["files"].append(entry)
            existing.add(ap)
            added += 1
        self._log(f"Added {added} file(s).")
        self._after_files_changed()

    def _after_files_changed(self):
        self._render_files()
        self._rebuild_perfile_rows()
        self._refresh_inspector_files()

    # ============================ Modify tab ============================ #
    def _build_modify_tab(self, tab):
        tab.grid_rowconfigure(0, weight=1)
        tab.grid_columnconfigure(0, weight=1)
        body = ctk.CTkScrollableFrame(tab, label_text="")
        body.grid(row=0, column=0, sticky="nsew")
        body.grid_columnconfigure(0, weight=1, uniform="mod")
        body.grid_columnconfigure(1, weight=1, uniform="mod")

        ctk.CTkCheckBox(body, text="Enable “Modify PDF” in the run",
                        variable=self.modify_enabled,
                        font=ctk.CTkFont(size=14, weight="bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=8, pady=(8, 6))

        # Two columns for the compact option groups; wide editors span both.
        def left(panel, row):
            panel.grid(row=row, column=0, sticky="new", padx=(8, 4), pady=4)

        def right(panel, row):
            panel.grid(row=row, column=1, sticky="new", padx=(4, 8), pady=4)

        left(self._build_mode_panel(body), 1)
        right(self._build_what_panel(body), 1)
        left(self._build_pages_panel(body), 2)
        right(self._build_security_panel(body), 2)
        left(self._build_metadata_panel(body), 3)
        right(self._build_ai_analysis_panel(body), 3)
        self._build_text_rep_editor(body).grid(
            row=4, column=0, columnspan=2, sticky="ew", padx=8, pady=4)
        self._build_img_rep_editor(body).grid(
            row=5, column=0, columnspan=2, sticky="ew", padx=8, pady=4)
        self._build_output_panel(body, row=6, dest_var=self.dest_modify,
                                 folder_var=self.folder_modify,
                                 title="Output location (Modify PDF)",
                                 suffix_var=self.suffix, columnspan=2)

    def _build_mode_panel(self, parent):
        f = ctk.CTkFrame(parent)
        ctk.CTkLabel(f, text="Run mode", font=ctk.CTkFont(weight="bold"),
                     anchor="w").pack(fill="x", padx=10, pady=(8, 2))
        ctk.CTkRadioButton(f, text="Execute — write the modified PDF",
                           variable=self.modify_mode, value="execute").pack(
            anchor="w", padx=16, pady=2)
        ctk.CTkRadioButton(
            f, text="Validate — don’t write; report changes (see Inspector)",
            variable=self.modify_mode, value="validate").pack(
            anchor="w", padx=16, pady=(2, 8))
        return f

    def _build_what_panel(self, parent):
        f = ctk.CTkFrame(parent)
        ctk.CTkLabel(f, text="What to remove",
                     font=ctk.CTkFont(weight="bold"), anchor="w").pack(
            fill="x", padx=10, pady=(8, 2))
        ctk.CTkRadioButton(
            f, text="Remove images only (keep charts, tables, layout)",
            variable=self.remove_mode, value="images").pack(
            anchor="w", padx=16, pady=2)
        ctk.CTkRadioButton(
            f, text="Remove images + figures/charts (text-only result)",
            variable=self.remove_mode, value="all").pack(
            anchor="w", padx=16, pady=2)
        ctk.CTkCheckBox(
            f, text="Remove existing restrictions & password (unlocked copy)",
            variable=self.remove_restrictions).pack(
            anchor="w", padx=16, pady=(2, 8))
        return f

    # ---- Modify: output security (set password / restrictions) ----
    def _build_security_panel(self, parent):
        f = ctk.CTkFrame(parent)
        ctk.CTkLabel(f, text="Output security",
                     font=ctk.CTkFont(weight="bold"), anchor="w").pack(
            fill="x", padx=10, pady=(8, 2))
        r1 = ctk.CTkFrame(f, fg_color="transparent")
        r1.pack(fill="x", padx=14, pady=2)
        ctk.CTkLabel(r1, text="Set open password:").pack(side="left",
                                                         padx=(0, 6))
        ctk.CTkOptionMenu(r1, variable=self.sec_pw_mode, width=120,
                          values=["none", "fixed", "random"]).pack(side="left")
        ctk.CTkEntry(r1, textvariable=self.sec_user_pw, width=130,
                     placeholder_text="fixed password").pack(side="left",
                                                              padx=6)
        ctk.CTkCheckBox(f, text="Apply restrictions (owner password)",
                        variable=self.sec_restrict).pack(
            anchor="w", padx=14, pady=(4, 2))
        perms = ctk.CTkFrame(f, fg_color="transparent")
        perms.pack(fill="x", padx=20, pady=2)
        labels = {"print": "print", "copy": "copy", "modify": "edit",
                  "annotate": "annotate", "fill_forms": "forms",
                  "accessibility": "accessibility", "assemble": "assemble",
                  "print_hq": "hi-res print"}
        for i, (name, lbl) in enumerate(labels.items()):
            ctk.CTkCheckBox(perms, text=f"allow {lbl}", width=130,
                            variable=self.sec_perms[name],
                            font=ctk.CTkFont(size=11)).grid(
                row=i // 2, column=i % 2, sticky="w", padx=4, pady=1)
        r3 = ctk.CTkFrame(f, fg_color="transparent")
        r3.pack(fill="x", padx=14, pady=(2, 2))
        ctk.CTkLabel(r3, text="Owner password:").pack(side="left", padx=(0, 6))
        ctk.CTkEntry(r3, textvariable=self.sec_owner_pw, width=130,
                     placeholder_text="blank = random").pack(side="left")
        ctk.CTkLabel(f, text="“random” open passwords are written to "
                             "modified_passwords.csv in each output folder.",
                     text_color="gray", font=ctk.CTkFont(size=11),
                     wraplength=300, justify="left", anchor="w").pack(
            fill="x", padx=10, pady=(2, 8))
        return f

    # ---- Modify: document properties (metadata) ----
    def _build_metadata_panel(self, parent):
        f = ctk.CTkFrame(parent)
        ctk.CTkLabel(f, text="Document properties",
                     font=ctk.CTkFont(weight="bold"), anchor="w").pack(
            fill="x", padx=10, pady=(8, 2))
        for label, var in (("Title", self.meta_title),
                           ("Author", self.meta_author),
                           ("Subject", self.meta_subject),
                           ("Keywords", self.meta_keywords)):
            row = ctk.CTkFrame(f, fg_color="transparent")
            row.pack(fill="x", padx=14, pady=1)
            ctk.CTkLabel(row, text=label + ":", width=70, anchor="w").pack(
                side="left")
            ctk.CTkEntry(row, textvariable=var, width=200,
                         placeholder_text="(leave blank to keep)").pack(
                side="left", fill="x", expand=True)
        ctk.CTkLabel(f, text="Blank fields are left unchanged.",
                     text_color="gray", font=ctk.CTkFont(size=11),
                     anchor="w").pack(fill="x", padx=10, pady=(2, 8))
        return f

    # ---- Modify: search & replace text editor ----
    def _build_text_rep_editor(self, parent):
        f = ctk.CTkFrame(parent)
        ctk.CTkLabel(f, text="Search & replace text",
                     font=ctk.CTkFont(weight="bold"), anchor="w").pack(
            fill="x", padx=10, pady=(8, 2))
        self.text_rep_holder = ctk.CTkFrame(f, fg_color="transparent", height=0)
        self.text_rep_holder.pack(fill="x", padx=8)
        ctk.CTkButton(f, text="+ Add text rule", width=130,
                      command=lambda: self._add_text_rep_row()).pack(
            anchor="w", padx=10, pady=(4, 2))
        ctk.CTkLabel(f, text="Best-effort: matched text is redacted and the "
                             "replacement written in its place.",
                     text_color="gray", font=ctk.CTkFont(size=11),
                     anchor="w").pack(fill="x", padx=10, pady=(0, 8))
        return f

    def _add_text_rep_row(self, find="", replace="", regex=False):
        row = ctk.CTkFrame(self.text_rep_holder, fg_color="transparent")
        row.pack(fill="x", pady=1)
        fv, rv, gv = (tk.StringVar(value=find), tk.StringVar(value=replace),
                      tk.BooleanVar(value=regex))
        ctk.CTkEntry(row, textvariable=fv, width=190,
                     placeholder_text="find").pack(side="left", padx=2)
        ctk.CTkLabel(row, text="→").pack(side="left", padx=2)
        ctk.CTkEntry(row, textvariable=rv, width=190,
                     placeholder_text="replace with").pack(side="left", padx=2)
        ctk.CTkCheckBox(row, text="regex", variable=gv, width=60).pack(
            side="left", padx=4)
        rec = (fv, rv, gv, row)
        ctk.CTkButton(row, text="✕", width=28, fg_color="gray30",
                      hover_color="#b91c1c",
                      command=lambda: self._del_row(self._text_rep_rows, rec)
                      ).pack(side="left", padx=2)
        self._text_rep_rows.append(rec)

    # ---- Modify: search & replace image editor ----
    def _build_img_rep_editor(self, parent):
        f = ctk.CTkFrame(parent)
        ctk.CTkLabel(f, text="Search & replace image",
                     font=ctk.CTkFont(weight="bold"), anchor="w").pack(
            fill="x", padx=10, pady=(8, 2))
        self.img_rep_holder = ctk.CTkFrame(f, fg_color="transparent", height=0)
        self.img_rep_holder.pack(fill="x", padx=8)
        ctk.CTkButton(f, text="+ Add image rule", width=140,
                      command=lambda: self._add_img_rep_row()).pack(
            anchor="w", padx=10, pady=(4, 2))
        ctk.CTkLabel(f, text="Embedded images matching the reference image by "
                             "≥ the given % are deleted or replaced.",
                     text_color="gray", font=ctk.CTkFont(size=11),
                     anchor="w").pack(fill="x", padx=10, pady=(0, 8))
        return f

    def _add_img_rep_row(self, image="", pct="90", action="delete", repl=""):
        row = ctk.CTkFrame(self.img_rep_holder, fg_color="transparent")
        row.pack(fill="x", pady=1)
        iv, pv = tk.StringVar(value=image), tk.StringVar(value=str(pct))
        av, rvar = tk.StringVar(value=action), tk.StringVar(value=repl)
        ctk.CTkEntry(row, textvariable=iv, width=160,
                     placeholder_text="match image…").pack(side="left", padx=2)
        ctk.CTkButton(row, text="…", width=28,
                      command=lambda v=iv: self._choose_image(v)).pack(
            side="left")
        ctk.CTkEntry(row, textvariable=pv, width=44).pack(side="left", padx=2)
        ctk.CTkLabel(row, text="%").pack(side="left")
        ctk.CTkOptionMenu(row, variable=av, width=92,
                          values=["delete", "replace"]).pack(side="left", padx=4)
        ctk.CTkEntry(row, textvariable=rvar, width=150,
                     placeholder_text="replacement (if replace)").pack(
            side="left", padx=2)
        ctk.CTkButton(row, text="…", width=28,
                      command=lambda v=rvar: self._choose_image(v)).pack(
            side="left")
        rec = (iv, pv, av, rvar, row)
        ctk.CTkButton(row, text="✕", width=28, fg_color="gray30",
                      hover_color="#b91c1c",
                      command=lambda: self._del_row(self._img_rep_rows, rec)
                      ).pack(side="left", padx=2)
        self._img_rep_rows.append(rec)

    def _del_row(self, store, rec):
        rec[-1].destroy()
        store[:] = [r for r in store if r is not rec]

    def _choose_image(self, var):
        path = filedialog.askopenfilename(
            title="Select image",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp *.gif"),
                       ("All files", "*.*")])
        if path:
            var.set(path)

    # ---- Modify: AI image analysis ----
    def _build_ai_analysis_panel(self, parent):
        f = ctk.CTkFrame(parent)
        ctk.CTkCheckBox(
            f, text="Analyse images with an AI model (caption each image in "
                    "place)", variable=self.ai_analysis_enabled,
            font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=10,
                                                  pady=(8, 2))
        row = ctk.CTkFrame(f, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(0, 4))
        ctk.CTkLabel(row, text="Model:").pack(side="left", padx=(0, 6))
        img_models = [mid for mid, _ in models.list_models("image")] or \
            ["img-blip-base"]
        ctk.CTkOptionMenu(row, variable=self.ai_model, width=200,
                          values=img_models).pack(side="left")
        ctk.CTkButton(row, text="Download", width=90,
                      command=self._download_selected_image_model).pack(
            side="left", padx=8)
        urow = ctk.CTkFrame(f, fg_color="transparent")
        urow.pack(fill="x", padx=14, pady=(0, 4))
        ctk.CTkLabel(urow, text="Your own model (HF id or local folder):").pack(
            side="left", padx=(0, 6))
        ctk.CTkEntry(urow, textvariable=self.ai_user_model, width=240,
                     placeholder_text="(optional)").pack(side="left")
        ctk.CTkButton(urow, text="…", width=28,
                      command=lambda: self._choose_folder(self.ai_user_model)
                      ).pack(side="left", padx=4)
        ctk.CTkLabel(f, text="Downloaded on demand. Without the model "
                             "(transformers/torch), a heuristic description is "
                             "used.", text_color="gray",
                     font=ctk.CTkFont(size=11), anchor="w").pack(
            fill="x", padx=10, pady=(0, 8))
        return f

    # ---- Modify: page ranges ----
    def _build_pages_panel(self, parent):
        f = ctk.CTkFrame(parent)
        ctk.CTkLabel(f, text="Pages", font=ctk.CTkFont(weight="bold"),
                     anchor="w").pack(fill="x", padx=10, pady=(8, 2))
        r1 = ctk.CTkFrame(f, fg_color="transparent")
        r1.pack(fill="x", padx=14, pady=2)
        ctk.CTkLabel(r1, text="Apply changes to pages:", width=170,
                     anchor="w").pack(side="left")
        ctk.CTkEntry(r1, textvariable=self.process_pages, width=160).pack(
            side="left")
        ctk.CTkLabel(r1, text="e.g. all or 1-3,5", text_color="gray").pack(
            side="left", padx=8)
        r2 = ctk.CTkFrame(f, fg_color="transparent")
        r2.pack(fill="x", padx=14, pady=(2, 8))
        ctk.CTkLabel(r2, text="Keep only these pages:", width=170,
                     anchor="w").pack(side="left")
        ctk.CTkEntry(r2, textvariable=self.keep_pages, width=160).pack(
            side="left")
        ctk.CTkLabel(r2, text="all = keep every page", text_color="gray").pack(
            side="left", padx=8)
        return f

    # ========================== Decompile tab ========================== #
    def _build_decompile_tab(self, tab):
        tab.grid_rowconfigure(0, weight=1)
        tab.grid_columnconfigure(0, weight=1)
        body = ctk.CTkScrollableFrame(tab, label_text="")
        body.grid(row=0, column=0, sticky="nsew")
        body.grid_columnconfigure(0, weight=1, uniform="dec")
        body.grid_columnconfigure(1, weight=1, uniform="dec")

        ctk.CTkCheckBox(body, text="Enable “Decompile to Text” in the run",
                        variable=self.dec_enabled,
                        font=ctk.CTkFont(size=14, weight="bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=8, pady=(8, 6))

        fmt = ctk.CTkFrame(body)
        fmt.grid(row=1, column=0, sticky="new", padx=(8, 4), pady=4)
        ctk.CTkLabel(fmt, text="Output formats",
                     font=ctk.CTkFont(weight="bold"), anchor="w").pack(
            fill="x", padx=10, pady=(8, 2))
        ctk.CTkCheckBox(fmt, text="LaTeX (.tex + Latex_Resource)",
                        variable=self.fmt_latex).pack(anchor="w", padx=16, pady=2)
        ctk.CTkCheckBox(fmt, text="Markdown (.md, full text)",
                        variable=self.fmt_md).pack(anchor="w", padx=16,
                                                   pady=(2, 8))

        mm = ctk.CTkFrame(body)
        mm.grid(row=1, column=1, rowspan=2, sticky="new", padx=(4, 8), pady=4)
        ctk.CTkLabel(mm, text="Equation handling (LaTeX)",
                     font=ctk.CTkFont(weight="bold"), anchor="w").pack(
            fill="x", padx=10, pady=(8, 2))
        for label, value in self.MATH_MODES:
            ctk.CTkRadioButton(mm, text=label, variable=self.math_mode,
                               value=value).pack(anchor="w", padx=16, pady=1)

        names = ctk.CTkFrame(body)
        names.grid(row=2, column=0, sticky="new", padx=(8, 4), pady=4)
        ctk.CTkLabel(names, text="Naming & pages",
                     font=ctk.CTkFont(weight="bold"), anchor="w").pack(
            fill="x", padx=10, pady=(8, 2))
        prow = ctk.CTkFrame(names, fg_color="transparent")
        prow.pack(fill="x", padx=10, pady=(8, 2))
        ctk.CTkLabel(prow, text="Output name prefix (optional):").pack(
            side="left", padx=(0, 6))
        ctk.CTkEntry(prow, textvariable=self.out_prefix, width=140,
                     placeholder_text="(none)").pack(side="left")
        lrow = ctk.CTkFrame(names, fg_color="transparent")
        lrow.pack(fill="x", padx=10, pady=(2, 4))
        ctk.CTkLabel(lrow, text="Image name prefix length:").pack(
            side="left", padx=(0, 6))
        ctk.CTkEntry(lrow, textvariable=self.prefix_len, width=54).pack(
            side="left")
        ctk.CTkLabel(lrow, text="letters from PDF name (default 9, 0=full)",
                     text_color="gray").pack(side="left", padx=8)
        prow2 = ctk.CTkFrame(names, fg_color="transparent")
        prow2.pack(fill="x", padx=10, pady=(2, 8))
        ctk.CTkLabel(prow2, text="Pages to include:").pack(side="left",
                                                           padx=(0, 6))
        ctk.CTkEntry(prow2, textvariable=self.dec_pages, width=160).pack(
            side="left")
        ctk.CTkLabel(prow2, text="all = every page, or e.g. 1-3,5",
                     text_color="gray").pack(side="left", padx=8)

        self._build_output_panel(body, row=3, dest_var=self.dest_dec,
                                 folder_var=self.folder_dec,
                                 title="Output location (Decompile to Text)",
                                 columnspan=2)

    # Shared output-destination panel (beside / chosen folder).
    def _build_output_panel(self, tab, row, dest_var, folder_var, title,
                            suffix_var=None, column=0, columnspan=1):
        p = ctk.CTkFrame(tab)
        p.grid(row=row, column=column, columnspan=columnspan, sticky="ew",
               padx=8, pady=4)
        ctk.CTkLabel(p, text=title, font=ctk.CTkFont(weight="bold"),
                     anchor="w").pack(fill="x", padx=10, pady=(8, 2))
        ctk.CTkRadioButton(p, text="Beside each input PDF",
                           variable=dest_var, value="beside").pack(
            anchor="w", padx=16, pady=2)
        ctk.CTkRadioButton(p, text="In one chosen output folder",
                           variable=dest_var, value="folder").pack(
            anchor="w", padx=16, pady=2)
        frow = ctk.CTkFrame(p, fg_color="transparent")
        frow.pack(fill="x", padx=12, pady=(2, 6))
        frow.grid_columnconfigure(0, weight=1)
        ctk.CTkEntry(frow, textvariable=folder_var,
                     placeholder_text="Choose a folder…").grid(
            row=0, column=0, sticky="ew")
        ctk.CTkButton(frow, text="Browse…", width=90,
                      command=lambda v=folder_var: self._choose_folder(v)).grid(
            row=0, column=1, padx=(8, 0))
        if suffix_var is not None:
            srow = ctk.CTkFrame(p, fg_color="transparent")
            srow.pack(fill="x", padx=12, pady=(0, 8))
            ctk.CTkLabel(srow, text="Add to file name (suffix):").pack(
                side="left", padx=(0, 6))
            ctk.CTkEntry(srow, textvariable=suffix_var, width=120).pack(
                side="left")
            ctk.CTkLabel(
                srow, text="required when writing beside the PDF (never "
                           "overwrites the original)",
                text_color="gray", font=ctk.CTkFont(size=11)).pack(
                side="left", padx=8)

    def _choose_folder(self, var):
        folder = filedialog.askdirectory(title="Select output folder")
        if folder:
            var.set(folder)

    # ========================== Passwords tab ========================== #
    def _build_passwords_tab(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_columnconfigure(1, weight=1)
        tab.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            tab, text="Passwords are tried before processing each PDF: the "
                      "file’s specific password first, then the shared pool. "
                      "Locked files are skipped unless cracking finds the "
                      "password. Recover only files you are authorised to open.",
            justify="left", wraplength=1000, text_color="gray").grid(
            row=0, column=0, columnspan=2, sticky="w", padx=8, pady=(8, 4))

        left = ctk.CTkFrame(tab)
        left.grid(row=1, column=0, sticky="nsew", padx=(8, 4), pady=4)
        left.grid_rowconfigure(1, weight=1)
        left.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(left, text="Shared password pool (one per line)",
                     font=ctk.CTkFont(weight="bold"), anchor="w").grid(
            row=0, column=0, sticky="w", padx=10, pady=(8, 2))
        self.pool_box = ctk.CTkTextbox(left, wrap="none")
        self.pool_box.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 8))

        right = ctk.CTkFrame(tab)
        right.grid(row=1, column=1, sticky="nsew", padx=(4, 8), pady=4)
        right.grid_rowconfigure(1, weight=1)
        right.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(right, text="Per-file password (optional)",
                     font=ctk.CTkFont(weight="bold"), anchor="w").grid(
            row=0, column=0, sticky="w", padx=10, pady=(8, 2))
        self.perfile_frame = ctk.CTkScrollableFrame(right, label_text="")
        self.perfile_frame.grid(row=1, column=0, sticky="nsew", padx=10,
                                pady=(0, 8))

        self._build_cracking_panel(tab).grid(row=2, column=0, columnspan=2,
                                             sticky="ew", padx=8, pady=4)

        actions = ctk.CTkFrame(tab, fg_color="transparent")
        actions.grid(row=3, column=0, columnspan=2, sticky="ew", padx=8,
                     pady=(0, 6))
        ctk.CTkButton(actions, text="Detect passwords now",
                      command=self.detect_passwords).pack(side="left", padx=4)
        ctk.CTkButton(actions, text="Crack now", command=self.crack_now).pack(
            side="left", padx=4)
        ctk.CTkLabel(
            actions, text="Detect = try pool/per-file. Crack = also run the "
                          "configured brute force / models (can be slow).",
            text_color="gray", font=ctk.CTkFont(size=11)).pack(
            side="left", padx=10)

    def _build_cracking_panel(self, parent):
        f = ctk.CTkFrame(parent)
        ctk.CTkCheckBox(
            f, text="Enable password cracking", variable=self.crack_enabled,
            font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=0, columnspan=6, sticky="w", padx=10, pady=(8, 2))

        m = ctk.CTkFrame(f, fg_color="transparent")
        m.grid(row=1, column=0, columnspan=6, sticky="w", padx=10, pady=2)
        ctk.CTkLabel(m, text="Method:").pack(side="left", padx=(0, 4))
        ctk.CTkOptionMenu(m, variable=self.crack_method, width=120,
                          values=["bruteforce", "model", "both"]).pack(
            side="left")
        ctk.CTkCheckBox(m, text="Use hidden reuse pool",
                        variable=self.crack_use_hidden).pack(side="left",
                                                             padx=12)
        ctk.CTkCheckBox(m, text="Crack files in parallel",
                        variable=self.crack_parallel).pack(side="left", padx=8)

        bf = ctk.CTkFrame(f, fg_color="transparent")
        bf.grid(row=2, column=0, columnspan=6, sticky="w", padx=10, pady=2)
        ctk.CTkLabel(bf, text="Brute force:").pack(side="left", padx=(0, 4))
        ctk.CTkComboBox(bf, variable=self.bf_charset, width=130,
                        values=["digits", "lower", "upper", "letters",
                                "lower+digits", "alnum", "all"]).pack(
            side="left", padx=2)
        ctk.CTkLabel(bf, text="len").pack(side="left", padx=(8, 2))
        ctk.CTkEntry(bf, textvariable=self.bf_min, width=40).pack(side="left")
        ctk.CTkLabel(bf, text="–").pack(side="left")
        ctk.CTkEntry(bf, textvariable=self.bf_max, width=40).pack(side="left")
        ctk.CTkLabel(bf, text="mask").pack(side="left", padx=(8, 2))
        ctk.CTkEntry(bf, textvariable=self.bf_pattern, width=110,
                     placeholder_text="?d?d (optional)").pack(side="left")
        ctk.CTkLabel(bf, text="threads").pack(side="left", padx=(8, 2))
        ctk.CTkEntry(bf, textvariable=self.bf_threads, width=40).pack(
            side="left")

        lim = ctk.CTkFrame(f, fg_color="transparent")
        lim.grid(row=3, column=0, columnspan=6, sticky="w", padx=10, pady=2)
        ctk.CTkLabel(lim, text="Limit:").pack(side="left", padx=(0, 4))
        ctk.CTkOptionMenu(lim, variable=self.bf_limit_type, width=110,
                          values=["attempts", "time", "infinite"]).pack(
            side="left")
        ctk.CTkEntry(lim, textvariable=self.bf_limit_value, width=110).pack(
            side="left", padx=6)
        ctk.CTkLabel(lim, text="(max attempts, or seconds)",
                     text_color="gray").pack(side="left")

        mdl = ctk.CTkFrame(f, fg_color="transparent")
        mdl.grid(row=4, column=0, columnspan=6, sticky="w", padx=10, pady=2)
        ctk.CTkLabel(mdl, text="Models:").pack(side="left", padx=(0, 4))
        self._pw_model_vars = {}
        for mid, meta in models.list_models("password"):
            var = tk.BooleanVar(value=False)
            ctk.CTkCheckBox(mdl, text=meta.get("name", mid), variable=var).pack(
                side="left", padx=6)
            self._pw_model_vars[mid] = var

        um = ctk.CTkFrame(f, fg_color="transparent")
        um.grid(row=5, column=0, columnspan=6, sticky="w", padx=10, pady=(2, 8))
        ctk.CTkLabel(um, text="Your own model (.py with generate(hints)):").pack(
            side="left", padx=(0, 4))
        ctk.CTkEntry(um, textvariable=self.user_model_path, width=260,
                     placeholder_text="path to .py…").pack(side="left")
        ctk.CTkButton(um, text="…", width=28,
                      command=self._choose_user_model).pack(side="left", padx=4)
        return f

    def _choose_user_model(self):
        path = filedialog.askopenfilename(
            title="Select a password generator (.py)",
            filetypes=[("Python", "*.py"), ("All files", "*.*")])
        if path:
            self.user_model_path.set(path)

    def _download_selected_image_model(self):
        if not models.huggingface_hub_available():
            messagebox.showinfo(
                about_info.APP_NAME,
                "Downloads need the 'huggingface_hub' package.\n\n"
                "Install it with:  pip install huggingface_hub\n\n"
                "Manage and test models in the Models tab.")
            return
        mid = self.ai_model.get()
        self._log(f"Downloading model {mid}… (see the Models tab to manage)")

        def work():
            try:
                models.download_model(
                    mid, progress=lambda m: self.msg_queue.put(("log", m)))
            except Exception as exc:  # noqa: BLE001
                self.msg_queue.put(("log", f"Download failed: {exc}"))
            self.msg_queue.put(("models_refresh", "image"))
        threading.Thread(target=work, daemon=True).start()

    def crack_now(self):
        self._gather_ui_to_project()
        if not self.project["passwords"]["cracking"]["enabled"]:
            messagebox.showinfo(about_info.APP_NAME,
                                "Enable password cracking first.")
            return
        self._stop_flag = False
        self.run_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.status_lbl.configure(text="Cracking…")
        self._log("-" * 64)
        self._log("Cracking passwords…")

        def work():
            runner.recovery_pass(
                self.project, stop=lambda: self._stop_flag,
                log=lambda m: self.msg_queue.put(("log", m)))
            self.msg_queue.put(("crack_done", None))
        threading.Thread(target=work, daemon=True).start()

    def _rebuild_perfile_rows(self):
        for child in self.perfile_frame.winfo_children():
            child.destroy()
        self._perfile_vars = {}
        self.perfile_frame.grid_columnconfigure(0, weight=1, minsize=150)
        self.perfile_frame.grid_columnconfigure(1, weight=0, minsize=150)
        per_file = self.project["passwords"].get("per_file", {})
        # Only files that are actually password-protected (item 1).
        encrypted = [e for e in self.project["files"]
                     if (e.get("info") or {}).get("encrypted")
                     or (e.get("info") or {}).get("needs_password")]
        if not encrypted:
            ctk.CTkLabel(self.perfile_frame,
                         text="No password-protected files in the list.",
                         text_color="gray").grid(row=0, column=0, columnspan=2,
                                                  sticky="w", padx=6, pady=6)
            return
        ctk.CTkLabel(self.perfile_frame, text="File", anchor="w",
                     font=ctk.CTkFont(size=11, weight="bold")).grid(
            row=0, column=0, sticky="w", padx=4, pady=(0, 4))
        ctk.CTkLabel(self.perfile_frame, text="Password", anchor="w",
                     font=ctk.CTkFont(size=11, weight="bold")).grid(
            row=0, column=1, sticky="w", padx=4, pady=(0, 4))
        for i, e in enumerate(encrypted, start=1):
            path = e["path"]
            # Read-only, horizontally scrollable name field (long names readable).
            name_entry = ctk.CTkEntry(self.perfile_frame)
            name_entry.insert(0, os.path.basename(path))
            name_entry.grid(row=i, column=0, sticky="ew", padx=4, pady=1)
            try:
                name_entry.configure(state="readonly")
            except Exception:
                pass
            var = tk.StringVar(value=per_file.get(path, ""))
            ctk.CTkEntry(self.perfile_frame, textvariable=var, width=150,
                         placeholder_text="password…").grid(
                row=i, column=1, sticky="w", padx=4, pady=1)
            self._perfile_vars[path] = var

    def detect_passwords(self):
        self._gather_ui_to_project()
        n = 0
        for e in self.project["files"]:
            res = runner.resolve_password(e, self.project)
            if res.get("error"):
                self._log(f"  {os.path.basename(e['path'])}: error "
                          f"({res['error']})")
            elif not res["needs_password"]:
                e["info"]["needs_password"] = False
                self._log(f"  {os.path.basename(e['path'])}: not encrypted")
            elif res["opened"]:
                e["password"] = res["password"]
                e["password_source"] = "provided/pool"
                runner._record_password(res["password"])
                n += 1
                self._log(f"  {os.path.basename(e['path'])}: unlocked "
                          f"(password found)")
            else:
                self._log(f"  {os.path.basename(e['path'])}: LOCKED "
                          "(no working password)")
        self._log(f"Detect passwords: {n} file(s) unlocked.")
        self._render_files()

    # ============================ Models tab =========================== #
    def _build_models_tab(self, tab):
        tab.grid_rowconfigure(0, weight=1)
        tab.grid_columnconfigure(0, weight=1)
        self._cat_holders = {}
        self._hw = None
        sub = ctk.CTkTabview(tab)
        sub.grid(row=0, column=0, sticky="nsew")
        for n in ("Overview", "Password", "Image", "Import (HF)"):
            sub.add(n)
        self._build_models_overview(sub.tab("Overview"))
        self._build_category_subtab(sub.tab("Password"), "password")
        self._build_category_subtab(sub.tab("Image"), "image")
        self._build_models_import(sub.tab("Import (HF)"))

    def _build_models_overview(self, tab):
        body = ctk.CTkScrollableFrame(tab, label_text="")
        body.pack(fill="both", expand=True)

        fold = ctk.CTkFrame(body)
        fold.pack(fill="x", padx=8, pady=6)
        ctk.CTkLabel(fold, text="Models folder",
                     font=ctk.CTkFont(weight="bold"), anchor="w").pack(
            fill="x", padx=10, pady=(8, 2))
        row = ctk.CTkFrame(fold, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=2)
        row.grid_columnconfigure(0, weight=1)
        self.models_root_var.set(appconfig.models_root())
        ctk.CTkEntry(row, textvariable=self.models_root_var).grid(
            row=0, column=0, sticky="ew")
        ctk.CTkButton(row, text="Browse…", width=80,
                      command=lambda: self._choose_folder(self.models_root_var)
                      ).grid(row=0, column=1, padx=4)
        ctk.CTkButton(row, text="Save", width=60,
                      command=self._save_models_root).grid(row=0, column=2,
                                                           padx=2)
        ctk.CTkButton(row, text="Open", width=60,
                      command=self._open_models_folder).grid(row=0, column=3,
                                                             padx=2)
        ctk.CTkLabel(fold, text="Each downloaded model gets its own subfolder "
                                "with a model.json config. Shared across "
                                "projects.", text_color="gray",
                     font=ctk.CTkFont(size=11), anchor="w").pack(
            fill="x", padx=10, pady=(0, 8))

        env = ctk.CTkFrame(body)
        env.pack(fill="x", padx=8, pady=6)
        hrow = ctk.CTkFrame(env, fg_color="transparent")
        hrow.pack(fill="x", padx=10, pady=(8, 0))
        ctk.CTkLabel(hrow, text="Environment & hardware",
                     font=ctk.CTkFont(weight="bold")).pack(side="left")
        ctk.CTkButton(hrow, text="Refresh", width=70,
                      command=self._refresh_models_env).pack(side="right")
        self.models_env_label = ctk.CTkLabel(env, text="…", justify="left",
                                             anchor="w", wraplength=820)
        self.models_env_label.pack(fill="x", padx=10, pady=(2, 8))

        cats = ctk.CTkFrame(body)
        cats.pack(fill="x", padx=8, pady=6)
        ctk.CTkLabel(cats, text="Model categories",
                     font=ctk.CTkFont(weight="bold"), anchor="w").pack(
            fill="x", padx=10, pady=(8, 2))
        for cat, meta in models.CATEGORIES.items():
            c = ctk.CTkFrame(cats, fg_color=("gray92", "gray16"))
            c.pack(fill="x", padx=10, pady=4)
            ctk.CTkLabel(c, text=meta["name"], font=ctk.CTkFont(weight="bold"),
                         anchor="w").pack(fill="x", padx=8, pady=(6, 0))
            ctk.CTkLabel(c, text=meta["summary"], anchor="w", justify="left",
                         wraplength=820, text_color="gray").pack(
                fill="x", padx=8)
            ctk.CTkLabel(c, text="I/O: " + meta["io"], anchor="w",
                         justify="left", wraplength=820,
                         font=ctk.CTkFont(size=11)).pack(fill="x", padx=8)
            ctk.CTkLabel(c, text="Category configuration: fixed (not "
                                 "user-changeable).", anchor="w",
                         font=ctk.CTkFont(size=11, slant="italic"),
                         text_color="gray").pack(fill="x", padx=8, pady=(0, 6))
        self._refresh_models_env()

    def _refresh_models_env(self):
        self._hw = models.hardware_info()
        hub = models.huggingface_hub_available()
        trans = models._transformers_available()
        gpu = self._hw["gpu_name"] or ("yes" if self._hw["gpu"] else "none")
        text = (
            f"CPU: {self._hw['cpu_count']} cores · RAM: "
            f"{self._hw['ram_gb']} GB · GPU: {gpu}\n"
            f"huggingface_hub: " + ("installed"
                                    if hub else "NOT installed — run  pip "
                                    "install huggingface_hub  to enable "
                                    "downloads/imports") + "\n"
            f"transformers + torch: " + ("installed"
                                         if trans else "NOT installed — run  "
                                         "pip install transformers torch  to "
                                         "run image models"))
        self.models_env_label.configure(text=text)

    def _save_models_root(self):
        appconfig.set_models_root(self.models_root_var.get().strip())
        self._log(f"Models folder set to: {appconfig.models_root()}")
        for cat in models.CATEGORIES:
            if cat in self._cat_holders:
                self._render_category_models(cat)

    def _open_models_folder(self):
        path = appconfig.models_root()
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)  # noqa: S606
            else:
                import subprocess
                subprocess.Popen(["open" if sys.platform == "darwin"
                                  else "xdg-open", path])
        except Exception as exc:  # noqa: BLE001
            messagebox.showinfo(about_info.APP_NAME, f"Folder: {path}\n{exc}")

    def _build_category_subtab(self, tab, category):
        body = ctk.CTkScrollableFrame(tab, label_text="")
        body.pack(fill="both", expand=True)
        meta = models.category_meta(category)
        ctk.CTkLabel(body, text=meta.get("name", category),
                     font=ctk.CTkFont(size=15, weight="bold"), anchor="w").pack(
            fill="x", padx=10, pady=(8, 0))
        ctk.CTkLabel(body, text=meta.get("summary", ""), anchor="w",
                     justify="left", wraplength=820, text_color="gray").pack(
            fill="x", padx=10, pady=(0, 6))

        holder = ctk.CTkFrame(body, fg_color="transparent")
        holder.pack(fill="x", padx=6)
        self._cat_holders[category] = holder

        # Add-your-own-model section (item 6.4).
        add = ctk.CTkFrame(body)
        add.pack(fill="x", padx=8, pady=(10, 6))
        ctk.CTkLabel(add, text="Add your own model",
                     font=ctk.CTkFont(weight="bold"), anchor="w").pack(
            fill="x", padx=10, pady=(8, 2))
        ctk.CTkLabel(add, text=self._user_model_guide(category), anchor="w",
                     justify="left", wraplength=820,
                     font=ctk.CTkFont(size=11)).pack(fill="x", padx=10)
        name_var, source_var = tk.StringVar(), tk.StringVar()
        self._cat_user_inputs[category] = (name_var, source_var)
        frow = ctk.CTkFrame(add, fg_color="transparent")
        frow.pack(fill="x", padx=12, pady=(4, 8))
        ctk.CTkLabel(frow, text="Name:").pack(side="left", padx=(0, 4))
        ctk.CTkEntry(frow, textvariable=name_var, width=120,
                     placeholder_text="my model").pack(side="left", padx=2)
        ctk.CTkLabel(frow, text="Source:").pack(side="left", padx=(8, 4))
        ctk.CTkEntry(frow, textvariable=source_var, width=240,
                     placeholder_text=(".py file" if category == "password"
                                       else "HF id or local folder")).pack(
            side="left", padx=2)
        ctk.CTkButton(frow, text="…", width=28,
                      command=lambda c=category: self._browse_user_model(c)
                      ).pack(side="left")
        ctk.CTkButton(frow, text="Add", width=60,
                      command=lambda c=category: self._add_user_model(c)).pack(
            side="left", padx=6)
        self._render_category_models(category)

    def _user_model_guide(self, category):
        if category == "password":
            return ("Write a Python file exposing  generate(hints) -> "
                    "list[str].  hints = {samples, min_len, max_len, count}. "
                    "Browse to the .py, give it a name, Add, then Test.")
        return ("Use a local Hugging Face image-to-text model folder, or a HF "
                "repo id (e.g. nlpconnect/vit-gpt2-image-captioning). Enter it, "
                "name it, Add, then Test. Needs transformers + torch to run.")

    def _browse_user_model(self, category):
        _name, source_var = self._cat_user_inputs[category]
        if category == "password":
            path = filedialog.askopenfilename(
                title="Select generator (.py)",
                filetypes=[("Python", "*.py"), ("All files", "*.*")])
        else:
            path = filedialog.askdirectory(title="Select model folder")
        if path:
            source_var.set(path)

    def _add_user_model(self, category):
        name_var, source_var = self._cat_user_inputs[category]
        source = source_var.get().strip()
        if not source:
            messagebox.showinfo(about_info.APP_NAME, "Enter a model source.")
            return
        entry = models.register_user_model(category, name_var.get().strip(),
                                           source)
        self._log(f"Added {category} model: {entry['name']} ({entry['id']})")
        name_var.set(""); source_var.set("")
        self._render_category_models(category)

    def _render_category_models(self, category):
        holder = self._cat_holders.get(category)
        if holder is None:
            return
        for child in holder.winfo_children():
            child.destroy()
        hw = self._hw or models.hardware_info()

        def model_row(mid, name, source, status, reasons, is_user):
            r = ctk.CTkFrame(holder)
            r.pack(fill="x", pady=2)
            top = ctk.CTkFrame(r, fg_color="transparent")
            top.pack(fill="x", padx=8, pady=(6, 0))
            badge = {"built-in": "✓ built-in", "installed": "✓ installed",
                     "needs-deps": "needs deps", "available": "downloadable",
                     "user": "your model"}.get(status, status)
            ctk.CTkLabel(top, text=f"{name}", anchor="w",
                         font=ctk.CTkFont(weight="bold")).pack(side="left")
            ctk.CTkLabel(top, text=f"  [{badge}]  {source}",
                         text_color="gray", font=ctk.CTkFont(size=11)).pack(
                side="left")
            btns = ctk.CTkFrame(r, fg_color="transparent")
            btns.pack(fill="x", padx=8, pady=(0, 6))
            if status in ("available", "needs-deps"):
                ctk.CTkButton(btns, text="Download", width=90,
                              command=lambda: self._download_model(mid, category)
                              ).pack(side="left", padx=2)
            ctk.CTkButton(btns, text="Test", width=70,
                          command=lambda: self._test_model(mid, category,
                                                           is_user)).pack(
                side="left", padx=2)
            if is_user:
                ctk.CTkButton(btns, text="Remove", width=70, fg_color="gray30",
                              hover_color="#b91c1c",
                              command=lambda: self._remove_user_model(
                                  mid, category)).pack(side="left", padx=2)
            if reasons:
                ctk.CTkLabel(btns, text="⚠ " + "; ".join(reasons),
                             text_color="#f59e0b",
                             font=ctk.CTkFont(size=11)).pack(side="left",
                                                             padx=8)

        for mid, meta in models.list_models(category):
            status = models.install_status(mid)
            _ok, reasons = models.applicable(mid, hw)
            sz = meta.get("size_mb")
            src = (meta.get("source", "") + (f" · ~{sz} MB" if sz else "")).strip()
            model_row(mid, meta.get("name", mid), src, status, reasons, False)
        for um in models.list_user_models(category):
            model_row(um["id"], um.get("name", um["id"]),
                      str(um.get("path", "")), "user", [], True)

    def _download_model(self, mid, category):
        ok, reasons = models.applicable(mid, self._hw or models.hardware_info())
        if not ok and not messagebox.askyesno(
                about_info.APP_NAME,
                "This model may not run well on your PC:\n  - "
                + "\n  - ".join(reasons)
                + "\n\nDownload anyway?"):
            return
        if not models.huggingface_hub_available():
            messagebox.showinfo(
                about_info.APP_NAME,
                "Downloads need the 'huggingface_hub' package.\n\n"
                "Install it with:  pip install huggingface_hub")
            return
        self._log(f"Downloading {mid}…")

        def work():
            try:
                models.download_model(
                    mid, progress=lambda m: self.msg_queue.put(("log", m)))
            except Exception as exc:  # noqa: BLE001
                self.msg_queue.put(("log", f"Download failed: {exc}"))
            self.msg_queue.put(("models_refresh", category))
        threading.Thread(target=work, daemon=True).start()

    def _test_model(self, mid, category, is_user):
        source = None
        if is_user:
            for um in models.list_user_models(category):
                if um["id"] == mid:
                    source = um.get("path")
                    break
        self._log(f"Testing {mid}…")

        def work():
            ok, msg = models.self_test(mid, category, source=source)
            self.msg_queue.put(("log", f"  Test {mid}: "
                                f"{'OK' if ok else 'FAILED'} — {msg}"))
        threading.Thread(target=work, daemon=True).start()

    def _remove_user_model(self, mid, category):
        models.remove_user_model(mid)
        self._log(f"Removed model {mid}")
        self._render_category_models(category)

    def _build_models_import(self, tab):
        body = ctk.CTkScrollableFrame(tab, label_text="")
        body.pack(fill="both", expand=True)
        ctk.CTkLabel(body, text="Import a model from Hugging Face",
                     font=ctk.CTkFont(size=15, weight="bold"), anchor="w").pack(
            fill="x", padx=10, pady=(8, 2))
        ctk.CTkLabel(body, text="Enter any Hugging Face repo id; it downloads "
                                "into your models folder and is registered for "
                                "the chosen category. Browse models at the "
                                "sources below.", anchor="w", justify="left",
                     wraplength=820, text_color="gray").pack(fill="x", padx=10)
        srow = ctk.CTkFrame(body, fg_color="transparent")
        srow.pack(fill="x", padx=10, pady=(4, 4))
        for label, url in models.MODEL_SOURCES:
            ctk.CTkButton(srow, text=f"Open: {label}", width=200,
                          command=lambda u=url: self._open_url(u)).pack(
                side="left", padx=4)

        form = ctk.CTkFrame(body)
        form.pack(fill="x", padx=8, pady=8)
        r1 = ctk.CTkFrame(form, fg_color="transparent")
        r1.pack(fill="x", padx=10, pady=(8, 2))
        ctk.CTkLabel(r1, text="Repo id:").pack(side="left", padx=(0, 4))
        ctk.CTkEntry(r1, textvariable=self.import_repo, width=300,
                     placeholder_text="e.g. nlpconnect/vit-gpt2-image-captioning"
                     ).pack(side="left", padx=2)
        ctk.CTkLabel(r1, text="Category:").pack(side="left", padx=(10, 4))
        ctk.CTkOptionMenu(r1, variable=self.import_category, width=120,
                          values=list(models.CATEGORIES)).pack(side="left")
        ctk.CTkButton(r1, text="Download & import", width=150,
                      command=self._import_hf).pack(side="left", padx=8)
        ctk.CTkLabel(form, text="⚠ Large downloads; image models need "
                                "transformers + torch to run. Validation lets "
                                "you force-use a model that fails its test.",
                     text_color="#f59e0b", font=ctk.CTkFont(size=11),
                     anchor="w", justify="left", wraplength=820).pack(
            fill="x", padx=10, pady=(0, 8))

    def _open_url(self, url):
        import webbrowser
        try:
            webbrowser.open(url)
        except Exception:
            messagebox.showinfo(about_info.APP_NAME, url)

    def _import_hf(self):
        repo = self.import_repo.get().strip()
        cat = self.import_category.get()
        if not repo:
            messagebox.showinfo(about_info.APP_NAME, "Enter a HF repo id.")
            return
        if not models.huggingface_hub_available():
            messagebox.showinfo(
                about_info.APP_NAME,
                "Importing needs the 'huggingface_hub' package.\n\n"
                "Install it with:  pip install huggingface_hub")
            return
        self._log(f"Importing {repo} ({cat})…")

        def work():
            try:
                entry = models.import_hf_model(
                    repo, cat,
                    progress=lambda m: self.msg_queue.put(("log", m)))
                self.msg_queue.put(("log", f"Imported as {entry['id']}."))
            except Exception as exc:  # noqa: BLE001
                self.msg_queue.put(("log", f"Import failed: {exc}"))
            self.msg_queue.put(("models_refresh", cat))
        threading.Thread(target=work, daemon=True).start()

    # ========================== Inspector tab ========================== #
    def _build_inspector_tab(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)

        top = ctk.CTkFrame(tab, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", pady=(6, 2))
        ctk.CTkLabel(top, text="File:").pack(side="left", padx=(4, 4))
        self.insp_menu = ctk.CTkOptionMenu(top, width=320,
                                           variable=self.insp_file,
                                           values=["(no files)"],
                                           command=lambda _v: self._inspector_refresh())
        self.insp_menu.pack(side="left", padx=4)
        ctk.CTkRadioButton(top, text="Info", variable=self.insp_mode,
                           value="info",
                           command=self._inspector_refresh).pack(
            side="left", padx=(16, 4))
        ctk.CTkRadioButton(top, text="Preview", variable=self.insp_mode,
                           value="preview",
                           command=self._inspector_refresh).pack(
            side="left", padx=4)
        ctk.CTkButton(top, text="Refresh", width=80,
                      command=self._inspector_refresh).pack(side="left", padx=12)

        self.insp_body = ctk.CTkScrollableFrame(tab, label_text="")
        self.insp_body.grid(row=1, column=0, sticky="nsew", pady=(0, 4))

    def _refresh_inspector_files(self):
        self._insp_paths = [e["path"] for e in self.project["files"]]
        labels = [os.path.basename(p) for p in self._insp_paths] or ["(no files)"]
        self.insp_menu.configure(values=labels)
        if self._insp_paths:
            if self.insp_file.get() not in labels:
                self.insp_file.set(labels[0])
        else:
            self.insp_file.set("(no files)")

    def _current_inspector_entry(self):
        label = self.insp_file.get()
        for e in self.project["files"]:
            if os.path.basename(e["path"]) == label:
                return e
        return None

    def _clear_insp_body(self):
        for child in self.insp_body.winfo_children():
            child.destroy()
        self._preview_imgs = []

    def _inspector_refresh(self):
        self._clear_insp_body()
        entry = self._current_inspector_entry()
        if not entry:
            ctk.CTkLabel(self.insp_body, text="Add files in the Files tab.",
                         text_color="gray").pack(anchor="w", padx=10, pady=10)
            return
        if self.insp_mode.get() == "info":
            self._show_inspector_info(entry)
        else:
            self._start_inspector_preview(entry)

    def _show_inspector_info(self, entry):
        path = entry["path"]
        pw = entry.get("password")
        scan = pdf_info.scan_pdf(path, password=pw)
        entry["info"].update({
            "page_count": scan.get("page_count"),
            "size_bytes": scan.get("size_bytes"),
            "encrypted": scan.get("encrypted"),
            "needs_password": scan.get("needs_password"),
            "opened": scan.get("opened"),
            "permissions": scan.get("permissions"),
        })

        def line(label, value):
            r = ctk.CTkFrame(self.insp_body, fg_color="transparent")
            r.pack(fill="x", padx=8, pady=1)
            ctk.CTkLabel(r, text=label, width=180, anchor="w",
                         font=ctk.CTkFont(weight="bold")).pack(side="left")
            ctk.CTkLabel(r, text=str(value), anchor="w", justify="left",
                         wraplength=620).pack(side="left")

        line("File name", scan["name"])
        line("Path", path)
        line("Size", scan["size_human"])
        line("Encrypted", "Yes" if scan["encrypted"] else "No")
        if scan["encrypted"]:
            src = entry.get("password_source")
            if scan["opened"]:
                used = scan.get("password_used")
                shown = pw or used
                note = f"  (source: {src})" if src and src != "none" else ""
                line("Password", (f"known: “{shown}”" if shown not in (None, "")
                                  else "(empty user password)") + note)
            elif self.crack_enabled.get():
                line("Password", "UNKNOWN — locked. Cracking is enabled: run "
                     "“Crack now” (Passwords tab) or Run; progress appears in "
                     "the Log below.")
            else:
                line("Password", "UNKNOWN — file is locked (add it in the "
                     "Passwords tab, run Detect, or enable cracking).")
        line("Pages", "?" if scan["page_count"] is None else scan["page_count"])
        perms = scan.get("permissions")
        if perms:
            denied = [k for k, v in perms.items() if not v]
            line("Restrictions", "none" if not denied
                 else ", ".join(sorted(denied)) + " (not allowed)")

        # Document properties (item 3.3).
        meta = scan.get("metadata") or {}
        shown_meta = [(k, meta.get(k)) for k in
                      ("title", "author", "subject", "keywords", "creator",
                       "producer", "creationDate", "modDate", "format")
                      if meta.get(k)]
        if shown_meta:
            ctk.CTkLabel(self.insp_body, text="Properties",
                         font=ctk.CTkFont(size=14, weight="bold"),
                         anchor="w").pack(fill="x", padx=8, pady=(12, 2))
            for k, v in shown_meta:
                line(k.capitalize(), v)

        # Planned modifications (item 9 — validate/preview overview).
        self._gather_ui_to_project()
        jobs = runner.jobs_for(self.project)
        ctk.CTkLabel(self.insp_body, text="Planned for this run",
                     font=ctk.CTkFont(size=14, weight="bold"),
                     anchor="w").pack(fill="x", padx=8, pady=(12, 2))
        if not jobs:
            line("Operations", "none enabled")
        else:
            line("Operations", ", ".join(runner.JOB_LABELS[j] for j in jobs))
            if "modify" in jobs:
                mp = self.project["modify_pdf"]
                line("Modify mode", mp.get("mode", "execute"))
                bits = []
                if mp.get("remove_images", True):
                    bits.append("images + figures" if mp.get("remove_vector")
                                else "images")
                if mp.get("remove_restrictions_and_password"):
                    bits.append("restrictions + password")
                if mp.get("search_replace_text"):
                    bits.append(f"{len(mp['search_replace_text'])} text rule(s)")
                if mp.get("search_replace_image"):
                    bits.append(f"{len(mp['search_replace_image'])} image rule(s)")
                if (mp.get("image_ai_analysis") or {}).get("enabled"):
                    bits.append("AI image analysis")
                line("Modify actions", ", ".join(bits) or "none")
                line("Modify pages", f"apply {mp.get('page_range', 'all')}, "
                                     f"keep {mp.get('keep_pages', 'all')}")
            if "latex" in jobs or "markdown" in jobs:
                line("Decompile pages",
                     self.project["decompile"].get("page_range", "all"))

    def _start_inspector_preview(self, entry):
        ctk.CTkLabel(self.insp_body, text="Rendering preview…",
                     text_color="gray").pack(anchor="w", padx=10, pady=10)
        path = entry["path"]
        pw = entry.get("password")
        t = threading.Thread(target=self._preview_worker, args=(path, pw),
                             daemon=True)
        t.start()

    def _preview_worker(self, path, password):
        try:
            scan = pdf_info.scan_pdf(path, password=password)
            if not scan.get("opened"):
                self.msg_queue.put(("ipreview_err",
                                    "File is locked — add its password."))
                return
            pages = scan.get("page_count") or 0
            self.msg_queue.put(("ipreview_start", pages))
            for i in range(min(pages, self.PREVIEW_PAGE_CAP)):
                png = pdf_info.render_page_png(path, i, password=password,
                                               zoom=1.3)
                self.msg_queue.put(("ipreview_img", (i + 1, png)))
            self.msg_queue.put(("ipreview_done", pages))
        except Exception as exc:  # noqa: BLE001
            self.msg_queue.put(("ipreview_err", str(exc)))

    # ============================ projects ============================= #
    def _update_title(self):
        name = self.proj_name.get() or "Untitled Project"
        suffix = f"  —  {self.project_path}" if self.project_path else \
            "  (unsaved)"
        self.title(f"{about_info.APP_NAME} v{about_info.VERSION}  –  "
                   f"{name}{suffix}")

    def _apply_project_to_ui(self):
        p = self.project
        self.proj_name.set(p["project"].get("name", "Untitled Project"))
        om = p["output"].get("modify", {})
        self.dest_modify.set(om.get("dest", "beside"))
        self.folder_modify.set(om.get("folder", ""))
        self.suffix.set(om.get("suffix", "_noimg"))
        od = p["output"].get("decompile", {})
        self.dest_dec.set(od.get("dest", "beside"))
        self.folder_dec.set(od.get("folder", ""))
        mp = p.get("modify_pdf", {})
        self.modify_enabled.set(mp.get("enabled", False))
        self.modify_mode.set(mp.get("mode", "execute"))
        self.remove_mode.set("all" if mp.get("remove_vector") else "images")
        self.remove_restrictions.set(
            mp.get("remove_restrictions_and_password", False))
        ai = mp.get("image_ai_analysis", {}) or {}
        self.ai_analysis_enabled.set(ai.get("enabled", False))
        self.ai_model.set(ai.get("model") or "img-blip-base")
        self.ai_user_model.set(ai.get("user_model", "") or "")
        self.process_pages.set(mp.get("page_range", "all") or "all")
        self.keep_pages.set(mp.get("keep_pages", "all") or "all")
        self._set_text_reps(mp.get("search_replace_text", []) or [])
        self._set_img_reps(mp.get("search_replace_image", []) or [])
        sec = mp.get("security", {}) or {}
        self.sec_pw_mode.set(sec.get("set_user_password", "none"))
        self.sec_user_pw.set(sec.get("user_password", ""))
        self.sec_restrict.set(sec.get("restrict", False))
        self.sec_owner_pw.set(sec.get("owner_password", ""))
        sp = sec.get("permissions", {}) or {}
        for name, var in self.sec_perms.items():
            var.set(sp.get(name, True))
        meta = mp.get("metadata", {}) or {}
        self.meta_title.set(meta.get("title", ""))
        self.meta_author.set(meta.get("author", ""))
        self.meta_subject.set(meta.get("subject", ""))
        self.meta_keywords.set(meta.get("keywords", ""))
        self._apply_cracking(p.get("passwords", {}).get("cracking", {}))
        dc = p.get("decompile", {})
        self.dec_enabled.set(dc.get("enabled", False))
        fmts = dc.get("formats", ["latex", "markdown"])
        self.fmt_latex.set("latex" in fmts)
        self.fmt_md.set("markdown" in fmts)
        self.math_mode.set(dc.get("math_mode", "text"))
        self.prefix_len.set(str(dc.get("name_prefix_len", 9)))
        self.out_prefix.set(dc.get("out_prefix", ""))
        self.dec_pages.set(dc.get("page_range", "all") or "all")
        # Pool + per-file.
        self.pool_box.delete("1.0", "end")
        self.pool_box.insert("1.0", "\n".join(p["passwords"].get("pool", [])))
        self._render_files()
        self._rebuild_perfile_rows()
        self._refresh_inspector_files()
        self._inspector_refresh()
        self._update_title()

    def _gather_ui_to_project(self):
        p = self.project
        p["project"]["name"] = self.proj_name.get().strip() or "Untitled Project"
        p["output"]["modify"] = {"dest": self.dest_modify.get(),
                                 "folder": self.folder_modify.get().strip(),
                                 "suffix": self.suffix.get().strip()}
        p["output"]["decompile"] = {"dest": self.dest_dec.get(),
                                    "folder": self.folder_dec.get().strip()}
        mpf = p["modify_pdf"]
        mpf["enabled"] = bool(self.modify_enabled.get())
        mpf["mode"] = self.modify_mode.get()
        mpf["remove_vector"] = self.remove_mode.get() == "all"
        mpf["remove_restrictions_and_password"] = bool(
            self.remove_restrictions.get())
        mpf["image_ai_analysis"] = {
            "enabled": bool(self.ai_analysis_enabled.get()),
            "model": self.ai_model.get(),
            "user_model": self.ai_user_model.get().strip()}
        mpf["page_range"] = self.process_pages.get().strip() or "all"
        mpf["keep_pages"] = self.keep_pages.get().strip() or "all"
        mpf["search_replace_text"] = self._gather_text_reps()
        mpf["search_replace_image"] = self._gather_img_reps()
        mpf["security"] = {
            "set_user_password": self.sec_pw_mode.get(),
            "user_password": self.sec_user_pw.get(),
            "restrict": bool(self.sec_restrict.get()),
            "owner_password": self.sec_owner_pw.get(),
            "permissions": {n: bool(v.get())
                            for n, v in self.sec_perms.items()},
        }
        mpf["metadata"] = {"title": self.meta_title.get().strip(),
                           "author": self.meta_author.get().strip(),
                           "subject": self.meta_subject.get().strip(),
                           "keywords": self.meta_keywords.get().strip()}
        self._gather_cracking()
        fmts = []
        if self.fmt_latex.get():
            fmts.append("latex")
        if self.fmt_md.get():
            fmts.append("markdown")
        p["decompile"]["enabled"] = bool(self.dec_enabled.get())
        p["decompile"]["formats"] = fmts
        p["decompile"]["math_mode"] = self.math_mode.get()
        try:
            p["decompile"]["name_prefix_len"] = int(self.prefix_len.get().strip()
                                                    or "9")
        except ValueError:
            p["decompile"]["name_prefix_len"] = 9
        p["decompile"]["out_prefix"] = self.out_prefix.get().strip()
        p["decompile"]["page_range"] = self.dec_pages.get().strip() or "all"
        # Passwords.
        pool = [ln.strip() for ln in
                self.pool_box.get("1.0", "end").splitlines() if ln.strip()]
        p["passwords"]["pool"] = pool
        per_file = {}
        for path, var in self._perfile_vars.items():
            val = var.get().strip()
            if val:
                per_file[path] = val
        p["passwords"]["per_file"] = per_file

    # ---- advanced-Modify and cracking gather/apply helpers ----
    def _set_text_reps(self, reps):
        for rec in list(self._text_rep_rows):
            rec[3].destroy()
        self._text_rep_rows = []
        for rp in reps:
            self._add_text_rep_row(rp.get("find", ""), rp.get("replace", ""),
                                   rp.get("regex", False))

    def _set_img_reps(self, reps):
        for rec in list(self._img_rep_rows):
            rec[4].destroy()
        self._img_rep_rows = []
        for rp in reps:
            self._add_img_rep_row(rp.get("image", ""), rp.get("match_pct", 90),
                                  rp.get("action", "delete"),
                                  rp.get("replacement", ""))

    def _gather_text_reps(self):
        out = []
        for fv, rv, gv, _row in self._text_rep_rows:
            if fv.get().strip():
                out.append({"find": fv.get(), "replace": rv.get(),
                            "regex": bool(gv.get())})
        return out

    def _gather_img_reps(self):
        out = []
        for iv, pv, av, rvar, _row in self._img_rep_rows:
            if iv.get().strip():
                try:
                    pct = float(pv.get())
                except ValueError:
                    pct = 90.0
                out.append({"image": iv.get(), "match_pct": pct,
                            "action": av.get(), "replacement": rvar.get()})
        return out

    @staticmethod
    def _int_or(var, default):
        try:
            return int(float(var.get().strip()))
        except (ValueError, AttributeError):
            return default

    def _gather_cracking(self):
        cr = self.project["passwords"]["cracking"]
        cr["enabled"] = bool(self.crack_enabled.get())
        cr["method"] = self.crack_method.get()
        cr["use_hidden_pool"] = bool(self.crack_use_hidden.get())
        cr["parallel_files"] = bool(self.crack_parallel.get())
        bf = cr["bruteforce"]
        bf["charset"] = self.bf_charset.get().strip() or "lower+digits"
        bf["min_len"] = self._int_or(self.bf_min, 1)
        bf["max_len"] = self._int_or(self.bf_max, 4)
        bf["pattern"] = self.bf_pattern.get().strip()
        bf["threads"] = self._int_or(self.bf_threads, 4)
        bf["limit_type"] = self.bf_limit_type.get()
        bf["limit_value"] = self._int_or(self.bf_limit_value, 1_000_000)
        cr["model"]["selected"] = [mid for mid, var in self._pw_model_vars.items()
                                   if var.get()]
        ump = self.user_model_path.get().strip()
        cr["model"]["user_models"] = (
            [{"id": os.path.basename(ump), "path": ump}] if ump else [])

    def _apply_cracking(self, cr):
        self.crack_enabled.set(cr.get("enabled", False))
        self.crack_method.set(cr.get("method", "bruteforce"))
        self.crack_use_hidden.set(cr.get("use_hidden_pool", False))
        self.crack_parallel.set(cr.get("parallel_files", False))
        bf = cr.get("bruteforce", {})
        self.bf_charset.set(bf.get("charset", "lower+digits"))
        self.bf_min.set(str(bf.get("min_len", 1)))
        self.bf_max.set(str(bf.get("max_len", 4)))
        self.bf_pattern.set(bf.get("pattern", ""))
        self.bf_threads.set(str(bf.get("threads", 4)))
        self.bf_limit_type.set(bf.get("limit_type", "attempts"))
        self.bf_limit_value.set(str(bf.get("limit_value", 1_000_000)))
        sel = set(cr.get("model", {}).get("selected", []))
        for mid, var in self._pw_model_vars.items():
            var.set(mid in sel)
        ums = cr.get("model", {}).get("user_models", [])
        if ums:
            first = ums[0]
            self.user_model_path.set(
                first.get("path") if isinstance(first, dict) else str(first))
        else:
            self.user_model_path.set("")

    def _confirm_discard(self):
        return messagebox.askyesno(
            about_info.APP_NAME,
            "Discard the current project and its unsaved changes?")

    def new_project(self):
        if self.project["files"] and not self._confirm_discard():
            return
        self.project = projmod.new_project("Untitled Project")
        self.project_path = None
        self._apply_project_to_ui()
        self._log("New project created.")

    def open_project(self, path=None):
        if path is None:
            path = filedialog.askopenfilename(
                title="Open project",
                filetypes=[("PDF Ai Decompile project", "*.paidproj"),
                           ("All files", "*.*")])
        if not path:
            return
        try:
            self.project = projmod.load_project(path)
            self.project_path = os.path.abspath(path)
            self._apply_project_to_ui()
            self._log(f"Opened project: {path}")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(about_info.APP_NAME,
                                 f"Could not open project:\n{exc}")

    def save_project(self):
        if not self.project_path:
            return self.save_project_as()
        self._gather_ui_to_project()
        try:
            projmod.save_project(self.project, self.project_path)
            self._log(f"Saved: {self.project_path}")
            self._update_title()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(about_info.APP_NAME,
                                 f"Could not save project:\n{exc}")

    def save_project_as(self):
        self._gather_ui_to_project()
        initial = (self.proj_name.get().strip() or "Untitled") + ".paidproj"
        path = filedialog.asksaveasfilename(
            title="Save project as", defaultextension=".paidproj",
            initialfile=initial,
            filetypes=[("PDF Ai Decompile project", "*.paidproj")])
        if not path:
            return
        try:
            self.project, out_path = projmod.save_project_as(self.project, path)
            self.project_path = out_path
            self.proj_name.set(self.project["project"]["name"])
            self._log(f"Saved: {out_path}")
            self._update_title()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(about_info.APP_NAME,
                                 f"Could not save project:\n{exc}")

    def _popup_recent(self):
        menu = tk.Menu(self, tearoff=0)
        recents = appconfig.recent_projects()
        if not recents:
            menu.add_command(label="(no recent projects)", state="disabled")
        else:
            for r in recents:
                p = r.get("path", "")
                menu.add_command(label=f"{r.get('name', 'Project')}  —  {p}",
                                 command=lambda pp=p: self.open_project(pp))
        try:
            x = self.winfo_pointerx()
            y = self.winfo_pointery()
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    # ============================ logging ============================== #
    def _log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _open_about(self):
        AboutDialog(self)

    # ============================ processing =========================== #
    def start_processing(self):
        self._gather_ui_to_project()
        sel = runner.selected_files(self.project)
        if not sel:
            messagebox.showwarning(about_info.APP_NAME,
                                   "Select at least one file in the Files tab.")
            return
        jobs = runner.jobs_for(self.project)
        if not jobs:
            messagebox.showerror(
                about_info.APP_NAME,
                "Enable at least one activity: “Modify PDF” and/or "
                "“Decompile to Text”.")
            return
        # Output-folder validation.
        if self.project["modify_pdf"]["enabled"]:
            om = self.project["output"]["modify"]
            if om["dest"] == "beside" and not om["suffix"]:
                messagebox.showerror(
                    about_info.APP_NAME,
                    "Modify PDF writes beside each PDF: add a filename suffix "
                    "so the original is not overwritten (e.g. \"_noimg\").")
                return
            if om["dest"] == "folder" and not om["folder"]:
                messagebox.showwarning(about_info.APP_NAME,
                                       "Choose an output folder for Modify PDF.")
                return
        if self.project["decompile"]["enabled"]:
            od = self.project["output"]["decompile"]
            if od["dest"] == "folder" and not od["folder"]:
                messagebox.showwarning(
                    about_info.APP_NAME,
                    "Choose an output folder for Decompile to Text.")
                return
            if not self.project["decompile"]["formats"]:
                messagebox.showwarning(
                    about_info.APP_NAME,
                    "Pick at least one Decompile format (LaTeX / Markdown).")
                return

        self._stop_flag = False
        self.run_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.progress.set(0)
        self.status_lbl.configure(text="Working…")
        self._log("-" * 64)
        self._log(f"Run: {len(sel)} file(s) × "
                  + ", ".join(runner.JOB_LABELS[j] for j in jobs))
        self.worker = threading.Thread(target=self._run_worker, daemon=True)
        self.worker.start()

    def _run_worker(self):
        def log(m):
            self.msg_queue.put(("log", m))

        def prog(f):
            self.msg_queue.put(("progress", f))
        try:
            res = runner.run(self.project, log=log, progress=prog,
                             stop=lambda: self._stop_flag,
                             project_path=self.project_path)
            self.msg_queue.put(("done", res))
        except Exception as exc:  # noqa: BLE001
            self.msg_queue.put(("log", f"FATAL: {exc}"))
            sys.stderr.write(traceback.format_exc() + "\n")
            self.msg_queue.put(("done", {"ok": 0, "fail": 1, "skip": 0}))

    def _request_stop(self):
        self._stop_flag = True
        self.status_lbl.configure(text="Stopping…")

    # ============================ queue poll =========================== #
    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.msg_queue.get_nowait()
                if kind == "log":
                    self._log(payload)
                elif kind == "progress":
                    self.progress.set(payload)
                elif kind == "done":
                    self._on_run_done(payload)
                elif kind == "crack_done":
                    self._on_crack_done()
                elif kind == "models_refresh":
                    self._render_category_models(payload)
                elif kind == "ipreview_start":
                    self._clear_insp_body()
                    if payload > self.PREVIEW_PAGE_CAP:
                        ctk.CTkLabel(
                            self.insp_body,
                            text=f"Showing first {self.PREVIEW_PAGE_CAP} of "
                                 f"{payload} pages.", text_color="gray").pack(
                            anchor="w", padx=8, pady=4)
                elif kind == "ipreview_img":
                    self._add_preview_image(*payload)
                elif kind == "ipreview_done":
                    pass
                elif kind == "ipreview_err":
                    self._clear_insp_body()
                    ctk.CTkLabel(self.insp_body, text=payload,
                                 text_color="#f87171").pack(anchor="w",
                                                            padx=10, pady=10)
        except queue.Empty:
            pass
        self.after(120, self._poll_queue)

    def _add_preview_image(self, page_no, png_bytes):
        try:
            from PIL import Image
            img = Image.open(io.BytesIO(png_bytes))
            w, h = img.size
            scale = min(1.0, 760 / max(1, w))
            cimg = ctk.CTkImage(light_image=img,
                                size=(int(w * scale), int(h * scale)))
            self._preview_imgs.append(cimg)
            ctk.CTkLabel(self.insp_body, text=f"Page {page_no}",
                         text_color="gray").pack(anchor="w", padx=8, pady=(8, 0))
            ctk.CTkLabel(self.insp_body, image=cimg, text="").pack(
                anchor="w", padx=8, pady=2)
        except Exception:
            pass

    def _on_run_done(self, res):
        self._log("-" * 64)
        self._log(f"Finished. {res['ok']} ok, {res['fail']} failed, "
                  f"{res['skip']} skipped.")
        self.run_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.status_lbl.configure(
            text="Done" if res["fail"] == 0 else "Done (errors)")
        self._render_files()   # password_source / discovered values may have changed
        if res["fail"] == 0:
            messagebox.showinfo(about_info.APP_NAME,
                                f"Finished. {res['ok']} output(s) created, "
                                f"{res['skip']} skipped.")
        else:
            messagebox.showwarning(
                about_info.APP_NAME,
                f"Finished with errors: {res['ok']} ok, {res['fail']} failed, "
                f"{res['skip']} skipped. See the log.")

    def _on_crack_done(self):
        self.run_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.status_lbl.configure(text="Ready")
        self._rebuild_perfile_rows()
        self._render_files()
        self._log("Cracking pass complete.")

    def _on_close(self):
        self.destroy()


def main():
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")
    close_pyi_splash()
    app = App()
    show_source_splash()
    app.mainloop()


if __name__ == "__main__":
    main()
