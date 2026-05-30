#!/usr/bin/env python3
"""
PDF Image Remover
=================
A desktop tool that removes images from PDF files while preserving the text
content and the original page layout.

Two removal modes
------------------
1. Images only (default)
   Removes embedded raster images (photographs, scanned figures, logos).
   Keeps vector graphics (line charts/plots, diagrams), tables, equations and
   the exact text layout. This is enough to avoid the per-upload image limit
   when sending PDFs to Claude AI, because Claude does not count vector graphics
   as images.

2. Images + figures/charts (text-only)
   Also removes vector graphics (plots, diagrams, and any vector-drawn tables),
   leaving a clean text-only PDF. Use this when you want the figures physically
   gone. Note: in many IEEE papers the plots AND the numeric table grids are
   drawn as vector graphics, so this mode removes both - the figure/table
   *captions* (which are real text) are kept.

Both modes keep text byte-identical and in the same positions, and the result
contains zero raster images. The whole-page redaction technique also removes
images that are nested inside Form XObjects (a case a per-image search can miss).

Requires: Python 3.8+  and  PyMuPDF>=1.24  (pip install PyMuPDF)
Tkinter ships with the standard CPython installer on Windows/macOS.
"""

import os
import sys
import threading
import queue
import traceback

try:
    import fitz  # PyMuPDF
except Exception:  # noqa: BLE001
    fitz = None

import tkinter as tk
from tkinter import ttk, filedialog, messagebox


APP_TITLE = "PDF Image Remover"
APP_VERSION = "1.1"
DEFAULT_SUFFIX = "_noimg"


# --------------------------------------------------------------------------- #
#  Core logic (no UI) - tested end to end on real IEEE PDFs                    #
# --------------------------------------------------------------------------- #
def _apply_redactions(page, remove_vector):
    """Apply a redaction that removes raster images (always) and, when
    ``remove_vector`` is set, vector line-art too. Text is never removed.
    Falls back gracefully on older PyMuPDF builds."""
    graphics = (
        fitz.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED
        if remove_vector
        else fitz.PDF_REDACT_LINE_ART_NONE
    )
    try:
        page.apply_redactions(
            images=fitz.PDF_REDACT_IMAGE_REMOVE,
            graphics=graphics,
            text=fitz.PDF_REDACT_TEXT_NONE,
        )
        return
    except (TypeError, AttributeError):
        pass
    try:
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_REMOVE)
    except (TypeError, AttributeError):
        page.apply_redactions()


def remove_images_from_pdf(input_path, output_path, remove_vector=False):
    """Remove images from ``input_path`` and write ``output_path``.

    If ``remove_vector`` is False (default): remove raster images only, keeping
    vector graphics, tables, equations and the exact text layout.
    If True: also remove vector graphics, producing a text-only PDF.

    Returns ``(removed, remaining)``:
        removed   - number of raster images removed
        remaining - raster images still detected afterwards (expected 0)
    """
    doc = fitz.open(input_path)
    removed = 0
    try:
        for page in doc:
            n_imgs = len(page.get_images(full=True))
            n_draws = len(page.get_drawings()) if remove_vector else 0
            if n_imgs == 0 and n_draws == 0:
                continue
            # A single whole-page redaction box. With image removal this also
            # clears images nested inside Form XObjects, which a per-image
            # rectangle search can miss. fill=False paints nothing; text and
            # (in images-only mode) vector graphics are preserved.
            try:
                page.add_redact_annot(page.rect, fill=False, cross_out=False)
            except TypeError:
                page.add_redact_annot(page.rect, fill=False)
            _apply_redactions(page, remove_vector)
            removed += n_imgs

        # garbage=4 + clean=True physically drop orphaned objects so the saved
        # file contains no image data at all.
        doc.save(output_path, garbage=4, deflate=True, clean=True)
    finally:
        doc.close()

    remaining = 0
    try:
        check = fitz.open(output_path)
        for page in check:
            remaining += len(page.get_images(full=True))
        check.close()
    except Exception:
        remaining = -1  # could not verify

    return removed, remaining


def find_pdfs_in_folder(folder, recursive=False):
    """Return a sorted list of .pdf file paths in ``folder``."""
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
#  GUI                                                                         #
# --------------------------------------------------------------------------- #
class PdfImageRemoverApp:
    def __init__(self, root):
        self.root = root
        self.pdf_paths = []
        self.output_dir = tk.StringVar(value="")
        self.suffix_var = tk.BooleanVar(value=True)
        self.recursive_var = tk.BooleanVar(value=False)
        self.mode_var = tk.StringVar(value="images")  # "images" or "all"
        self.msg_queue = queue.Queue()
        self.worker = None

        root.title(f"{APP_TITLE}  v{APP_VERSION}")
        root.geometry("700x760")
        root.minsize(640, 680)

        self._build_ui()
        self.root.after(100, self._poll_queue)

    def _build_ui(self):
        pad = {"padx": 10, "pady": 6}

        header = ttk.Frame(self.root)
        header.pack(fill="x", **pad)
        ttk.Label(header, text=APP_TITLE,
                  font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(
            header,
            text="Remove images from PDFs. Text and layout stay intact, "
                 "and the result contains no raster images.",
            foreground="#555",
        ).pack(anchor="w")

        # --- Step 1: input ---
        in_frame = ttk.LabelFrame(self.root, text="1. Choose PDFs to process")
        in_frame.pack(fill="both", expand=True, **pad)

        btn_row = ttk.Frame(in_frame)
        btn_row.pack(fill="x", padx=8, pady=8)
        ttk.Button(btn_row, text="Add PDF File(s)…",
                   command=self.add_files).pack(side="left")
        ttk.Button(btn_row, text="Add Folder…",
                   command=self.add_folder).pack(side="left", padx=6)
        ttk.Checkbutton(btn_row, text="Include subfolders",
                        variable=self.recursive_var).pack(side="left", padx=6)
        ttk.Button(btn_row, text="Remove Selected",
                   command=self.remove_selected).pack(side="right")
        ttk.Button(btn_row, text="Clear List",
                   command=self.clear_list).pack(side="right", padx=6)

        self.count_label = ttk.Label(in_frame, text="PDFs queued: 0")
        self.count_label.pack(anchor="w", padx=8)

        list_wrap = ttk.Frame(in_frame)
        list_wrap.pack(fill="both", expand=True, padx=8, pady=(2, 8))
        self.listbox = tk.Listbox(list_wrap, selectmode=tk.EXTENDED,
                                  activestyle="dotbox")
        yscroll = ttk.Scrollbar(list_wrap, orient="vertical",
                                command=self.listbox.yview)
        xscroll = ttk.Scrollbar(list_wrap, orient="horizontal",
                                command=self.listbox.xview)
        self.listbox.configure(yscrollcommand=yscroll.set,
                               xscrollcommand=xscroll.set)
        self.listbox.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        list_wrap.rowconfigure(0, weight=1)
        list_wrap.columnconfigure(0, weight=1)

        # --- Step 2: removal mode ---
        mode_frame = ttk.LabelFrame(self.root, text="2. What to remove")
        mode_frame.pack(fill="x", **pad)
        ttk.Radiobutton(
            mode_frame,
            text="Images only  —  raster photos/scanned figures. Keeps charts, "
                 "tables, equations and layout. (Recommended; clears Claude's "
                 "image limit.)",
            variable=self.mode_var, value="images",
        ).pack(anchor="w", padx=8, pady=(8, 2))
        ttk.Radiobutton(
            mode_frame,
            text="Images + figures/charts  —  also removes vector plots, "
                 "diagrams and vector-drawn tables (text-only result). "
                 "Captions are kept.",
            variable=self.mode_var, value="all",
        ).pack(anchor="w", padx=8, pady=(0, 8))

        # --- Step 3: output ---
        out_frame = ttk.LabelFrame(self.root, text="3. Choose output folder")
        out_frame.pack(fill="x", **pad)
        row = ttk.Frame(out_frame)
        row.pack(fill="x", padx=8, pady=8)
        self.out_entry = ttk.Entry(row, textvariable=self.output_dir)
        self.out_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Browse…",
                   command=self.choose_output).pack(side="left", padx=6)
        ttk.Checkbutton(
            out_frame,
            text='Append "_noimg" to output file names (recommended, '
                 "prevents overwriting originals)",
            variable=self.suffix_var,
        ).pack(anchor="w", padx=8, pady=(0, 8))

        # --- Step 4: run ---
        run_frame = ttk.Frame(self.root)
        run_frame.pack(fill="x", **pad)
        self.run_btn = ttk.Button(run_frame, text="Remove Images",
                                  command=self.start_processing)
        self.run_btn.pack(side="left")
        self.progress = ttk.Progressbar(run_frame, mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True, padx=10)

        # --- Log ---
        log_frame = ttk.LabelFrame(self.root, text="Log")
        log_frame.pack(fill="both", expand=True, **pad)
        self.log = tk.Text(log_frame, height=8, wrap="word", state="disabled",
                           background="#1e1e1e", foreground="#e0e0e0")
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical",
                                   command=self.log.yview)
        self.log.configure(yscrollcommand=log_scroll.set)
        self.log.pack(side="left", fill="both", expand=True, padx=(8, 0),
                      pady=8)
        log_scroll.pack(side="right", fill="y", pady=8, padx=(0, 8))

        if fitz is None:
            self._log("PyMuPDF is not installed. Run install_dependencies.bat "
                      "(or: pip install PyMuPDF) and restart this tool.")
            self.run_btn.state(["disabled"])

    # --------------------------- list handling ---------------------------- #
    def _refresh_list(self):
        self.listbox.delete(0, tk.END)
        for p in self.pdf_paths:
            self.listbox.insert(tk.END, p)
        self.count_label.config(text=f"PDFs queued: {len(self.pdf_paths)}")

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
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        if paths:
            n = self._add_paths(paths)
            self._log(f"Added {n} file(s).")

    def add_folder(self):
        folder = filedialog.askdirectory(title="Select a folder containing PDFs")
        if not folder:
            return
        found = find_pdfs_in_folder(folder, recursive=self.recursive_var.get())
        if not found:
            messagebox.showinfo(APP_TITLE, "No PDF files found in that folder.")
            return
        n = self._add_paths(found)
        self._log(f"Found {len(found)} PDF(s) in folder; added {n} new.")

    def remove_selected(self):
        sel = list(self.listbox.curselection())
        if not sel:
            return
        for index in reversed(sel):
            del self.pdf_paths[index]
        self._refresh_list()

    def clear_list(self):
        self.pdf_paths.clear()
        self._refresh_list()

    def choose_output(self):
        folder = filedialog.askdirectory(title="Select output folder")
        if folder:
            self.output_dir.set(folder)

    # ----------------------------- logging -------------------------------- #
    def _log(self, text):
        self.log.configure(state="normal")
        self.log.insert(tk.END, text + "\n")
        self.log.see(tk.END)
        self.log.configure(state="disabled")

    # --------------------------- processing ------------------------------- #
    def start_processing(self):
        if fitz is None:
            messagebox.showerror(APP_TITLE, "PyMuPDF is not installed.")
            return
        if not self.pdf_paths:
            messagebox.showwarning(APP_TITLE, "Add at least one PDF first.")
            return
        out_dir = self.output_dir.get().strip()
        if not out_dir:
            messagebox.showwarning(APP_TITLE, "Choose an output folder.")
            return
        if not os.path.isdir(out_dir):
            try:
                os.makedirs(out_dir, exist_ok=True)
            except Exception as exc:  # noqa: BLE001
                messagebox.showerror(APP_TITLE,
                                     f"Cannot create output folder:\n{exc}")
                return

        remove_vector = self.mode_var.get() == "all"
        self.run_btn.state(["disabled"])
        self.progress.configure(value=0, maximum=len(self.pdf_paths))
        self._log("-" * 50)
        mode_txt = ("images + figures/charts (text-only)"
                    if remove_vector else "images only")
        self._log(f"Processing {len(self.pdf_paths)} file(s) -> {out_dir}")
        self._log(f"Mode: {mode_txt}")

        files = list(self.pdf_paths)
        suffix = DEFAULT_SUFFIX if self.suffix_var.get() else ""
        self.worker = threading.Thread(
            target=self._worker, args=(files, out_dir, suffix, remove_vector),
            daemon=True,
        )
        self.worker.start()

    def _worker(self, files, out_dir, suffix, remove_vector):
        ok = fail = 0
        for i, path in enumerate(files, start=1):
            base = os.path.basename(path)
            stem, ext = os.path.splitext(base)
            out_name = f"{stem}{suffix}{ext}"
            out_path = os.path.join(out_dir, out_name)
            if os.path.abspath(out_path) == os.path.abspath(path):
                out_path = os.path.join(out_dir, f"{stem}{DEFAULT_SUFFIX}{ext}")

            try:
                removed, remaining = remove_images_from_pdf(
                    path, out_path, remove_vector=remove_vector
                )
                if remaining == 0:
                    self.msg_queue.put(
                        ("log", f"  OK  {base}  ->  {os.path.basename(out_path)} "
                                f"({removed} image(s) removed)")
                    )
                elif remaining > 0:
                    self.msg_queue.put(
                        ("log", f"  OK* {base}: {removed} removed, "
                                f"{remaining} image(s) could not be located")
                    )
                else:
                    self.msg_queue.put(
                        ("log", f"  OK  {base}: {removed} removed (verify skipped)")
                    )
                ok += 1
            except Exception as exc:  # noqa: BLE001
                fail += 1
                self.msg_queue.put(("log", f"  ERROR {base}: {exc}"))
                self.msg_queue.put(("trace", traceback.format_exc()))

            self.msg_queue.put(("progress", i))

        self.msg_queue.put(("done", (ok, fail, out_dir)))

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.msg_queue.get_nowait()
                if kind == "log":
                    self._log(payload)
                elif kind == "trace":
                    sys.stderr.write(payload + "\n")
                elif kind == "progress":
                    self.progress.configure(value=payload)
                elif kind == "done":
                    ok, fail, out_dir = payload
                    self._log("-" * 50)
                    self._log(f"Done. {ok} succeeded, {fail} failed.")
                    self.run_btn.state(["!disabled"])
                    if fail == 0:
                        messagebox.showinfo(
                            APP_TITLE,
                            f"Finished. {ok} file(s) saved to:\n{out_dir}",
                        )
                    else:
                        messagebox.showwarning(
                            APP_TITLE,
                            f"Finished with issues.\n{ok} succeeded, {fail} "
                            "failed.\nSee the log for details.",
                        )
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)


def main():
    root = tk.Tk()
    try:
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
        elif "clam" in style.theme_names():
            style.theme_use("clam")
    except Exception:
        pass
    PdfImageRemoverApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
