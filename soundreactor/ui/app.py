"""
SoundReactor GUI – built with Tkinter (ships with Python, works on Windows & Linux).
"""

from __future__ import annotations

import logging
import os
import queue
import shutil
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Optional

from core.config import Config
from core.detector import SoundDetector
from core.fingerprint import MatchResult
from core.actions import ACTION_TYPES

log = logging.getLogger(__name__)

COLORS = {
    "bg":      "#1e1e2e",
    "bg2":     "#2a2a3e",
    "bg3":     "#313145",
    "accent":  "#7aa2f7",
    "accent2": "#bb9af7",
    "green":   "#9ece6a",
    "yellow":  "#e0af68",
    "red":     "#f7768e",
    "fg":      "#c0caf5",
    "fg2":     "#a9b1d6",
    "border":  "#3d3d5c",
}


def _themed_btn(parent, text, command, color=None, **kw):
    bg = color or COLORS["accent"]
    return tk.Button(
        parent, text=text, command=command,
        bg=bg, fg="#1e1e2e", relief="flat", cursor="hand2",
        padx=10, pady=4, font=("Segoe UI", 9, "bold"),
        activebackground=COLORS["accent2"], activeforeground="#1e1e2e",
        **kw,
    )


def _label(parent, text, bold=False, fg=None, bg=None, **kw):
    font = ("Segoe UI", 9, "bold") if bold else ("Segoe UI", 9)
    return tk.Label(
        parent, text=text,
        bg=bg or COLORS["bg"],
        fg=fg or COLORS["fg"],
        font=font, **kw,
    )


# ---------------------------------------------------------------------------
# Rule Editor Dialog
# ---------------------------------------------------------------------------

class RuleEditorDialog(tk.Toplevel):
    def __init__(self, parent, config: Config, rule=None, index=-1):
        super().__init__(parent)
        self.config = config
        self.rule = dict(rule) if rule else {}
        self.index = index
        self.result_rule = None
        self.title("Edit Rule" if rule else "New Rule")
        self.configure(bg=COLORS["bg"])
        self.resizable(False, False)
        self.grab_set()
        self._build()
        self.wait_window()

    def _build(self):
        pad = {"padx": 10, "pady": 6}

        tk.Label(self, text="Rule Name:", bg=COLORS["bg"], fg=COLORS["fg"],
                 font=("Segoe UI", 9)).grid(row=0, column=0, sticky="w", **pad)
        self._name = tk.Entry(self, bg=COLORS["bg2"], fg=COLORS["fg"],
                              insertbackground=COLORS["fg"], width=35, relief="flat")
        self._name.insert(0, self.rule.get("name", ""))
        self._name.grid(row=0, column=1, sticky="ew", **pad)

        tk.Label(self, text="Sound (DB ID):", bg=COLORS["bg"], fg=COLORS["fg"],
                 font=("Segoe UI", 9)).grid(row=1, column=0, sticky="w", **pad)
        sounds = sorted(Path(self.config.sounds_db_path).glob("*"))
        sound_ids = [s.stem for s in sounds
                     if s.suffix.lower() in {".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac"}]
        self._sound_var = tk.StringVar(value=self.rule.get("sound_id", ""))
        ttk.Combobox(self, textvariable=self._sound_var,
                     values=sound_ids, state="readonly", width=33).grid(
            row=1, column=1, sticky="ew", **pad)

        tk.Label(self, text="Min match (s):", bg=COLORS["bg"], fg=COLORS["fg"],
                 font=("Segoe UI", 9)).grid(row=2, column=0, sticky="w", **pad)
        self._min_s = tk.Entry(self, bg=COLORS["bg2"], fg=COLORS["fg"],
                               insertbackground=COLORS["fg"], width=10, relief="flat")
        self._min_s.insert(0, str(self.rule.get("min_match_seconds", self.config.min_match_seconds)))
        self._min_s.grid(row=2, column=1, sticky="w", **pad)

        tk.Label(self, text="Cooldown (s):", bg=COLORS["bg"], fg=COLORS["fg"],
                 font=("Segoe UI", 9)).grid(row=3, column=0, sticky="w", **pad)
        self._cool = tk.Entry(self, bg=COLORS["bg2"], fg=COLORS["fg"],
                              insertbackground=COLORS["fg"], width=10, relief="flat")
        self._cool.insert(0, str(self.rule.get("cooldown_seconds", self.config.cooldown_seconds)))
        self._cool.grid(row=3, column=1, sticky="w", **pad)

        self._enabled = tk.BooleanVar(value=self.rule.get("enabled", True))
        tk.Checkbutton(self, text="Enabled", variable=self._enabled,
                       bg=COLORS["bg"], fg=COLORS["fg"], selectcolor=COLORS["bg2"],
                       activebackground=COLORS["bg"],
                       font=("Segoe UI", 9)).grid(row=4, column=1, sticky="w", **pad)

        self._trigger_once = tk.BooleanVar(value=self.rule.get("trigger_once", False))
        tk.Checkbutton(self, text="Trigger once per session (never repeats until restart)",
                       variable=self._trigger_once,
                       bg=COLORS["bg"], fg=COLORS["yellow"], selectcolor=COLORS["bg2"],
                       activebackground=COLORS["bg"],
                       font=("Segoe UI", 9)).grid(row=5, column=1, sticky="w", **pad)

        tk.Label(self, text="Actions:", bg=COLORS["bg"], fg=COLORS["fg"],
                 font=("Segoe UI", 9, "bold")).grid(row=6, column=0, sticky="nw", **pad)

        af = tk.Frame(self, bg=COLORS["bg2"])
        af.grid(row=6, column=1, sticky="ew", **pad)

        self._actions_list = tk.Listbox(af, bg=COLORS["bg2"], fg=COLORS["fg"],
                                        selectbackground=COLORS["accent"],
                                        height=5, width=40, relief="flat")
        self._actions_list.pack(side="left", fill="both", expand=True)

        self._actions_data = list(self.rule.get("actions", []))
        for a in self._actions_data:
            self._actions_list.insert("end", self._action_label(a))

        bf = tk.Frame(af, bg=COLORS["bg2"])
        bf.pack(side="right", fill="y", padx=4)
        _themed_btn(bf, "+ Add",  self._add_action,  color=COLORS["green"]).pack(pady=2)
        _themed_btn(bf, "✎ Edit", self._edit_action, color=COLORS["yellow"]).pack(pady=2)
        _themed_btn(bf, "✕ Del",  self._del_action,  color=COLORS["red"]).pack(pady=2)

        br = tk.Frame(self, bg=COLORS["bg"])
        br.grid(row=7, column=0, columnspan=2, pady=12)
        _themed_btn(br, "Save",   self._save,    color=COLORS["green"]).pack(side="left", padx=6)
        _themed_btn(br, "Cancel", self.destroy,  color=COLORS["red"]).pack(side="left", padx=6)

    @staticmethod
    def _action_label(a):
        atype = a.get("type", "?")
        label = ACTION_TYPES.get(atype, {}).get("label", atype)
        params = {k: v for k, v in a.items() if k != "type"}
        return f"{label} {params}" if params else label

    def _add_action(self):
        dlg = ActionEditorDialog(self, self.config)
        if dlg.result_action:
            self._actions_data.append(dlg.result_action)
            self._actions_list.insert("end", self._action_label(dlg.result_action))

    def _edit_action(self):
        sel = self._actions_list.curselection()
        if not sel:
            return
        idx = sel[0]
        dlg = ActionEditorDialog(self, self.config, self._actions_data[idx])
        if dlg.result_action:
            self._actions_data[idx] = dlg.result_action
            self._actions_list.delete(idx)
            self._actions_list.insert(idx, self._action_label(dlg.result_action))

    def _del_action(self):
        sel = self._actions_list.curselection()
        if not sel:
            return
        self._actions_data.pop(sel[0])
        self._actions_list.delete(sel[0])

    def _save(self):
        name = self._name.get().strip()
        if not name:
            messagebox.showerror("Error", "Rule name is required.", parent=self)
            return
        sound_id = self._sound_var.get().strip()
        if not sound_id:
            messagebox.showerror("Error", "Select a sound from the database.", parent=self)
            return
        try:
            min_s = float(self._min_s.get())
            cool  = float(self._cool.get())
        except ValueError:
            messagebox.showerror("Error", "Min match / cooldown must be numbers.", parent=self)
            return
        self.result_rule = {
            "name": name,
            "sound_id": sound_id,
            "enabled": self._enabled.get(),
            "trigger_once": self._trigger_once.get(),
            "min_match_seconds": min_s,
            "cooldown_seconds": cool,
            "actions": self._actions_data,
        }
        self.destroy()


# ---------------------------------------------------------------------------
# Action Editor Dialog
# ---------------------------------------------------------------------------

class ActionEditorDialog(tk.Toplevel):
    def __init__(self, parent, config: Config, action=None):
        super().__init__(parent)
        self.config = config
        self.action = dict(action) if action else {}
        self.result_action = None
        self.title("Edit Action" if action else "New Action")
        self.configure(bg=COLORS["bg"])
        self.resizable(False, False)
        self.grab_set()
        self._build()
        self.wait_window()

    def _build(self):
        pad = {"padx": 10, "pady": 5}

        tk.Label(self, text="Action Type:", bg=COLORS["bg"], fg=COLORS["fg"],
                 font=("Segoe UI", 9)).grid(row=0, column=0, sticky="w", **pad)

        self._type_var = tk.StringVar(value=self.action.get("type", "volume_set"))
        cb = ttk.Combobox(self, textvariable=self._type_var,
                          values=list(ACTION_TYPES.keys()), state="readonly", width=30)
        cb.grid(row=0, column=1, **pad)
        cb.bind("<<ComboboxSelected>>", lambda _: self._refresh_params())

        self._param_frame = tk.Frame(self, bg=COLORS["bg"])
        self._param_frame.grid(row=1, column=0, columnspan=2, sticky="ew")
        self._param_widgets = {}
        self._refresh_params()

        br = tk.Frame(self, bg=COLORS["bg"])
        br.grid(row=2, column=0, columnspan=2, pady=10)
        _themed_btn(br, "OK",     self._save,    color=COLORS["green"]).pack(side="left", padx=5)
        _themed_btn(br, "Cancel", self.destroy,  color=COLORS["red"]).pack(side="left", padx=5)

    def _refresh_params(self):
        for w in self._param_frame.winfo_children():
            w.destroy()
        self._param_widgets.clear()
        atype = self._type_var.get()
        for row_i, (key, kind, default, desc) in enumerate(
                ACTION_TYPES.get(atype, {}).get("params", [])):
            tk.Label(self._param_frame, text=f"{desc}:", bg=COLORS["bg"],
                     fg=COLORS["fg"], font=("Segoe UI", 9)).grid(
                row=row_i, column=0, sticky="w", padx=10, pady=4)
            existing = self.action.get(key, default)
            if kind == "bool":
                var = tk.BooleanVar(value=bool(existing))
                tk.Checkbutton(self._param_frame, variable=var,
                               bg=COLORS["bg"], selectcolor=COLORS["bg2"],
                               activebackground=COLORS["bg"]).grid(
                    row=row_i, column=1, sticky="w", padx=10, pady=4)
            else:
                var = tk.StringVar(value=str(existing))
                tk.Entry(self._param_frame, textvariable=var,
                         bg=COLORS["bg2"], fg=COLORS["fg"],
                         insertbackground=COLORS["fg"], relief="flat", width=30).grid(
                    row=row_i, column=1, sticky="w", padx=10, pady=4)
            self._param_widgets[key] = (kind, var)

    def _save(self):
        atype = self._type_var.get()
        result = {"type": atype}
        for key, (kind, var) in self._param_widgets.items():
            raw = var.get()
            if kind == "int":
                try:
                    result[key] = int(raw)
                except ValueError:
                    messagebox.showerror("Error", f"'{key}' must be an integer.", parent=self)
                    return
            elif kind == "float":
                try:
                    result[key] = float(raw)
                except ValueError:
                    messagebox.showerror("Error", f"'{key}' must be a number.", parent=self)
                    return
            elif kind == "bool":
                result[key] = bool(raw)
            else:
                result[key] = raw
        self.result_action = result
        self.destroy()


# ---------------------------------------------------------------------------
# Settings Dialog
# ---------------------------------------------------------------------------

class SettingsDialog(tk.Toplevel):
    def __init__(self, parent, config: Config, detector: SoundDetector):
        super().__init__(parent)
        self.config = config
        self.detector = detector
        self.title("Settings")
        self.configure(bg=COLORS["bg"])
        self.resizable(False, False)
        self.grab_set()
        self._build()

    def _build(self):
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=10, pady=10)

        audio_tab = tk.Frame(nb, bg=COLORS["bg"])
        nb.add(audio_tab, text="Audio")
        self._build_audio_tab(audio_tab)

        det_tab = tk.Frame(nb, bg=COLORS["bg"])
        nb.add(det_tab, text="Detection")
        self._build_detection_tab(det_tab)

        _themed_btn(self, "Save & Close", self._save,
                    color=COLORS["green"]).pack(pady=8)

    def _build_audio_tab(self, parent):
        pad = {"padx": 12, "pady": 6}

        tk.Label(parent, text="Input Device:", bg=COLORS["bg"],
                 fg=COLORS["fg"]).grid(row=0, column=0, sticky="w", **pad)

        devices = self.detector.list_audio_devices()
        device_names = ["(system default)"]
        if devices is not None:
            try:
                for i, d in enumerate(devices):
                    name = d["name"] if isinstance(d, dict) else getattr(d, "name", str(d))
                    device_names.append(f"{i}: {name}")
            except Exception:
                pass

        self._device_var = tk.StringVar(value=device_names[0])
        ttk.Combobox(parent, textvariable=self._device_var,
                     values=device_names, width=40, state="readonly").grid(
            row=0, column=1, sticky="ew", **pad)

        tk.Label(parent, text="Sample Rate:", bg=COLORS["bg"],
                 fg=COLORS["fg"]).grid(row=1, column=0, sticky="w", **pad)
        self._sr = tk.Entry(parent, bg=COLORS["bg2"], fg=COLORS["fg"],
                            insertbackground=COLORS["fg"], relief="flat", width=12)
        self._sr.insert(0, str(self.config.sample_rate))
        self._sr.grid(row=1, column=1, sticky="w", **pad)

        tk.Label(parent, text="Chunk Duration (s):", bg=COLORS["bg"],
                 fg=COLORS["fg"]).grid(row=2, column=0, sticky="w", **pad)
        self._chunk = tk.Entry(parent, bg=COLORS["bg2"], fg=COLORS["fg"],
                               insertbackground=COLORS["fg"], relief="flat", width=12)
        self._chunk.insert(0, str(self.config.chunk_duration))
        self._chunk.grid(row=2, column=1, sticky="w", **pad)

    def _build_detection_tab(self, parent):
        pad = {"padx": 12, "pady": 6}
        fields = [
            ("Match Threshold (0–1):", "fingerprinting", "match_threshold"),
            ("Min Match Seconds:",     "fingerprinting", "min_match_seconds"),
            ("Cooldown Seconds:",      "fingerprinting", "cooldown_seconds"),
        ]
        self._det_entries = {}
        for row_i, (label, *keys) in enumerate(fields):
            tk.Label(parent, text=label, bg=COLORS["bg"],
                     fg=COLORS["fg"]).grid(row=row_i, column=0, sticky="w", **pad)
            e = tk.Entry(parent, bg=COLORS["bg2"], fg=COLORS["fg"],
                         insertbackground=COLORS["fg"], relief="flat", width=12)
            e.insert(0, str(self.config.get(*keys, default="")))
            e.grid(row=row_i, column=1, sticky="w", **pad)
            self._det_entries[tuple(keys)] = e

        tk.Label(parent, text="Algorithm:", bg=COLORS["bg"],
                 fg=COLORS["fg"]).grid(row=len(fields), column=0, sticky="w", **pad)
        self._algo_var = tk.StringVar(
            value=self.config.get("fingerprinting", "algorithm", default="chromaprint"))
        ttk.Combobox(parent, textvariable=self._algo_var,
                     values=["chromaprint", "spectrogram"],
                     state="readonly", width=18).grid(
            row=len(fields), column=1, sticky="w", **pad)

    def _save(self):
        try:
            sr    = int(self._sr.get())
            chunk = float(self._chunk.get())
        except ValueError:
            messagebox.showerror("Error", "Invalid numeric value.", parent=self)
            return
        self.config.set("audio", "sample_rate", sr)
        self.config.set("audio", "chunk_duration", chunk)
        for keys, entry in self._det_entries.items():
            try:
                self.config.set(*keys, float(entry.get()))
            except ValueError:
                pass
        self.config.set("fingerprinting", "algorithm", self._algo_var.get())
        self.destroy()


# ---------------------------------------------------------------------------
# Logging handler → UI queue
# ---------------------------------------------------------------------------

class _TkLogHandler(logging.Handler):
    def __init__(self, q: queue.Queue):
        super().__init__()
        self._queue = q

    def emit(self, record):
        msg = self.format(record)
        tag = "err" if record.levelno >= logging.ERROR else "info"
        try:
            self._queue.put_nowait(("log", msg, tag))
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Main Application Window
# ---------------------------------------------------------------------------

class SoundReactorApp:
    def __init__(self, config: Config):
        self.config = config
        self.detector = SoundDetector(config)
        self._ui_queue: queue.Queue = queue.Queue()
        self._running = False

        self.root = tk.Tk()
        self._build_ui()                    # builds ALL widgets first
        self._bind_detector_callbacks()     # then wire up callbacks

    # ------------------------------------------------------------------
    # UI construction  (log panel first so _log_text exists early)
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = self.root
        root.title("SoundReactor")
        root.configure(bg=COLORS["bg"])
        root.geometry("960x680")
        root.minsize(700, 520)

        style = ttk.Style()
        style.theme_use("default")
        style.configure("TCombobox",
                        fieldbackground=COLORS["bg2"],
                        background=COLORS["bg2"],
                        foreground=COLORS["fg"],
                        selectbackground=COLORS["accent"],
                        selectforeground=COLORS["bg"])

        # 1. Toolbar
        self._build_toolbar(root)

        # 2. Log panel (bottom) – built BEFORE the paned area so _log_text exists
        log_frame = tk.Frame(root, bg=COLORS["bg"])
        log_frame.pack(side="bottom", fill="x", padx=6, pady=(0, 6))
        self._build_log_panel(log_frame)

        # 3. Paned area (middle)
        paned = tk.PanedWindow(root, orient="horizontal",
                               bg=COLORS["border"], sashrelief="flat", sashwidth=4)
        paned.pack(fill="both", expand=True, padx=6, pady=6)

        left = tk.Frame(paned, bg=COLORS["bg"])
        paned.add(left, minsize=240, width=280)
        self._build_db_panel(left)

        right = tk.Frame(paned, bg=COLORS["bg"])
        paned.add(right, minsize=320)
        self._build_rules_panel(right)

    def _build_toolbar(self, root):
        toolbar = tk.Frame(root, bg=COLORS["bg2"], height=48)
        toolbar.pack(side="top", fill="x")

        tk.Label(toolbar, text="🎧 SoundReactor",
                 bg=COLORS["bg2"], fg=COLORS["accent"],
                 font=("Segoe UI", 12, "bold")).pack(side="left", padx=14, pady=8)

        self._start_btn = _themed_btn(toolbar, "▶ Start",
                                      self._start_listening, color=COLORS["green"])
        self._start_btn.pack(side="left", padx=4, pady=8)

        self._stop_btn = _themed_btn(toolbar, "■ Stop",
                                     self._stop_listening, color=COLORS["red"])
        self._stop_btn.pack(side="left", padx=4, pady=8)
        self._stop_btn.config(state="disabled")

        self._auto_start_var = tk.BooleanVar(
            value=self.config.get("ui", "auto_start", default=False)
        )
        tk.Checkbutton(
            toolbar, text="Auto-start", variable=self._auto_start_var,
            command=self._toggle_auto_start,
            bg=COLORS["bg2"], fg=COLORS["fg"], selectcolor=COLORS["bg3"],
            activebackground=COLORS["bg2"], activeforeground=COLORS["fg"],
            font=("Segoe UI", 9),
        ).pack(side="right", padx=6, pady=8)

        _themed_btn(toolbar, "⚙ Settings", self._open_settings,
                    color=COLORS["bg3"]).pack(side="right", padx=10, pady=8)

        self._status_var = tk.StringVar(value="Ready.")
        tk.Label(toolbar, textvariable=self._status_var,
                 bg=COLORS["bg2"], fg=COLORS["fg2"],
                 font=("Segoe UI", 9)).pack(side="right", padx=10)

    def _build_db_panel(self, parent):
        hdr = tk.Frame(parent, bg=COLORS["bg2"])
        hdr.pack(fill="x")
        tk.Label(hdr, text="  Sound Database",
                 bg=COLORS["bg2"], fg=COLORS["accent"],
                 font=("Segoe UI", 10, "bold")).pack(side="left", pady=6)

        btn_row = tk.Frame(parent, bg=COLORS["bg"])
        btn_row.pack(fill="x", pady=(4, 0))
        _themed_btn(btn_row, "+ Add",     self._add_sound,  color=COLORS["green"]).pack(side="left", padx=4)
        _themed_btn(btn_row, "🔄 Reload", self._reload_db,  color=COLORS["accent"]).pack(side="left", padx=4)
        _themed_btn(btn_row, "✕ Remove",  self._remove_sound, color=COLORS["red"]).pack(side="left", padx=4)

        self._db_listbox = tk.Listbox(
            parent, bg=COLORS["bg2"], fg=COLORS["fg"],
            selectbackground=COLORS["accent"], relief="flat",
            activestyle="none", font=("Segoe UI", 9),
        )
        self._db_listbox.pack(fill="both", expand=True, padx=4, pady=4)
        self._refresh_db_list()

        self._match_indicator = tk.Label(
            parent, text="No match",
            bg=COLORS["bg"], fg=COLORS["fg2"],
            font=("Segoe UI", 9, "italic"),
        )
        self._match_indicator.pack(pady=4)

    def _build_rules_panel(self, parent):
        hdr = tk.Frame(parent, bg=COLORS["bg2"])
        hdr.pack(fill="x")
        tk.Label(hdr, text="  Detection Rules",
                 bg=COLORS["bg2"], fg=COLORS["accent2"],
                 font=("Segoe UI", 10, "bold")).pack(side="left", pady=6)

        btn_row = tk.Frame(parent, bg=COLORS["bg"])
        btn_row.pack(fill="x", pady=(4, 0))
        _themed_btn(btn_row, "+ New Rule",  self._new_rule,    color=COLORS["green"]).pack(side="left", padx=4)
        _themed_btn(btn_row, "✎ Edit",      self._edit_rule,   color=COLORS["yellow"]).pack(side="left", padx=4)
        _themed_btn(btn_row, "✕ Delete",    self._delete_rule, color=COLORS["red"]).pack(side="left", padx=4)
        _themed_btn(btn_row, "▲/▼ Toggle",  self._toggle_rule, color=COLORS["accent"]).pack(side="left", padx=4)

        cols = ("name", "sound", "actions", "status")
        self._rules_tree = ttk.Treeview(parent, columns=cols, show="headings", height=14)
        self._rules_tree.heading("name",    text="Rule Name")
        self._rules_tree.heading("sound",   text="Sound ID")
        self._rules_tree.heading("actions", text="Actions")
        self._rules_tree.heading("status",  text="State")
        self._rules_tree.column("name",    width=160, stretch=True)
        self._rules_tree.column("sound",   width=130)
        self._rules_tree.column("actions", width=130)
        self._rules_tree.column("status",  width=60, anchor="center")
        self._rules_tree.pack(fill="both", expand=True, padx=4, pady=4)
        self._refresh_rules_list()

    def _build_log_panel(self, parent):
        hdr = tk.Frame(parent, bg=COLORS["bg2"])
        hdr.pack(fill="x")
        tk.Label(hdr, text="  Activity Log",
                 bg=COLORS["bg2"], fg=COLORS["fg2"],
                 font=("Segoe UI", 9, "bold")).pack(side="left", pady=4)
        _themed_btn(hdr, "Clear", self._clear_log,
                    color=COLORS["bg3"]).pack(side="right", padx=6, pady=4)

        inner = tk.Frame(parent, bg=COLORS["bg"])
        inner.pack(fill="x")

        self._log_text = tk.Text(
            inner, height=7, bg=COLORS["bg2"], fg=COLORS["fg"],
            relief="flat", font=("Consolas", 8), state="disabled", wrap="word",
        )
        scroll = ttk.Scrollbar(inner, command=self._log_text.yview)
        self._log_text.configure(yscrollcommand=scroll.set)
        self._log_text.pack(side="left", fill="x", expand=True)
        scroll.pack(side="right", fill="y")

        self._log_text.tag_config("match", foreground=COLORS["green"])
        self._log_text.tag_config("fire",  foreground=COLORS["yellow"])
        self._log_text.tag_config("err",   foreground=COLORS["red"])
        self._log_text.tag_config("info",  foreground=COLORS["fg2"])

        handler = _TkLogHandler(self._ui_queue)
        handler.setLevel(logging.INFO)
        logging.getLogger().addHandler(handler)

    # ------------------------------------------------------------------
    # Detector callbacks
    # ------------------------------------------------------------------

    def _bind_detector_callbacks(self):
        def on_match(result: MatchResult):
            self._ui_queue.put(("match", result))

        def on_fire(rule_name: str, result: MatchResult):
            self._ui_queue.put(("fire", rule_name, result))

        def on_status(msg: str):
            self._ui_queue.put(("status", msg))

        self.detector.on_match   = on_match
        self.detector.on_rule_fired = on_fire
        self.detector.on_status  = on_status

    # ------------------------------------------------------------------
    # Control
    # ------------------------------------------------------------------

    def _start_listening(self):
        if self._running:
            return
        self._running = True
        self._start_btn.config(state="disabled")
        self._stop_btn.config(state="normal")
        threading.Thread(target=self.detector.start, daemon=True).start()
        self._log("Detector started.", "info")

    def _stop_listening(self):
        if not self._running:
            return
        self._running = False
        self._start_btn.config(state="normal")
        self._stop_btn.config(state="disabled")
        threading.Thread(target=self.detector.stop, daemon=True).start()
        self._log("Detector stopped.", "info")

    def _toggle_auto_start(self):
        self.config.set("ui", "auto_start", self._auto_start_var.get())

    # ------------------------------------------------------------------
    # Database panel
    # ------------------------------------------------------------------

    def _add_sound(self):
        paths = filedialog.askopenfilenames(
            title="Add Sound Files",
            filetypes=[("Audio files", "*.mp3 *.wav *.ogg *.flac *.m4a *.aac"),
                       ("All files", "*.*")],
        )
        if not paths:
            return
        db_path = self.config.sounds_db_path
        db_path.mkdir(parents=True, exist_ok=True)
        for src in paths:
            dest = db_path / Path(src).name
            if not dest.exists():
                shutil.copy2(src, dest)
        self._reload_db()

    def _reload_db(self):
        def _do():
            self.detector.reload_database()
            self._ui_queue.put(("refresh_db",))
        threading.Thread(target=_do, daemon=True).start()

    def _remove_sound(self):
        sel = self._db_listbox.curselection()
        if not sel:
            return
        sid = self._db_listbox.get(sel[0])
        if not messagebox.askyesno("Remove", f"Remove '{sid}' from database?"):
            return
        db_path = self.config.sounds_db_path
        for ext in (".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac"):
            f = db_path / (sid + ext)
            if f.exists():
                f.unlink()
        self.detector.db.remove(sid)
        self._refresh_db_list()
        self._log(f"Removed sound: {sid}", "info")

    def _refresh_db_list(self):
        self._db_listbox.delete(0, "end")
        for sid in sorted(self.detector.db.list_sounds()):
            self._db_listbox.insert("end", sid)

    # ------------------------------------------------------------------
    # Rules panel
    # ------------------------------------------------------------------

    def _new_rule(self):
        dlg = RuleEditorDialog(self.root, self.config)
        if dlg.result_rule:
            self.config.add_rule(dlg.result_rule)
            self._refresh_rules_list()
            self._log(f"Rule added: {dlg.result_rule['name']}", "info")

    def _edit_rule(self):
        sel = self._rules_tree.selection()
        if not sel:
            return
        idx = self._rules_tree.index(sel[0])
        dlg = RuleEditorDialog(self.root, self.config, self.config.rules[idx], idx)
        if dlg.result_rule:
            self.config.update_rule(idx, dlg.result_rule)
            self._refresh_rules_list()

    def _delete_rule(self):
        sel = self._rules_tree.selection()
        if not sel:
            return
        idx  = self._rules_tree.index(sel[0])
        name = self.config.rules[idx].get("name", "?")
        if messagebox.askyesno("Delete Rule", f"Delete rule '{name}'?"):
            self.config.delete_rule(idx)
            self._refresh_rules_list()

    def _toggle_rule(self):
        sel = self._rules_tree.selection()
        if not sel:
            return
        idx  = self._rules_tree.index(sel[0])
        rule = dict(self.config.rules[idx])
        rule["enabled"] = not rule.get("enabled", True)
        self.config.update_rule(idx, rule)
        self._refresh_rules_list()

    def _refresh_rules_list(self):
        for item in self._rules_tree.get_children():
            self._rules_tree.delete(item)
        for rule in self.config.rules:
            actions_summary = ", ".join(
                ACTION_TYPES.get(a.get("type", ""), {}).get("label", a.get("type", ""))
                for a in rule.get("actions", [])
            )
            enabled = rule.get("enabled", True)
            once    = rule.get("trigger_once", False)
            if not enabled:
                status = "✗ off"
            elif once:
                status = "✓ once"
            else:
                status = "✓ loop"
            self._rules_tree.insert("", "end", values=(
                rule.get("name", ""),
                rule.get("sound_id", ""),
                actions_summary or "—",
                status,
            ))

    def _open_settings(self):
        SettingsDialog(self.root, self.config, self.detector)

    # ------------------------------------------------------------------
    # Log
    # ------------------------------------------------------------------

    def _log(self, msg: str, tag: str = "info"):
        ts   = time.strftime("%H:%M:%S")
        line = f"[{ts}] {msg}\n"
        self._log_text.config(state="normal")
        self._log_text.insert("end", line, tag)
        max_lines = self.config.get("ui", "log_lines", default=200)
        lines = int(self._log_text.index("end-1c").split(".")[0])
        if lines > max_lines:
            self._log_text.delete("1.0", f"{lines - max_lines}.0")
        self._log_text.see("end")
        self._log_text.config(state="disabled")

    def _clear_log(self):
        self._log_text.config(state="normal")
        self._log_text.delete("1.0", "end")
        self._log_text.config(state="disabled")

    # ------------------------------------------------------------------
    # Queue pump
    # ------------------------------------------------------------------

    def _pump_queue(self):
        try:
            while True:
                item = self._ui_queue.get_nowait()
                self._handle_event(item)
        except queue.Empty:
            pass
        self.root.after(100, self._pump_queue)

    def _handle_event(self, item):
        tag = item[0]
        if tag == "match":
            result: MatchResult = item[1]
            self._match_indicator.config(
                text=f"🎵 {result.sound_id}  ({result.similarity:.0%})",
                fg=COLORS["green"],
            )
            self._log(f"Match: {result.sound_id}  ({result.similarity:.0%})", "match")
        elif tag == "fire":
            rule_name, result = item[1], item[2]
            self._log(f"🔥 Rule fired: '{rule_name}' → {result.sound_id}", "fire")
        elif tag == "status":
            self._status_var.set(item[1])
        elif tag == "refresh_db":
            self._refresh_db_list()
        elif tag == "log":
            self._log(item[1], item[2])

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(self):
        self.root.after(100, self._pump_queue)
        if self.config.get("ui", "auto_start", default=False):
            self.root.after(300, self._start_listening)
        self.root.mainloop()
