from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from pathlib import Path
import colorsys
import http.server
import json
import os
import queue
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import webbrowser

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox
    import customtkinter as ctk
except Exception as exc:  # pragma: no cover - platform/runtime guard
    tk = None
    filedialog = None
    messagebox = None
    ctk = None
    TK_IMPORT_ERROR = exc
else:
    TK_IMPORT_ERROR = None

_CTK_FRAME_BASE = ctk.CTkFrame if ctk is not None else object

_KI_COLORS = {
    "plum_dark": "#4F0433",
    "orange": "#FF876F",
    "light_orange": "#FEEEEB",
    "light_blue": "#EDF4F4",
    "plum": "#870052",
}

_KAROSPACE_LIGHT_PALETTE = {
    "plum_dark": _KI_COLORS["plum_dark"],
    "orange": _KI_COLORS["orange"],
    "light_orange": _KI_COLORS["light_orange"],
    "light_blue": _KI_COLORS["light_blue"],
    "plum": _KI_COLORS["plum"],
    "background": "#ffffff",
    "text": "#1a1d23",
    "panel_bg": "#ffffff",
    "border": "#d8dbe1",
    "input_bg": "#f8f9fb",
    "muted": "#6b7280",
    "hover_bg": "#e6e8ed",
    "accent": _KI_COLORS["plum"],
    "accent_strong": _KI_COLORS["plum_dark"],
    "secondary": _KI_COLORS["plum"],
    "on_secondary": "#ffffff",
    "on_secondary_idle": _KI_COLORS["plum"],
    "danger": "#c9252d",
    "danger_hover": "#a51f25",
    "on_danger": "#ffffff",
    "on_accent": "#ffffff",
    "hero_bg": "#ffffff",
}

_KAROSPACE_DARK_PALETTE = {
    "plum_dark": _KI_COLORS["plum_dark"],
    "orange": _KI_COLORS["orange"],
    "light_orange": _KI_COLORS["light_orange"],
    "light_blue": _KI_COLORS["light_blue"],
    "plum": _KI_COLORS["plum"],
    "background": "#000000",
    "text": "#e8eaef",
    "panel_bg": "#1c1d22",
    "border": "#2e3038",
    "input_bg": "#24262c",
    "muted": "#9ca3af",
    "hover_bg": "#282a31",
    "accent": _KI_COLORS["orange"],
    "accent_strong": _KI_COLORS["plum"],
    "secondary": _KI_COLORS["orange"],
    "on_secondary": "#1a1d23",
    "on_secondary_idle": "#ffffff",
    "danger": "#e04b53",
    "danger_hover": "#b9333a",
    "on_danger": "#ffffff",
    "on_accent": "#1a1a1a",
    "hero_bg": "#000000",
}


def _palette_for_mode(mode: str) -> dict[str, str]:
    return (
        dict(_KAROSPACE_DARK_PALETTE)
        if str(mode).strip().lower() == "dark"
        else dict(_KAROSPACE_LIGHT_PALETTE)
    )


def _shift_hex_luminance(hex_color: str, points: float) -> str:
    return _transform_hex_luminance(hex_color, points=points)


def _set_hex_luminance(hex_color: str, luminance_percent: float) -> str:
    return _transform_hex_luminance(hex_color, absolute=luminance_percent)


def _is_dark_palette(palette: dict[str, str]) -> bool:
    return str(palette.get("background", "")).strip().lower() == "#000000"


def _secondary_idle_color(palette: dict[str, str]) -> str:
    return _set_hex_luminance(palette["secondary"], 5 if _is_dark_palette(palette) else 99)


def _transform_hex_luminance(
    hex_color: str,
    *,
    points: float | None = None,
    absolute: float | None = None,
) -> str:
    cleaned = hex_color.strip().lstrip("#")
    if len(cleaned) != 6:
        return hex_color
    try:
        red = int(cleaned[0:2], 16) / 255
        green = int(cleaned[2:4], 16) / 255
        blue = int(cleaned[4:6], 16) / 255
    except ValueError:
        return hex_color

    hue, luminance, saturation = colorsys.rgb_to_hls(red, green, blue)
    if absolute is not None:
        luminance = absolute / 100.0
    elif points is not None:
        luminance = luminance + (points / 100.0)
    luminance = max(0.0, min(1.0, luminance))
    red, green, blue = colorsys.hls_to_rgb(hue, luminance, saturation)
    return f"#{round(red * 255):02x}{round(green * 255):02x}{round(blue * 255):02x}"


def _ui_font() -> str:
    """Return the preferred UI font family for the current platform."""
    if sys.platform == "darwin":
        return "Helvetica Neue"
    return "Segoe UI"


def _mono_font() -> str:
    """Return the preferred monospace font family for the current platform."""
    if sys.platform == "darwin":
        return "Menlo"
    return "Consolas"


def _ctk_theme_config(palette: dict[str, str]) -> dict[str, dict[str, object]]:
    ui = _ui_font()
    mono = _mono_font()
    return {
        "root": {"fg_color": palette["background"]},
        "root_frame": {"fg_color": palette["background"], "corner_radius": 0},
        "card_frame": {
            "fg_color": palette["panel_bg"],
            "corner_radius": 16,
            "border_width": 1,
            "border_color": palette["border"],
        },
        "hero_card": {
            "fg_color": palette.get("hero_bg", palette["panel_bg"]),
            "corner_radius": 20,
            "border_width": 2,
            "border_color": palette["secondary"],
        },
        "highlight_card": {
            "fg_color": palette["panel_bg"],
            "corner_radius": 14,
            "border_width": 1,
            "border_color": palette["secondary"],
        },
        "sub_frame": {"fg_color": "transparent", "corner_radius": 0},
        "section_label": {
            "font": (ui, 11, "bold"),
            "text_color": palette["secondary"],
            "fg_color": "transparent",
            "anchor": "w",
        },
        "hero_label": {
            "font": (ui, 30, "bold"),
            "text_color": palette["text"],
            "fg_color": "transparent",
            "anchor": "w",
        },
        "header_label": {
            "font": (ui, 18, "bold"),
            "text_color": palette["text"],
            "fg_color": "transparent",
            "anchor": "w",
        },
        "subheader_label": {
            "font": (ui, 12),
            "text_color": palette["muted"],
            "fg_color": "transparent",
            "anchor": "w",
        },
        "field_label": {
            "font": (ui, 12, "bold"),
            "text_color": palette["text"],
            "fg_color": "transparent",
            "anchor": "w",
        },
        "body_label": {
            "font": (ui, 11),
            "text_color": palette["text"],
            "fg_color": "transparent",
            "anchor": "w",
        },
        "primary_button": {
            "fg_color": palette["accent"],
            "hover_color": palette["accent_strong"],
            "text_color": palette.get("on_accent", "#ffffff"),
            "corner_radius": 12,
            "font": (ui, 12, "bold"),
            "height": 42,
            "border_width": 0,
        },
        "secondary_button": {
            "fg_color": _secondary_idle_color(palette),
            "hover_color": palette["secondary"],
            "text_color": palette.get("on_secondary_idle", palette["on_secondary"]),
            "corner_radius": 10,
            "font": (ui, 11),
            "height": 40,
            "border_width": 1,
            "border_color": palette["secondary"],
        },
        "pill_label": {
            "font": (ui, 10, "bold"),
            "text_color": palette.get("on_accent", "#ffffff"),
            "fg_color": palette["accent"],
            "corner_radius": 999,
            "padx": 12,
            "pady": 6,
        },
        "muted_pill_label": {
            "font": (ui, 10, "bold"),
            "text_color": palette["text"],
            "fg_color": palette["hover_bg"],
            "corner_radius": 999,
            "padx": 12,
            "pady": 6,
        },
        "entry": {
            "fg_color": palette["input_bg"],
            "text_color": palette["text"],
            "placeholder_text_color": palette["muted"],
            "border_color": palette["border"],
            "border_width": 1,
            "corner_radius": 10,
            "height": 40,
            "font": (ui, 12),
        },
        "combo": {
            "fg_color": palette["input_bg"],
            "text_color": palette["text"],
            "button_color": palette["hover_bg"],
            "button_hover_color": palette["accent"],
            "dropdown_fg_color": palette["panel_bg"],
            "dropdown_text_color": palette["text"],
            "dropdown_hover_color": palette["hover_bg"],
            "corner_radius": 10,
            "font": (ui, 12),
        },
        "checkbox": {
            "fg_color": palette["accent"],
            "hover_color": palette["accent_strong"],
            "checkmark_color": palette.get("on_accent", "#ffffff"),
            "text_color": palette["text"],
            "border_color": palette["border"],
            "font": (ui, 11),
            "corner_radius": 6,
        },
        "tabview": {
            "fg_color": palette["panel_bg"],
            "segmented_button_fg_color": palette["hover_bg"],
            "segmented_button_selected_color": palette["accent"],
            "segmented_button_selected_hover_color": palette["accent"],
            "segmented_button_unselected_color": palette["hover_bg"],
            "segmented_button_unselected_hover_color": _set_hex_luminance(palette["secondary"], 98),
            "text_color": palette["text"],
            "corner_radius": 0,
            "border_width": 0,
            "border_color": palette["border"],
        },
        "divider": {
            "fg_color": palette["border"],
            "corner_radius": 999,
        },
        "textbox": {
            "fg_color": palette["input_bg"],
            "text_color": palette["text"],
            "border_color": palette["secondary"],
            "corner_radius": 10,
            "border_width": 1,
            "font": (mono, 10),
            "scrollbar_button_color": palette["hover_bg"],
            "scrollbar_button_hover_color": palette["accent"],
        },
        "progress": {
            "fg_color": palette["hover_bg"],
            "progress_color": palette["secondary"],
            "border_color": palette["border"],
            "corner_radius": 10,
            "height": 18,
        },
    }


def _get_anndata():
    import anndata as ad

    return ad


def _get_numpy():
    import numpy as np

    return np


def _style_secondary_button_for_palette(button: tk.Widget, palette: dict[str, str], *, borderless: bool = False) -> None:
    try:
        button.configure(
            fg_color=_secondary_idle_color(palette),
            hover_color=palette["secondary"],
            text_color=palette.get("on_secondary_idle", palette["on_secondary"]),
            border_width=0 if borderless else 1,
            border_color=palette["secondary"],
        )
    except Exception:
        pass


def _bind_secondary_button_feedback(button: tk.Widget, palette_getter, *, reset_callback=None) -> None:
    def pointer_inside() -> bool:
        try:
            pointer_x, pointer_y = button.winfo_pointerxy()
            root_x = button.winfo_rootx()
            root_y = button.winfo_rooty()
            return root_x <= pointer_x <= root_x + button.winfo_width() and root_y <= pointer_y <= root_y + button.winfo_height()
        except Exception:
            return False

    def reset() -> None:
        if reset_callback is not None:
            reset_callback()
        else:
            _style_secondary_button_for_palette(button, palette_getter())

    def on_enter(_event: object) -> None:
        try:
            if button.cget("state") == "disabled":
                return
            palette = palette_getter()
            button.configure(fg_color=palette["secondary"], text_color=palette["on_secondary"])
        except Exception:
            pass

    def on_press(_event: object) -> None:
        try:
            if button.cget("state") == "disabled":
                return
            palette = palette_getter()
            button.configure(
                fg_color=_shift_hex_luminance(palette["secondary"], -10),
                text_color=palette["on_secondary"],
            )
        except Exception:
            pass

    def on_release(_event: object) -> None:
        try:
            if button.cget("state") == "disabled":
                return
            if pointer_inside():
                palette = palette_getter()
                button.configure(fg_color=palette["secondary"], text_color=palette["on_secondary"])
            else:
                reset()
        except Exception:
            pass

    def on_leave(_event: object) -> None:
        try:
            if button.cget("state") == "disabled":
                return
            reset()
        except Exception:
            pass

    button.bind("<Enter>", on_enter, add="+")
    button.bind("<ButtonPress-1>", on_press, add="+")
    button.bind("<ButtonRelease-1>", on_release, add="+")
    button.bind("<Leave>", on_leave, add="+")


class SearchableListEditor(_CTK_FRAME_BASE):
    def __init__(
        self,
        parent,
        *,
        label: str,
        height: int = 8,
        help_text: str | None = None,
        palette: dict[str, str] | None = None,
        on_change=None,
    ) -> None:
        self._palette = dict(palette or _palette_for_mode("dark"))
        self._theme = _ctk_theme_config(self._palette)
        self._on_change = on_change
        self._suspend_change_notification = False
        super().__init__(parent, **self._theme["sub_frame"])
        self._choices: list[str] = []
        self._input_var = tk.StringVar(value="")

        self.columnconfigure(0, weight=1)
        self.label_widget = ctk.CTkLabel(self, text=label, **self._theme["field_label"])
        self.label_widget.grid(row=0, column=0, sticky="w", pady=(0, 6))

        controls = ctk.CTkFrame(self, **self._theme["sub_frame"])
        controls.grid(row=1, column=0, sticky="ew")
        controls.columnconfigure(0, weight=1)

        self.entry = ctk.CTkComboBox(
            controls,
            variable=self._input_var,
            values=[],
            state="normal",
            **self._theme["combo"],
        )
        self.entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.entry.bind("<KeyRelease>", self._on_search)
        self.entry.bind("<Return>", lambda _event: self.add_current())

        self.add_btn = ctk.CTkButton(controls, text="+ Add", command=self.add_current, width=88, **self._theme["secondary_button"])
        _bind_secondary_button_feedback(self.add_btn, lambda: self._palette)
        self.add_btn.grid(row=0, column=1, padx=(0, 6))
        self.remove_btn = ctk.CTkButton(
            controls,
            text="Remove",
            command=self.remove_selected,
            width=88,
            **self._theme["secondary_button"],
        )
        _bind_secondary_button_feedback(self.remove_btn, lambda: self._palette)
        self.remove_btn.grid(row=0, column=2, padx=(0, 6))
        self.clear_btn = ctk.CTkButton(controls, text="Clear", command=self.clear, width=88, **self._theme["secondary_button"])
        _bind_secondary_button_feedback(self.clear_btn, lambda: self._palette)
        self.clear_btn.grid(row=0, column=3)

        list_wrap = ctk.CTkFrame(self, **self._theme["sub_frame"])
        list_wrap.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        list_wrap.columnconfigure(0, weight=1)

        self.listbox = tk.Listbox(
            list_wrap,
            height=height,
            selectmode="extended",
            activestyle="none",
            relief="flat",
            bd=0,
            highlightthickness=1,
            font=(_ui_font(), 10),
        )
        self.listbox.grid(row=0, column=0, sticky="ew")
        self.scroll = tk.Scrollbar(list_wrap, orient="vertical", command=self.listbox.yview)
        self.scroll.grid(row=0, column=1, sticky="ns")
        self.listbox.configure(yscrollcommand=self.scroll.set)

        self.help_label: ctk.CTkLabel | None = None
        if help_text:
            self.help_label = ctk.CTkLabel(self, text=help_text, **self._theme["subheader_label"])
            self.help_label.grid(row=3, column=0, sticky="w", pady=(6, 0))

        self.apply_palette(self._palette)

    def _on_search(self, _event) -> None:
        self._update_choices(self._input_var.get())

    def _update_choices(self, query: str = "") -> None:
        needle = query.strip().lower()
        if not needle:
            values = self._choices
        else:
            values = [item for item in self._choices if needle in item.lower()]
        self.entry.configure(values=values[:300])

    def set_choices(self, values: list[str] | tuple[str, ...]) -> None:
        seen: set[str] = set()
        ordered: list[str] = []
        for raw in values:
            value = str(raw).strip()
            if not value or value in seen:
                continue
            seen.add(value)
            ordered.append(value)
        self._choices = ordered
        self._update_choices(self._input_var.get())

    def add_current(self) -> None:
        value = self._input_var.get().strip()
        if not value:
            return
        existing = self.get_items()
        if value in existing:
            idx = existing.index(value)
            self.listbox.selection_clear(0, "end")
            self.listbox.selection_set(idx)
            self.listbox.see(idx)
            self._input_var.set("")
            self.entry.set("")
            return
        self.listbox.insert("end", value)
        self._input_var.set("")
        self.entry.set("")
        self._update_choices("")
        self._notify_change()

    def remove_selected(self) -> None:
        for idx in reversed(self.listbox.curselection()):
            self.listbox.delete(idx)
        self._notify_change()

    def clear(self) -> None:
        self.listbox.delete(0, "end")
        self._notify_change()

    def set_items(self, values: list[str] | tuple[str, ...]) -> None:
        self._suspend_change_notification = True
        self.clear()
        seen: set[str] = set()
        for raw in values:
            value = str(raw).strip()
            if not value or value in seen:
                continue
            seen.add(value)
            self.listbox.insert("end", value)
        self._suspend_change_notification = False
        self._notify_change()

    def get_items(self) -> list[str]:
        return [str(v) for v in self.listbox.get(0, "end")]

    def _notify_change(self) -> None:
        if self._suspend_change_notification:
            return
        if self._on_change is None:
            return
        try:
            self._on_change()
        except Exception:
            pass

    def set_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self.entry.configure(state=state)
        self.add_btn.configure(state=state)
        self.remove_btn.configure(state=state)
        self.clear_btn.configure(state=state)
        self.listbox.configure(state=state)

    def apply_palette(self, palette: dict[str, str]) -> None:
        self._palette = dict(palette)
        self._theme = _ctk_theme_config(self._palette)
        self.label_widget.configure(**self._theme["field_label"])
        self.entry.configure(**self._theme["combo"])
        self.add_btn.configure(**self._theme["secondary_button"])
        self.remove_btn.configure(**self._theme["secondary_button"])
        self.clear_btn.configure(**self._theme["secondary_button"])
        if self.help_label is not None:
            self.help_label.configure(**self._theme["subheader_label"])
        self.listbox.configure(
            background=self._palette["input_bg"],
            foreground=self._palette["text"],
            selectbackground=self._palette["accent"],
            selectforeground=self._palette.get("on_accent", "#ffffff"),
            disabledforeground=self._palette["muted"],
            highlightbackground=self._palette["border"],
            highlightcolor=self._palette["accent"],
        )
        try:
            self.scroll.configure(
                background=self._palette["panel_bg"],
                troughcolor=self._palette["hover_bg"],
                activebackground=self._palette["accent"],
                highlightbackground=self._palette["border"],
            )
        except tk.TclError:
            try:
                self.scroll.configure(background=self._palette["panel_bg"], activebackground=self._palette["accent"])
            except tk.TclError:
                pass


class SearchableMultiSelectEditor(_CTK_FRAME_BASE):
    def __init__(
        self,
        parent,
        *,
        label: str,
        height: int = 8,
        help_text: str | None = None,
        max_visible: int = 500,
        palette: dict[str, str] | None = None,
    ) -> None:
        self._palette = dict(palette or _palette_for_mode("dark"))
        self._theme = _ctk_theme_config(self._palette)
        super().__init__(parent, **self._theme["sub_frame"])
        self._choices: list[str] = []
        self._selected_values: set[str] = set()
        self._search_var = tk.StringVar(value="")
        self._info_var = tk.StringVar(value="")
        self._max_visible = max(50, int(max_visible))

        self.columnconfigure(0, weight=1)
        self.label_widget = ctk.CTkLabel(self, text=label, **self._theme["field_label"])
        self.label_widget.grid(row=0, column=0, sticky="w", pady=(0, 6))

        controls = ctk.CTkFrame(self, **self._theme["sub_frame"])
        controls.grid(row=1, column=0, sticky="ew")
        controls.columnconfigure(0, weight=1)

        self.search_entry = ctk.CTkEntry(controls, textvariable=self._search_var, **self._theme["entry"])
        self.search_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.search_entry.bind("<KeyRelease>", lambda _event: self._on_search_changed())

        self.select_all_btn = ctk.CTkButton(
            controls,
            text="Select all",
            command=self.select_all_matches,
            width=100,
            **self._theme["secondary_button"],
        )
        _bind_secondary_button_feedback(self.select_all_btn, lambda: self._palette)
        self.select_all_btn.grid(row=0, column=1, padx=(0, 6))
        self.clear_btn = ctk.CTkButton(
            controls,
            text="Clear",
            command=self.clear_selection,
            width=90,
            **self._theme["secondary_button"],
        )
        _bind_secondary_button_feedback(self.clear_btn, lambda: self._palette)
        self.clear_btn.grid(row=0, column=2)

        list_wrap = ctk.CTkFrame(self, **self._theme["sub_frame"])
        list_wrap.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        list_wrap.columnconfigure(0, weight=1)

        self.listbox = tk.Listbox(
            list_wrap,
            height=height,
            selectmode="extended",
            activestyle="none",
            relief="flat",
            bd=0,
            highlightthickness=1,
            font=(_ui_font(), 10),
        )
        self.listbox.grid(row=0, column=0, sticky="ew")
        self.listbox.bind("<<ListboxSelect>>", lambda _event: self._capture_visible_selection())
        self.scroll = tk.Scrollbar(list_wrap, orient="vertical", command=self.listbox.yview)
        self.scroll.grid(row=0, column=1, sticky="ns")
        self.listbox.configure(yscrollcommand=self.scroll.set)

        self.info_label = ctk.CTkLabel(self, textvariable=self._info_var, **self._theme["subheader_label"])
        self.info_label.grid(row=3, column=0, sticky="w", pady=(6, 0))

        self.help_label: ctk.CTkLabel | None = None
        if help_text:
            self.help_label = ctk.CTkLabel(self, text=help_text, **self._theme["subheader_label"])
            self.help_label.grid(row=4, column=0, sticky="w", pady=(4, 0))

        self.apply_palette(self._palette)

    def _all_matches(self, needle: str) -> list[str]:
        if not needle:
            return list(self._choices)
        return [name for name in self._choices if needle in name.lower()]

    def _filtered_choices(self) -> tuple[list[str], int]:
        needle = self._search_var.get().strip().lower()
        matches = self._all_matches(needle)
        return matches[: self._max_visible], len(matches)

    def _capture_visible_selection(self) -> None:
        visible = [str(v) for v in self.listbox.get(0, "end")]
        if not visible:
            return
        visible_set = set(visible)
        self._selected_values = {name for name in self._selected_values if name not in visible_set}
        for index in self.listbox.curselection():
            if 0 <= int(index) < len(visible):
                self._selected_values.add(visible[int(index)])

    def _render(self) -> None:
        visible, total_matches = self._filtered_choices()
        self.listbox.delete(0, "end")
        for idx, name in enumerate(visible):
            self.listbox.insert("end", name)
            if name in self._selected_values:
                self.listbox.selection_set(idx)
        if total_matches > len(visible):
            self._info_var.set(
                f"Showing first {len(visible)} of {total_matches} matches. Type more characters to narrow."
            )
        else:
            self._info_var.set(f"{total_matches} matches.")

    def _on_search_changed(self) -> None:
        self._capture_visible_selection()
        self._render()

    def set_choices(self, values: list[str] | tuple[str, ...]) -> None:
        self._capture_visible_selection()
        seen: set[str] = set()
        ordered: list[str] = []
        for raw in values:
            value = str(raw).strip()
            if not value or value in seen:
                continue
            seen.add(value)
            ordered.append(value)
        self._choices = ordered
        allowed = set(self._choices)
        self._selected_values = {name for name in self._selected_values if name in allowed}
        self._render()

    def set_selected(self, values: list[str] | tuple[str, ...]) -> None:
        allowed = set(self._choices)
        self._selected_values = {str(v).strip() for v in values if str(v).strip() in allowed}
        self._render()

    def get_selected(self) -> list[str]:
        self._capture_visible_selection()
        selected = self._selected_values
        return [name for name in self._choices if name in selected]

    def select_all_matches(self) -> None:
        self._capture_visible_selection()
        needle = self._search_var.get().strip().lower()
        for name in self._all_matches(needle):
            self._selected_values.add(name)
        self._render()

    def clear_selection(self) -> None:
        self._selected_values.clear()
        self._render()

    def set_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self.search_entry.configure(state=state)
        self.select_all_btn.configure(state=state)
        self.clear_btn.configure(state=state)
        self.listbox.configure(state=state)

    def apply_palette(self, palette: dict[str, str]) -> None:
        self._palette = dict(palette)
        self._theme = _ctk_theme_config(self._palette)
        self.label_widget.configure(**self._theme["field_label"])
        self.search_entry.configure(**self._theme["entry"])
        self.select_all_btn.configure(**self._theme["secondary_button"])
        self.clear_btn.configure(**self._theme["secondary_button"])
        self.info_label.configure(**self._theme["subheader_label"])
        if self.help_label is not None:
            self.help_label.configure(**self._theme["subheader_label"])
        self.listbox.configure(
            background=self._palette["input_bg"],
            foreground=self._palette["text"],
            selectbackground=self._palette["accent"],
            selectforeground=self._palette.get("on_accent", "#ffffff"),
            disabledforeground=self._palette["muted"],
            highlightbackground=self._palette["border"],
            highlightcolor=self._palette["accent"],
        )
        try:
            self.scroll.configure(
                background=self._palette["panel_bg"],
                troughcolor=self._palette["hover_bg"],
                activebackground=self._palette["accent"],
                highlightbackground=self._palette["border"],
            )
        except tk.TclError:
            try:
                self.scroll.configure(background=self._palette["panel_bg"], activebackground=self._palette["accent"])
            except tk.TclError:
                pass


@dataclass(slots=True)
class AppResult:
    outdir: Path
    n_cells: int
    n_sections: int
    output_html: Path


@dataclass(slots=True)
class BuilderConfig:
    h5ad_path: Path
    outdir: Path
    coords_mode: str | None
    spatialdata_table: str | None
    section_groupby: str
    section_order: list[str] | None
    section_metadata: list[str] | None
    section_metadata_extra: list[str] | None
    metadata_value_order: dict[str, list[str]] | None
    metadata_max_columns: int | None
    initial_color: str
    title: str
    enable_numba_jit: bool
    outline_by: str | None
    metadata_labels: dict[str, str] | None
    viewer_info_html: str | None
    tutorial: bool
    min_panel_size: int
    spot_size: float | str | None
    downsample: int | None
    additional_colors: list[str] | None
    genes: list[str] | None
    feature_encoding: str
    feature_value_encoding: str
    feature_storage: str
    feature_manifest_path: str | None
    feature_sidecar_shard_size: int
    feature_sparse_zero_threshold: float
    modalities: list[str] | None
    neighbor_stats_groupby: list[str] | None
    neighbor_stats_permutations: int | None
    neighbor_stats_seed: int
    pseudobulk: str | None
    pseudobulk_additional_annotations: list[str] | None
    pseudobulk_replicate_annotation: str | None
    pseudobulk_simple_constrast_categories: dict[str, list[str] | None] | list[str] | None
    pseudobulk_counts_layer: str | None
    pseudobulk_min_cell_counts: int
    pseudobulk_min_gene_counts: int
    pseudobulk_min_cells_per_pseudobulk: int
    pseudobulk_min_replicates: int
    pseudobulk_min_pct_expressed: float
    pseudobulk_p_adjust_method: str
    pseudobulk_padj_cutoff: float
    pseudobulk_log2fc_cutoff: float
    pseudobulk_deseq2_fit_type: str
    pseudobulk_n_cpus: int
    pseudobulk_embed_top_n_per_comparison: int
    pathway_gmt: list[str] | None
    pathway_organism: str
    pathway_top_n: int
    pathway_min_overlap: int
    pathway_gsea_permutations: int
    interaction_markers: str | None
    interaction_markers_top_targets: int
    interaction_markers_top_genes: int
    interaction_markers_min_cells: int
    interaction_markers_min_neighbors: int
    section_rotations: dict[str, float] | None
    deconvolutions: dict[str, str] | None
    gene_correlation_top_n: int
    category_means_n_genes: int
    spatial_variable_genes_n: int
    scalebar_unit: str
    section_images: dict[str, object] | None
    section_images_max_px: int


class _ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


class _ExportCancelled(Exception):
    pass


class _EventLogTee:
    def __init__(self, stream, event_queue: queue.Queue[tuple[str, object]], *, prefix: str = "") -> None:
        self._stream = stream
        self._queue = event_queue
        self._prefix = prefix
        self._buffer = ""

    @property
    def encoding(self):
        return getattr(self._stream, "encoding", None)

    def isatty(self) -> bool:
        try:
            return bool(self._stream.isatty())
        except Exception:
            return False

    def write(self, text) -> int:
        if text is None:
            return 0
        value = str(text)
        try:
            self._stream.write(value)
        except Exception:
            pass

        self._buffer += value.replace("\r", "\n")
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._emit(line)
        return len(value)

    def flush(self) -> None:
        try:
            self._stream.flush()
        except Exception:
            pass
        if self._buffer.strip():
            self._emit(self._buffer)
        self._buffer = ""

    def _emit(self, line: str) -> None:
        message = line.strip()
        if not message:
            return
        self._queue.put(("log", f"{self._prefix}{message}"))


class ExportApp(ctk.CTk if ctk is not None else object):
    _OUTPUT_HTML_BASENAME = "KaroSpace"
    _NEIGHBOR_MATRIX_BUDGET_BYTES = 512 * 1024 * 1024
    _MARKER_GROUPBY_MAX_UNIQUE = 2048
    _INTERACTION_GROUPBY_MAX_UNIQUE = 512
    _HTML_SIZE_MB_PER_ELEMENT = 2.313e-6
    _HTML_SIZE_WARNING_ELEMENTS = 150_000_000

    def __init__(self) -> None:
        super().__init__()
        self.title("KaroSpaceBuilder")
        self.geometry("1280x820")
        self.minsize(1060, 720)

        self._queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self._export_thread: threading.Thread | None = None
        self._cancel_requested = threading.Event()
        self._server: _ThreadingHTTPServer | None = None
        self._server_thread: threading.Thread | None = None
        self._last_outdir: Path | None = None
        self._last_output_html: Path | None = None
        self._has_valid_input_file = False
        self._has_inspected_input_file = False
        self._inspect_locked_after_press = False
        self._inspected_h5ad_path: Path | None = None
        self._inspected_var_name_set: set[str] | None = None
        self._inspected_coords_mode: str | None = None
        self._inspected_n_cells: int | None = None
        self._inspected_n_genes: int | None = None
        self._inspected_obs_cols: set[str] = set()
        self._inspected_section_counts_by_column: dict[str, list[int]] = {}
        self._themed_widgets: dict[str, list[tk.Widget]] = {}
        self._inspection_gated_widgets: list[tk.Widget] = []
        self._right_panel_widgets: list[tk.Widget] = []
        self._secondary_action_buttons: list[tk.Widget] = []
        self._tab_hover_bound: set[str] = set()
        self._placeholder_refreshers: list[object] = []
        self._hidden_widget_layouts: dict[tk.Widget, tuple[str, dict[str, object]]] = {}

        self._build_style()
        self._build_variables()
        self._build_layout()
        self.after(120, self._poll_events)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_style(self) -> None:
        self._themed_widgets = {}
        self._app_palette = _palette_for_mode("dark")
        self._theme = _ctk_theme_config(self._app_palette)
        ctk.set_appearance_mode("dark")
        self.configure(**self._theme["root"])

    def _apply_app_theme(self, mode: str) -> None:
        palette = _palette_for_mode(mode)
        self._app_palette = palette
        self._theme = _ctk_theme_config(palette)
        ctk.set_appearance_mode("dark" if mode.strip().lower() == "dark" else "light")
        self.configure(**self._theme["root"])

        for role, widgets in self._themed_widgets.items():
            role_style = self._theme.get(role)
            if not role_style:
                continue
            for widget in widgets:
                if widget is None:
                    continue
                try:
                    widget.configure(**role_style)
                except Exception:
                    continue

        if hasattr(self, "help_text"):
            self.help_text.configure(**self._theme["textbox"])
        if hasattr(self, "log_text"):
            self.log_text.configure(**self._theme["textbox"])
        if hasattr(self, "progress"):
            self.progress.configure(**self._theme["progress"])
        if hasattr(self, "theme_toggle_btn"):
            self.theme_toggle_btn.configure(**self._theme["secondary_button"])
            self._sync_theme_toggle()
        if hasattr(self, "main_scroll_frame"):
            self.main_scroll_frame.configure(
                scrollbar_button_color=palette["hover_bg"],
                scrollbar_button_hover_color=palette["accent"],
            )
        self._sync_runtime_chip()
        for attr in (
            "additional_colors_editor",
            "groupby_editor",
            "section_metadata_editor",
            "section_metadata_extra_editor",
            "manual_genes_editor",
            "selection_additional_picker",
            "selection_groupby_picker",
            "selection_genes_picker",
        ):
            widget = getattr(self, attr, None)
            if widget is not None and hasattr(widget, "apply_palette"):
                widget.apply_palette(palette)
        for button in self._secondary_action_buttons:
            self._style_secondary_action_button(button)
        for refresh_placeholder in self._placeholder_refreshers:
            try:
                refresh_placeholder()
            except Exception:
                pass
        self._sync_tab_button_styles()
        if hasattr(self, "inspect_btn"):
            self._refresh_input_gate()
        if hasattr(self, "export_estimate_summary_label"):
            self._update_export_estimate()

    def _register_theme_widget(self, role: str, widget: tk.Widget) -> tk.Widget:
        self._themed_widgets.setdefault(role, []).append(widget)
        return widget

    def _header_label(self, parent: tk.Widget, text: str) -> ctk.CTkLabel:
        label = ctk.CTkLabel(parent, text=text, **self._theme["header_label"])
        self._register_theme_widget("header_label", label)
        return label

    def _hero_label(self, parent: tk.Widget, text: str) -> ctk.CTkLabel:
        label = ctk.CTkLabel(parent, text=text, **self._theme["hero_label"])
        self._register_theme_widget("hero_label", label)
        return label

    def _subheader_label(self, parent: tk.Widget, text: str | None = None, textvariable: tk.StringVar | None = None) -> ctk.CTkLabel:
        kwargs: dict[str, object] = dict(self._theme["subheader_label"])
        if text is not None:
            kwargs["text"] = text
        if textvariable is not None:
            kwargs["textvariable"] = textvariable
        label = ctk.CTkLabel(parent, **kwargs)
        self._register_theme_widget("subheader_label", label)
        return label

    def _section_label(self, parent: tk.Widget, text: str) -> ctk.CTkLabel:
        label = ctk.CTkLabel(parent, text=text, **self._theme["section_label"])
        self._register_theme_widget("section_label", label)
        return label

    def _field_label(self, parent: tk.Widget, text: str) -> ctk.CTkLabel:
        label = ctk.CTkLabel(parent, text=text, **self._theme["field_label"])
        self._register_theme_widget("field_label", label)
        return label

    def _body_label(self, parent: tk.Widget, text: str) -> ctk.CTkLabel:
        label = ctk.CTkLabel(parent, text=text, **self._theme["body_label"])
        self._register_theme_widget("body_label", label)
        return label

    def _secondary_button(self, parent: tk.Widget, text: str, command, width: int | None = None) -> ctk.CTkButton:
        kwargs: dict[str, object] = {"text": text, "command": command, **self._theme["secondary_button"]}
        if width is not None:
            kwargs["width"] = width
        button = ctk.CTkButton(parent, **kwargs)
        self._register_theme_widget("secondary_button", button)
        self._bind_secondary_press_feedback(button)
        return button

    def _primary_button(self, parent: tk.Widget, text: str, command, width: int | None = None) -> ctk.CTkButton:
        kwargs: dict[str, object] = {"text": text, "command": command, **self._theme["primary_button"]}
        if width is not None:
            kwargs["width"] = width
        button = ctk.CTkButton(parent, **kwargs)
        self._register_theme_widget("primary_button", button)
        return button

    def _pill_label(
        self,
        parent: tk.Widget,
        *,
        text: str | None = None,
        textvariable: tk.StringVar | None = None,
        muted: bool = False,
    ) -> ctk.CTkLabel:
        role = "muted_pill_label" if muted else "pill_label"
        kwargs: dict[str, object] = dict(self._theme[role])
        if text is not None:
            kwargs["text"] = text
        if textvariable is not None:
            kwargs["textvariable"] = textvariable
        label = ctk.CTkLabel(parent, **kwargs)
        self._register_theme_widget(role, label)
        return label

    def _divider(self, parent: tk.Widget, *, height: int = 1) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(parent, height=height, **self._theme["divider"])
        self._register_theme_widget("divider", frame)
        return frame

    def _make_card_frame(self, parent: tk.Widget, *, padding: int = 0) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(parent, **self._theme["card_frame"])
        self._register_theme_widget("card_frame", frame)
        if padding > 0:
            inner = ctk.CTkFrame(frame, **self._theme["sub_frame"])
            self._register_theme_widget("sub_frame", inner)
            inner.pack(fill="both", expand=True, padx=padding, pady=padding)
            return inner
        return frame

    def _make_sub_frame(self, parent: tk.Widget) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(parent, **self._theme["sub_frame"])
        self._register_theme_widget("sub_frame", frame)
        return frame

    def _register_entry_widget(self, widget: tk.Widget) -> None:
        self._register_theme_widget("entry", widget)

    def _register_combo_widget(self, widget: tk.Widget) -> None:
        self._register_theme_widget("combo", widget)

    def _register_checkbox_widget(self, widget: tk.Widget) -> None:
        self._register_theme_widget("checkbox", widget)

    def _sync_app_theme_to_viewer_setting(self) -> None:
        self._apply_app_theme(self.theme_var.get())

    def _toggle_theme(self) -> None:
        current = self.theme_var.get().strip().lower()
        next_mode = "light" if current == "dark" else "dark"
        self.theme_var.set(next_mode)
        self._apply_app_theme(next_mode)

    def _sync_theme_toggle(self) -> None:
        if not hasattr(self, "theme_toggle_btn"):
            return
        mode = self.theme_var.get().strip().lower()
        self.theme_toggle_btn.configure(text="☀" if mode == "dark" else "☾")

    @staticmethod
    def _guide_text() -> str:
        return (
            "Basic tab\n"
            "- Input file: absolute path to your AnnData .h5ad file, or a SpatialData .zarr path typed manually.\n"
            "- Output directory: folder where KaroSpace_YYYYMMDD_HHMMSS.html is written.\n"
            "- Coordinates: auto/obsm/obs-centroid modes are converted to KaroSpace spatial input.\n"
            "- Section key: section split column used by load_spatial_data(section_key=...).\n"
            "- Main cell annotation, outline, metadata labels, tutorial, and title map to export_to_html.\n"
            "- Runtime mode: optional numba JIT performance mode (can be less stable in frozen app).\n"
            "- Downsample: integer cells per section (blank keeps all).\n\n"
            "Colors tab\n"
            "- additional_colors maps to cell_annotations in the new KaroSpace API.\n"
            "- analysis annotations feed pseudobulk_additional_annotations and optional neighbor stats.\n"
            "- section_metadata and section_metadata_extra control section filters and stored section metadata.\n\n"
            "Genes tab\n"
            "- Tick selection mode: optional inspected multi-select mode. Tick obs/features and export directly without manually adding rows.\n"
            "- features: build a var_names list manually with the searchable picker or tick selections.\n"
            "- feature_storage, feature_encoding, sidecar shard size, and modalities map directly to KaroSpace feature options.\n\n"
            "Cells tab\n"
            "- Downsample: integer cells per section (blank keeps all).\n\n"
            "Advanced tab\n"
            "- Min panel size, spot size, feature/pseudobulk/pathway thresholds.\n"
            "- Neighbor stats annotations/permutations/seed and interaction marker controls.\n"
            "- Metadata value order, section rotations, deconvolutions, section images, modalities, and discovery-panel limits.\n"
            "- Serve after export starts a local preview server for the latest KaroSpace_*.html export.\n\n"
            "Tip: click Inspect H5AD to load searchable obs dropdown choices and var_names gene pickers."
        )

    def _show_guide_popup(self) -> None:
        existing = getattr(self, "_guide_popup", None)
        if existing is not None and existing.winfo_exists():
            existing.destroy()
            return

        popup = ctk.CTkToplevel(self)
        self._guide_popup = popup
        popup.overrideredirect(True)
        popup.geometry("720x620")
        popup.minsize(560, 440)
        popup.configure(**self._theme["root"])
        popup.columnconfigure(0, weight=1)
        popup.rowconfigure(1, weight=1)
        popup.bind("<Escape>", lambda _event: popup.destroy())

        self.update_idletasks()
        x = self.winfo_rootx() + max(24, int((self.winfo_width() - 720) / 2))
        y = self.winfo_rooty() + 96
        popup.geometry(f"720x620+{x}+{y}")

        header = ctk.CTkFrame(popup, **self._theme["sub_frame"])
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(18, 10))
        header.columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text="Guide & Workflow", **self._theme["header_label"]).grid(row=0, column=0, sticky="w")
        close_btn = ctk.CTkButton(header, text="×", command=popup.destroy, width=42, **self._theme["secondary_button"])
        close_btn.grid(row=0, column=1, sticky="e")

        text = ctk.CTkTextbox(popup, wrap="word", **self._theme["textbox"])
        text.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 18))
        text.insert("1.0", self._guide_text())
        text.configure(state="disabled")
        popup.focus()

    def _on_tab_selected(self) -> None:
        if not hasattr(self, "notebook"):
            return
        selected = self.notebook.get()
        gated_tabs = {"Colors", "Genes", "Cells", "Advanced"}
        if selected in gated_tabs and not self._has_inspected_input_file:
            self.notebook.set(self._last_enabled_tab)
            self._sync_tab_button_styles()
            return
        self._last_enabled_tab = selected
        self._sync_tab_button_styles()

    def _valid_h5ad_path(self) -> Path | None:
        raw = self.h5ad_var.get().strip()
        if not raw:
            return None
        path = Path(raw).expanduser()
        try:
            resolved = path.resolve()
        except Exception:
            return None
        suffix = resolved.suffix.lower()
        if resolved.exists() and (
            (resolved.is_file() and suffix == ".h5ad")
            or (resolved.is_dir() and suffix == ".zarr")
        ):
            return resolved
        return None

    def _configure_widget_state(self, widget: object | None, enabled: bool) -> None:
        if widget is None:
            return
        try:
            widget.configure(state="normal" if enabled else "disabled")
        except Exception:
            pass
        if enabled:
            for role, widgets in self._themed_widgets.items():
                if widget in widgets:
                    style = self._theme.get(role)
                    if style:
                        try:
                            widget.configure(**style)
                        except Exception:
                            pass
                    break
            return

        disabled_styles = {
            "fg_color": self._app_palette["hover_bg"],
            "text_color": self._app_palette["muted"],
            "button_color": self._app_palette["hover_bg"],
            "button_hover_color": self._app_palette["hover_bg"],
            "hover_color": self._app_palette["hover_bg"],
            "border_color": self._app_palette["border"],
        }
        for key, value in disabled_styles.items():
            try:
                widget.configure(**{key: value})
            except Exception:
                pass

    def _set_widgets_visible(self, widgets: list[tk.Widget], visible: bool) -> None:
        for widget in widgets:
            try:
                if visible:
                    saved = self._hidden_widget_layouts.pop(widget, None)
                    if saved is None:
                        continue
                    manager, info = saved
                    if manager == "grid":
                        widget.grid(**info)
                    elif manager == "pack":
                        widget.pack(**info)
                    elif manager == "place":
                        widget.place(**info)
                else:
                    if widget in self._hidden_widget_layouts:
                        continue
                    manager = widget.winfo_manager()
                    if manager == "grid":
                        info = dict(widget.grid_info())
                        self._hidden_widget_layouts[widget] = (manager, info)
                        widget.grid_remove()
                    elif manager == "pack":
                        info = dict(widget.pack_info())
                        self._hidden_widget_layouts[widget] = (manager, info)
                        widget.pack_forget()
                    elif manager == "place":
                        info = dict(widget.place_info())
                        self._hidden_widget_layouts[widget] = (manager, info)
                        widget.place_forget()
            except Exception:
                pass

    def _refresh_tab_gate(self) -> None:
        if not hasattr(self, "notebook"):
            return
        segmented = getattr(self.notebook, "_segmented_button", None)
        buttons = getattr(segmented, "_buttons_dict", {}) if segmented is not None else {}
        for tab_name in ("Colors", "Genes", "Cells", "Advanced"):
            button = buttons.get(tab_name)
            self._configure_widget_state(button, self._has_inspected_input_file)
        if not self._has_inspected_input_file and self.notebook.get() in {"Colors", "Genes", "Cells", "Advanced"}:
            self.notebook.set("Basic")
            self._last_enabled_tab = "Basic"
        self._sync_tab_button_styles()

    def _sync_tab_button_styles(self) -> None:
        if not hasattr(self, "notebook"):
            return
        segmented = getattr(self.notebook, "_segmented_button", None)
        buttons = getattr(segmented, "_buttons_dict", {}) if segmented is not None else {}
        selected = self.notebook.get()
        if segmented is not None:
            try:
                segmented.grid_configure(sticky="ew", padx=0)
                for column_index in range(len(buttons)):
                    segmented.columnconfigure(column_index, weight=1)
                segmented.configure(
                    fg_color=self._app_palette["hover_bg"],
                    unselected_color=self._app_palette["hover_bg"],
                    unselected_hover_color=_set_hex_luminance(self._app_palette["secondary"], 98),
                    corner_radius=0,
                )
            except Exception:
                pass

        for tab_name, button in buttons.items():
            try:
                disabled = button.cget("state") == "disabled"
            except Exception:
                disabled = False

            try:
                button.configure(
                    border_width=0,
                    border_color=self._app_palette["hover_bg"],
                    corner_radius=10,
                    text_color=(
                        self._app_palette["muted"]
                        if disabled
                        else self._app_palette.get("on_accent", "#ffffff")
                        if tab_name == selected
                        else self._app_palette["text"]
                    ),
                )
            except Exception:
                pass

            if tab_name in self._tab_hover_bound:
                continue

            def on_enter(_event: object, name: str = tab_name, tab_button: tk.Widget = button) -> None:
                try:
                    if tab_button.cget("state") == "disabled":
                        return
                    if self.notebook.get() == name:
                        tab_button.configure(text_color=self._app_palette.get("on_accent", "#ffffff"))
                    else:
                        tab_button.configure(text_color=self._app_palette["secondary"])
                except Exception:
                    pass

            def on_leave(_event: object, name: str = tab_name, tab_button: tk.Widget = button) -> None:
                try:
                    if tab_button.cget("state") == "disabled":
                        tab_button.configure(text_color=self._app_palette["muted"])
                    elif self.notebook.get() == name:
                        tab_button.configure(text_color=self._app_palette.get("on_accent", "#ffffff"))
                    else:
                        tab_button.configure(text_color=self._app_palette["text"])
                except Exception:
                    pass

            button.bind("<Enter>", on_enter, add="+")
            button.bind("<Leave>", on_leave, add="+")
            self._tab_hover_bound.add(tab_name)

    def _refresh_inspect_button_state(self, *, busy: bool | None = None) -> None:
        if not hasattr(self, "inspect_btn"):
            return
        if busy is None:
            busy = bool(self._export_thread and self._export_thread.is_alive())

        armed = self._has_valid_input_file and not self._inspect_locked_after_press and not busy
        self._configure_widget_state(self.inspect_btn, armed)
        if armed:
            self._style_secondary_action_button(self.inspect_btn)

    def _style_secondary_action_button(self, button: tk.Widget, *, borderless: bool = False) -> None:
        _style_secondary_button_for_palette(button, self._app_palette, borderless=borderless)

    def _export_is_running(self) -> bool:
        return bool(self._export_thread and self._export_thread.is_alive())

    def _is_export_stop_button(self, button: tk.Widget) -> bool:
        return button is getattr(self, "export_btn", None) and self._export_is_running()

    def _style_export_stop_button(self) -> None:
        button = getattr(self, "export_btn", None)
        if button is None:
            return
        try:
            button.configure(
                text="Stop Preview",
                command=self._cancel_operations,
                fg_color=self._app_palette["danger"],
                hover_color=self._app_palette["danger_hover"],
                text_color=self._app_palette["on_danger"],
                border_width=1,
                border_color=self._app_palette["danger"],
            )
        except Exception:
            pass

    def _bind_secondary_press_feedback(self, button: tk.Widget) -> None:
        def reset() -> None:
            if self._is_export_stop_button(button):
                self._style_export_stop_button()
            else:
                self._style_secondary_action_button(button)

        _bind_secondary_button_feedback(button, lambda: self._app_palette, reset_callback=reset)

    def _sync_right_panel_title_colors(self) -> None:
        for attr in ("runtime_title_label", "event_log_label"):
            widget = getattr(self, attr, None)
            if widget is None:
                continue
            try:
                widget.configure(state="normal", text_color=self._app_palette["secondary"])
            except Exception:
                pass

    def _set_inspect_loading(self, loading: bool) -> None:
        indicator = getattr(self, "inspect_loading_label", None)
        if indicator is None:
            return

        if loading:
            try:
                indicator.configure(text="⟳ Inspecting...", text_color=self._app_palette["secondary"])
                if not indicator.winfo_manager():
                    indicator.pack(side="left", padx=(12, 0))
                indicator.lift()
                self.status_var.set("Inspecting dataset...")
                self.update()
            except Exception:
                pass
            return

        try:
            indicator.pack_forget()
        except Exception:
            pass

    def _on_export_button(self) -> None:
        if self._export_thread and self._export_thread.is_alive():
            self._cancel_operations()
            return
        self._on_export()

    def _sync_export_button_state(self, *, busy: bool, enabled: bool) -> None:
        button = getattr(self, "export_btn", None)
        if button is None:
            return
        try:
            if busy:
                self._configure_widget_state(button, True)
                self._style_export_stop_button()
            else:
                button.configure(text="Build Viewer", command=self._on_export_button)
                self._configure_widget_state(button, enabled)
                if enabled:
                    self._style_secondary_action_button(button)
        except Exception:
            pass

    def _cancel_operations(self) -> None:
        self._cancel_requested.set()
        if self._server is not None:
            self._stop_server()
        if self._export_thread and self._export_thread.is_alive():
            self.status_var.set("Cancel requested")
            self._log("Cancel requested. Current export step will stop at the next safe checkpoint.")
        else:
            self.status_var.set("Ready")

    def _refresh_right_panel_gate(self) -> None:
        inspected = bool(self._has_inspected_input_file)
        side_outer = getattr(self, "side_outer", None)
        if side_outer is not None:
            try:
                if inspected:
                    side_outer.configure(**self._theme["card_frame"])
                else:
                    side_outer.configure(
                        fg_color=self._app_palette["hover_bg"],
                        border_color=self._app_palette["border"],
                    )
            except Exception:
                pass

        for widget in self._right_panel_widgets:
            self._configure_widget_state(widget, inspected)
        self._sync_right_panel_title_colors()

        if hasattr(self, "progress"):
            try:
                if inspected:
                    self.progress.configure(**self._theme["progress"])
                else:
                    self.progress.configure(
                        fg_color=self._app_palette["hover_bg"],
                        progress_color=self._app_palette["muted"],
                    )
            except Exception:
                pass
        if hasattr(self, "log_text"):
            try:
                self.log_text.configure(state="disabled")
                if inspected:
                    self.log_text.configure(**self._theme["textbox"])
                else:
                    self.log_text.configure(
                        fg_color=self._app_palette["hover_bg"],
                        text_color=self._app_palette["muted"],
                        border_color=self._app_palette["secondary"],
                    )
            except Exception:
                pass
        self._sync_runtime_chip()

    def _clear_inspection_metadata(self) -> None:
        self._inspected_h5ad_path = None
        self._inspected_var_name_set = None
        self._inspected_coords_mode = None
        self._inspected_n_cells = None
        self._inspected_n_genes = None
        self._inspected_obs_cols = set()
        self._inspected_section_counts_by_column = {}

    @staticmethod
    def _format_count(value: int) -> str:
        return f"{int(value):,}"

    def _estimate_exported_gene_count(self) -> tuple[int | None, str | None]:
        total_genes = self._inspected_n_genes
        if total_genes is None:
            return None, "dataset gene count is unknown"

        genes = self.manual_genes_editor.get_items() if hasattr(self, "manual_genes_editor") else []
        if self.selection_mode_var.get() and hasattr(self, "selection_genes_picker"):
            selected = self.selection_genes_picker.get_selected()
            if selected:
                genes = selected
        count = len(self._merge_unique(genes))
        if count <= 0:
            return None, "add at least one feature"
        return min(total_genes, count), None

    def _get_section_counts_for_estimate(self, column: str) -> list[int] | None:
        if not column or column not in self._inspected_obs_cols:
            return None
        cached = self._inspected_section_counts_by_column.get(column)
        if cached is not None:
            return cached
        path = self._inspected_h5ad_path
        if path is None or not path.exists():
            return None

        adata = None
        try:
            ad_mod = _get_anndata()
            try:
                adata = ad_mod.read_h5ad(path, backed="r")
            except Exception:
                adata = ad_mod.read_h5ad(path)
            counts = [int(value) for value in adata.obs[column].value_counts(dropna=False).tolist()]
            self._inspected_section_counts_by_column[column] = counts
            return counts
        except Exception:
            return None
        finally:
            if adata is not None and getattr(adata, "isbacked", False):
                file_obj = getattr(adata, "file", None)
                if file_obj is not None:
                    file_obj.close()

    def _estimate_exported_cell_count(self) -> tuple[int | None, str | None]:
        total_cells = self._inspected_n_cells
        if total_cells is None:
            return None, "dataset cell count is unknown"

        downsample_text = self.downsample_var.get().strip()
        if not downsample_text:
            return total_cells, None
        try:
            downsample = int(downsample_text)
        except ValueError:
            return None, "enter a valid downsample value"
        if downsample <= 0:
            return None, "enter a positive downsample value"

        groupby = self.section_groupby_var.get().strip()
        counts = self._get_section_counts_for_estimate(groupby)
        if counts:
            return sum(min(count, downsample) for count in counts), None
        return min(total_cells, downsample), f"section counts unavailable for '{groupby}'"

    def _update_export_estimate(self) -> None:
        if not hasattr(self, "export_estimate_summary_label"):
            return

        if not self._has_inspected_input_file or self._inspected_n_cells is None or self._inspected_n_genes is None:
            self.export_estimate_summary_label.configure(
                text="Inspect a dataset to estimate exported cells, genes, elements, and HTML size.",
                text_color=self._app_palette["text"],
            )
            self.export_estimate_warning_label.configure(text="", text_color=self._app_palette["muted"])
            return

        cells, cell_note = self._estimate_exported_cell_count()
        genes, gene_note = self._estimate_exported_gene_count()
        notes = [note for note in (cell_note, gene_note) if note]
        if cells is None or genes is None:
            note = "; ".join(notes) if notes else "complete the export settings"
            self.export_estimate_summary_label.configure(
                text=f"Estimate waiting for valid settings: {note}.",
                text_color=self._app_palette["text"],
            )
            self.export_estimate_warning_label.configure(text="", text_color=self._app_palette["muted"])
            return

        elements = int(cells) * int(genes)
        predicted_mb = self._HTML_SIZE_MB_PER_ELEMENT * elements
        summary = (
            f"Export estimate: {self._format_count(cells)} cells x {self._format_count(genes)} genes = "
            f"{self._format_count(elements)} elements. Predicted HTML size: {predicted_mb:,.1f} MB. "
            "Expected if genes are selected at random. HTML file size will drastically increase if top_genes are selected (dense matrix)."
        )
        if notes:
            summary = f"{summary} Note: {'; '.join(notes)}."
        self.export_estimate_summary_label.configure(text=summary, text_color=self._app_palette["text"])

        if elements > self._HTML_SIZE_WARNING_ELEMENTS:
            self.export_estimate_warning_label.configure(
                text=(
                    "Warning: more than 150 million exported entries. Builder will probably generate an HTML file "
                    ">500 MB, and the browser may not be able to display such a big HTML file."
                ),
                text_color=self._app_palette["danger"],
            )
        else:
            self.export_estimate_warning_label.configure(text="", text_color=self._app_palette["muted"])

    def _refresh_input_gate(self) -> None:
        valid_path = self._valid_h5ad_path()
        has_valid_input = valid_path is not None
        if has_valid_input != self._has_valid_input_file:
            self._has_valid_input_file = has_valid_input
        input_changed = (
            valid_path is not None
            and self._inspected_h5ad_path is not None
            and self._inspected_h5ad_path != valid_path
        )
        if not has_valid_input or input_changed:
            self._has_inspected_input_file = False
            self._clear_inspection_metadata()

        busy = bool(self._export_thread and self._export_thread.is_alive())
        enabled = has_valid_input and self._has_inspected_input_file and not busy
        self._set_widgets_visible(self._inspection_gated_widgets, self._has_inspected_input_file)

        for attr in (
            "coords_menu",
            "spatialdata_table_entry",
            "groupby_combo",
            "color_combo",
            "numba_jit_check",
            "outline_combo",
            "title_entry",
            "downsample_entry",
        ):
            self._configure_widget_state(getattr(self, attr, None), enabled)

        self._sync_export_button_state(busy=busy, enabled=enabled)
        self._configure_widget_state(getattr(self, "inspect_btn", None), has_valid_input and not busy)
        self._refresh_inspect_button_state(busy=busy)
        self._configure_widget_state(getattr(self, "open_output_btn", None), self._has_inspected_input_file and not busy)
        self._configure_widget_state(getattr(self, "open_viewer_btn", None), self._has_inspected_input_file and not busy)

        self._refresh_tab_gate()
        self._refresh_right_panel_gate()
        self._update_export_estimate()

    def _sync_runtime_chip(self) -> None:
        if not hasattr(self, "runtime_chip_label"):
            return
        status = self.status_var.get().strip().lower()
        if status.startswith("export running"):
            text = "RUNNING"
            fg = self._app_palette["accent"]
            tc = self._app_palette.get("on_accent", "#ffffff")
        elif status.startswith("export complete"):
            text = "COMPLETE"
            fg = "#1f8f5f"
            tc = "#ffffff"
        elif status.startswith("serving on"):
            text = "SERVING"
            fg = self._app_palette["accent_strong"]
            tc = self._app_palette.get("on_accent", "#ffffff")
        elif status.startswith("export failed"):
            text = "FAILED"
            fg = "#bf2f5e"
            tc = "#ffffff"
        else:
            text = "READY"
            fg = self._theme["progress"]["fg_color"]
            tc = self._app_palette["text"]
        self.runtime_chip_label.configure(
            text=text,
            fg_color=fg,
            text_color=tc,
            border_width=0,
        )

    def _build_variables(self) -> None:
        self.h5ad_var = tk.StringVar()
        self.outdir_var = tk.StringVar()
        self.coords_var = tk.StringVar(value="auto")
        self.spatialdata_table_var = tk.StringVar()
        self.section_groupby_var = tk.StringVar(value="sample_id")
        self.section_order_var = tk.StringVar()
        self.metadata_value_order_var = tk.StringVar()
        self.metadata_max_columns_var = tk.StringVar()
        self.initial_color_var = tk.StringVar(value="leiden")
        self.title_var = tk.StringVar(value="KaroSpace")
        self.theme_var = tk.StringVar(value="dark")
        self.numba_jit_var = tk.BooleanVar(value=False)
        self.outline_by_var = tk.StringVar(value="condition")
        self.metadata_labels_var = tk.StringVar()
        self.viewer_info_html_file_var = tk.StringVar()
        self.tutorial_var = tk.BooleanVar(value=False)

        self.feature_encoding_var = tk.StringVar(value="auto")
        self.feature_value_encoding_var = tk.StringVar(value="uint16")
        self.feature_storage_var = tk.StringVar(value="embedded")
        self.feature_manifest_path_var = tk.StringVar()
        self.feature_sidecar_shard_size_var = tk.StringVar(value="256")
        self.feature_sparse_zero_threshold_var = tk.StringVar(value="0.8")
        self.modalities_var = tk.StringVar()
        self.min_panel_size_var = tk.StringVar(value="120")
        self.spot_size_var = tk.StringVar(value="auto")
        self.pseudobulk_embed_top_n_per_comparison_var = tk.StringVar(value="20")
        self.neighbor_permutations_var = tk.StringVar(value="25")
        self.neighbor_stats_seed_var = tk.StringVar(value="42")
        self.neighbor_auto_var = tk.BooleanVar(value=True)
        self.pseudobulk_enabled_var = tk.BooleanVar(value=True)
        self.pseudobulk_replicate_annotation_var = tk.StringVar()
        self.pseudobulk_simple_constrast_categories_var = tk.StringVar()
        self.pseudobulk_counts_layer_var = tk.StringVar(value="counts")
        self.pseudobulk_min_cell_counts_var = tk.StringVar(value="0")
        self.pseudobulk_min_gene_counts_var = tk.StringVar(value="0")
        self.pseudobulk_min_cells_per_pseudobulk_var = tk.StringVar(value="20")
        self.pseudobulk_min_replicates_var = tk.StringVar(value="2")
        self.pseudobulk_min_pct_expressed_var = tk.StringVar(value="0")
        self.pseudobulk_p_adjust_method_var = tk.StringVar(value="fdr_bh")
        self.pseudobulk_padj_cutoff_var = tk.StringVar(value="0.05")
        self.pseudobulk_log2fc_cutoff_var = tk.StringVar(value="0.5")
        self.pseudobulk_deseq2_fit_type_var = tk.StringVar(value="parametric")
        self.pseudobulk_n_cpus_var = tk.StringVar(value="1")
        self.pathway_gmt_var = tk.StringVar()
        self.pathway_organism_var = tk.StringVar(value="Human")
        self.pathway_top_n_var = tk.StringVar(value="20")
        self.pathway_min_overlap_var = tk.StringVar(value="3")
        self.pathway_gsea_permutations_var = tk.StringVar(value="100")
        self.interaction_markers_enabled_var = tk.BooleanVar(value=False)
        self.interaction_markers_top_targets_var = tk.StringVar(value="6")
        self.interaction_markers_top_genes_var = tk.StringVar(value="15")
        self.interaction_markers_min_cells_var = tk.StringVar(value="30")
        self.interaction_markers_min_neighbors_var = tk.StringVar(value="1")
        self.section_rotations_var = tk.StringVar()
        self.deconvolutions_var = tk.StringVar()
        self.gene_correlation_top_n_var = tk.StringVar(value="10")
        self.category_means_n_genes_var = tk.StringVar(value="500")
        self.spatial_variable_genes_n_var = tk.StringVar(value="200")
        self.scalebar_unit_var = tk.StringVar(value="um")
        self.section_images_var = tk.StringVar()
        self.section_images_max_px_var = tk.StringVar(value="4096")
        self.selection_mode_var = tk.BooleanVar(value=False)

        self.downsample_var = tk.StringVar()

        self.serve_var = tk.BooleanVar(value=False)
        self.port_var = tk.StringVar(value="8000")

        self.status_var = tk.StringVar(value="Ready")

    def _build_layout(self) -> None:
        shell = ctk.CTkFrame(self, **self._theme["root_frame"])
        self._register_theme_widget("root_frame", shell)
        shell.pack(fill="both", expand=True)
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(0, weight=1)

        root = ctk.CTkScrollableFrame(
            shell,
            **self._theme["root_frame"],
            scrollbar_button_color=self._app_palette["hover_bg"],
            scrollbar_button_hover_color=self._app_palette["accent"],
        )
        self.main_scroll_frame = root
        self._register_theme_widget("root_frame", root)
        root.grid(row=0, column=0, sticky="nsew", padx=16, pady=16)
        root.columnconfigure(0, weight=3, minsize=730, uniform="main_columns")
        root.columnconfigure(1, weight=2, minsize=430, uniform="main_columns")
        root.rowconfigure(0, weight=1)

        controls = ctk.CTkFrame(root, width=730, **self._theme["card_frame"])
        self._register_theme_widget("card_frame", controls)
        controls.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        controls.columnconfigure(0, weight=1)
        controls.rowconfigure(1, weight=1)
        controls_outer = controls

        side = ctk.CTkFrame(root, width=430, **self._theme["card_frame"])
        self._register_theme_widget("card_frame", side)
        side.grid(row=0, column=1, sticky="nsew")

        controls_inner = ctk.CTkFrame(controls, **self._theme["sub_frame"])
        self._register_theme_widget("sub_frame", controls_inner)
        controls_inner.grid(row=0, column=0, sticky="ew", padx=22, pady=(22, 8))
        controls = controls_inner

        side_inner = ctk.CTkFrame(side, **self._theme["sub_frame"])
        self.side_outer = side
        self.side_panel = side_inner
        self._register_theme_widget("sub_frame", side_inner)
        side_inner.pack(fill="both", expand=True, padx=22, pady=22)
        side = side_inner

        controls.columnconfigure(1, weight=1)
        side.columnconfigure(0, weight=1)
        side.rowconfigure(3, weight=1)

        hero = ctk.CTkFrame(controls, **self._theme["hero_card"])
        self._register_theme_widget("hero_card", hero)
        hero.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 16))
        hero.columnconfigure(0, weight=1)

        hero_inner = self._make_sub_frame(hero)
        hero_inner.grid(row=0, column=0, sticky="ew", padx=18, pady=18)
        hero_inner.columnconfigure(0, weight=1)

        hero_left = self._make_sub_frame(hero_inner)
        hero_left.grid(row=0, column=0, sticky="w")
        self._section_label(hero_left, "DESKTOP BUILDER").pack(anchor="w")
        self._hero_label(hero_left, "KaroSpaceBuilder").pack(anchor="w", pady=(4, 0))
        self._subheader_label(
            hero_left,
            "Export AnnData into a static KaroSpace viewer bundle with guided inputs and inspected field pickers.",
        ).pack(anchor="w", pady=(4, 0))

        tabs_toolbar = self._make_sub_frame(controls)
        self.tabs_toolbar = tabs_toolbar
        tabs_toolbar.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(0, 8))
        tabs_toolbar.columnconfigure(0, weight=1)

        self.theme_toggle_btn = self._secondary_button(tabs_toolbar, "☀", self._toggle_theme, width=42)
        self.theme_toggle_btn.grid(row=0, column=1, sticky="e", padx=(0, 8))
        self.guide_btn = self._secondary_button(tabs_toolbar, "?", self._show_guide_popup, width=42)
        self.guide_btn.grid(row=0, column=2, sticky="e")

        self._path_field(controls, 2, "Input file", self.h5ad_var, choose_file=True)

        notebook = ctk.CTkTabview(controls_outer, command=self._on_tab_selected, width=1, **self._theme["tabview"])
        self.notebook = notebook
        self._last_enabled_tab = "Basic"
        self._register_theme_widget("tabview", notebook)
        notebook.grid(row=1, column=0, sticky="ew", padx=18)
        self._inspection_gated_widgets.append(notebook)
        controls_outer.rowconfigure(1, weight=0)

        notebook.add("Basic")
        notebook.add("Colors")
        notebook.add("Genes")
        notebook.add("Cells")
        notebook.add("Advanced")
        basic_tab = notebook.tab("Basic")
        colors_tab = notebook.tab("Colors")
        genes_tab = notebook.tab("Genes")
        cells_tab = notebook.tab("Cells")
        advanced_tab = notebook.tab("Advanced")
        for tab in (basic_tab, colors_tab, genes_tab, cells_tab, advanced_tab):
            self._register_theme_widget("sub_frame", tab)

        basic_tab_outer = basic_tab
        colors_tab_outer = colors_tab
        genes_tab_outer = genes_tab
        cells_tab_outer = cells_tab
        advanced_tab_outer = advanced_tab
        for outer_tab in (basic_tab_outer, colors_tab_outer, genes_tab_outer, cells_tab_outer, advanced_tab_outer):
            outer_tab.columnconfigure(0, weight=1)
            outer_tab.rowconfigure(0, weight=1)

        basic_tab = self._make_sub_frame(basic_tab_outer)
        basic_tab.grid(row=0, column=0, sticky="nsew", padx=22, pady=18)
        colors_tab = self._make_sub_frame(colors_tab_outer)
        colors_tab.grid(row=0, column=0, sticky="nsew", padx=22, pady=18)
        genes_tab = self._make_sub_frame(genes_tab_outer)
        genes_tab.grid(row=0, column=0, sticky="nsew", padx=22, pady=18)
        cells_tab = self._make_sub_frame(cells_tab_outer)
        cells_tab.grid(row=0, column=0, sticky="nsew", padx=22, pady=18)
        advanced_tab = self._make_sub_frame(advanced_tab_outer)
        advanced_tab.grid(row=0, column=0, sticky="nsew", padx=22, pady=18)

        basic_tab.columnconfigure(1, weight=1)
        self._section_label(basic_tab, "PARAMETERS").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
        self._divider(basic_tab, height=1).grid(row=1, column=0, columnspan=3, sticky="ew", pady=(0, 12))
        row = 2
        row = self._option_row(
            basic_tab,
            row,
            "Coordinates",
            widget=self._coords_dropdown(basic_tab),
            hint="auto | obsm:spatial | obs:centroid_x_y. obs centroid mode is converted to temporary obsm['spatial'] before KaroSpace export.",
            gated=True,
        )
        self.spatialdata_table_entry = self._entry(basic_tab, self.spatialdata_table_var)
        row = self._option_row(
            basic_tab,
            row,
            "SpatialData table",
            widget=self.spatialdata_table_entry,
            hint="Optional table key for SpatialData .zarr inputs. Leave blank for H5AD.",
            gated=True,
        )
        row = self._option_row(
            basic_tab,
            row,
            "Section key",
            widget=self._groupby_dropdown(basic_tab),
            hint="obs column used to split sections (load_spatial_data(section_key=...)).",
            gated=True,
        )
        row = self._option_row(
            basic_tab,
            row,
            "Main cell annotation",
            widget=self._color_dropdown(basic_tab),
            hint="Initial viewer cell annotation (export_to_html(main_cell_annotation=...)).",
            gated=True,
        )
        row = self._option_row(
            basic_tab,
            row,
            "Outline cards by",
            widget=self._outline_dropdown(basic_tab),
            hint="Optional metadata column for panel outlines.",
            gated=True,
        )
        self._section_label(basic_tab, "HTML VIEWER").grid(row=row, column=0, columnspan=3, sticky="w", pady=(10, 8))
        row += 1
        self._divider(basic_tab, height=1).grid(row=row, column=0, columnspan=3, sticky="ew", pady=(0, 12))
        row += 1
        row = self._path_field(basic_tab, row, "Output directory", self.outdir_var, choose_file=False, gated=True)
        self.title_entry = self._entry(basic_tab, self.title_var)
        row = self._option_row(
            basic_tab,
            row,
            "Viewer title",
            widget=self.title_entry,
            hint="Title shown in the exported HTML.",
            gated=True,
        )
        self._section_label(basic_tab, "RUNTIME").grid(row=row, column=0, columnspan=3, sticky="w", pady=(10, 8))
        row += 1
        self._divider(basic_tab, height=1).grid(row=row, column=0, columnspan=3, sticky="ew", pady=(0, 12))
        row += 1
        runtime_mode_row = self._make_sub_frame(basic_tab)
        self.runtime_mode_row = runtime_mode_row
        self.numba_jit_check = ctk.CTkCheckBox(
            runtime_mode_row,
            text="Performance mode (enable numba JIT)",
            variable=self.numba_jit_var,
            **self._theme["checkbox"],
        )
        self._register_checkbox_widget(self.numba_jit_check)
        self.numba_jit_check.pack(side="left")
        row = self._option_row(
            basic_tab,
            row,
            "Runtime mode",
            widget=runtime_mode_row,
            hint="Faster on some datasets. If unstable in the desktop app, turn this off.",
            gated=True,
        )
        self.estimate_card = ctk.CTkFrame(basic_tab, **self._theme["highlight_card"])
        self._register_theme_widget("highlight_card", self.estimate_card)
        self.estimate_card.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(0, 12))
        self.estimate_card.columnconfigure(0, weight=1)

        estimate_inner = self._make_sub_frame(self.estimate_card)
        estimate_inner.grid(row=0, column=0, sticky="ew", padx=14, pady=12)
        estimate_inner.columnconfigure(0, weight=1)
        self.export_estimate_title_label = self._section_label(estimate_inner, "EXPORT ESTIMATE")
        self.export_estimate_title_label.grid(row=0, column=0, sticky="w")
        self.export_estimate_summary_label = self._body_label(
            estimate_inner,
            "Inspect a dataset to estimate exported cells, genes, elements, and HTML size.",
        )
        self.export_estimate_summary_label.configure(wraplength=690, justify="left")
        self.export_estimate_summary_label.grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.export_estimate_warning_label = self._subheader_label(estimate_inner, "")
        self.export_estimate_warning_label.configure(wraplength=690, justify="left")
        self.export_estimate_warning_label.grid(row=2, column=0, sticky="w", pady=(4, 0))
        row += 1

        cells_tab.columnconfigure(1, weight=1)
        self._section_label(cells_tab, "CELL SOURCES").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))
        self._subheader_label(
            cells_tab,
            "Configure cell-level export volume.",
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 8))
        self._divider(cells_tab, height=1).grid(row=2, column=0, columnspan=3, sticky="ew", pady=(0, 10))
        downsample_container = self._make_sub_frame(cells_tab)
        downsample_entry = ctk.CTkEntry(downsample_container, textvariable=self.downsample_var, width=100, **self._theme["entry"])
        self.downsample_entry = downsample_entry
        self._register_entry_widget(downsample_entry)
        downsample_entry.pack(side="left")
        self._body_label(downsample_container, "cells per section (blank = all)").pack(side="left", padx=(8, 0))
        self._option_row(
            cells_tab,
            3,
            "Downsample",
            widget=downsample_container,
            hint="Maps to export_to_html(downsample=...).",
            gated=True,
        )

        colors_tab.columnconfigure(0, weight=1)
        self._section_label(colors_tab, "COLOR FIELDS").grid(row=0, column=0, sticky="w", pady=(0, 6))
        self._subheader_label(
            colors_tab,
            "Build color menus from inspected obs fields.",
        ).grid(row=1, column=0, sticky="w", pady=(0, 8))
        self._divider(colors_tab, height=1).grid(row=2, column=0, sticky="ew", pady=(0, 10))
        self.additional_colors_editor = SearchableListEditor(
            colors_tab,
            label="additional_colors (obs columns)",
            height=6,
            help_text="These become color options in KaroSpace. Use Inspect to load obs columns.",
            palette=self._app_palette,
        )
        self.additional_colors_editor.grid(row=3, column=0, sticky="ew", pady=(0, 10))

        self.groupby_editor = SearchableListEditor(
            colors_tab,
            label="analysis annotations (pseudobulk/neighbor/interaction)",
            height=6,
            help_text="Used for pseudobulk_additional_annotations and optionally neighbor stats annotations.",
            palette=self._app_palette,
        )
        self.groupby_editor.grid(row=4, column=0, sticky="ew", pady=(0, 12))

        self.section_metadata_editor = SearchableListEditor(
            colors_tab,
            label="section_metadata (filter chips)",
            height=5,
            help_text="Section-level obs fields shown in the visual params bar/filter chips.",
            palette=self._app_palette,
        )
        self.section_metadata_editor.grid(row=5, column=0, sticky="ew", pady=(0, 10))

        self.section_metadata_extra_editor = SearchableListEditor(
            colors_tab,
            label="section_metadata_extra (stored only)",
            height=5,
            help_text="Section-level obs fields stored in the payload without filter chips.",
            palette=self._app_palette,
        )
        self.section_metadata_extra_editor.grid(row=6, column=0, sticky="ew", pady=(0, 12))

        genes_tab.columnconfigure(0, weight=1)
        self._section_label(genes_tab, "GENE SOURCES").grid(row=0, column=0, sticky="w", pady=(0, 6))
        self._subheader_label(
            genes_tab,
            "Select feature vectors from inspected var_names.",
        ).grid(row=1, column=0, sticky="w", pady=(0, 8))
        self._divider(genes_tab, height=1).grid(row=2, column=0, sticky="ew", pady=(0, 10))
        genes_card = ctk.CTkFrame(genes_tab, **self._theme["card_frame"])
        self._register_theme_widget("card_frame", genes_card)
        genes_card.grid(row=3, column=0, sticky="ew")
        genes_card.columnconfigure(0, weight=1)
        genes_inner = self._make_sub_frame(genes_card)
        genes_inner.grid(row=0, column=0, sticky="ew", padx=12, pady=12)
        genes_inner.columnconfigure(0, weight=1)
        self._field_label(genes_inner, "Feature Selection").grid(row=0, column=0, sticky="w", pady=(0, 6))
        self._subheader_label(
            genes_inner,
            "Selected var_names are passed directly to export_to_html(features=[...]).",
        ).grid(row=1, column=0, sticky="w", pady=(0, 8))

        feature_storage_row = self._make_sub_frame(genes_inner)
        feature_storage_row.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        self._body_label(feature_storage_row, "Storage").pack(side="left")
        self.feature_storage_combo = ctk.CTkComboBox(
            feature_storage_row,
            variable=self.feature_storage_var,
            values=["embedded", "sidecar"],
            width=120,
            state="readonly",
            **self._theme["combo"],
        )
        self._register_combo_widget(self.feature_storage_combo)
        self.feature_storage_combo.pack(side="left", padx=(6, 12))
        self._body_label(feature_storage_row, "Encoding").pack(side="left")
        self.feature_encoding_combo = ctk.CTkComboBox(
            feature_storage_row,
            variable=self.feature_encoding_var,
            values=["auto", "dense", "sparse"],
            width=110,
            state="readonly",
            **self._theme["combo"],
        )
        self._register_combo_widget(self.feature_encoding_combo)
        self.feature_encoding_combo.pack(side="left", padx=(6, 12))
        self._body_label(feature_storage_row, "Value").pack(side="left")
        self.feature_value_encoding_combo = ctk.CTkComboBox(
            feature_storage_row,
            variable=self.feature_value_encoding_var,
            values=["uint16", "uint8"],
            width=100,
            state="readonly",
            **self._theme["combo"],
        )
        self._register_combo_widget(self.feature_value_encoding_combo)
        self.feature_value_encoding_combo.pack(side="left", padx=(6, 0))

        feature_options_row = self._make_sub_frame(genes_inner)
        feature_options_row.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        self._body_label(feature_options_row, "Manifest").pack(side="left")
        self.feature_manifest_entry = ctk.CTkEntry(
            feature_options_row,
            textvariable=self.feature_manifest_path_var,
            width=170,
            **self._theme["entry"],
        )
        self._register_entry_widget(self.feature_manifest_entry)
        self.feature_manifest_entry.pack(side="left", padx=(6, 12))
        self._body_label(feature_options_row, "Shard").pack(side="left")
        self.feature_sidecar_shard_entry = ctk.CTkEntry(
            feature_options_row,
            textvariable=self.feature_sidecar_shard_size_var,
            width=70,
            **self._theme["entry"],
        )
        self._register_entry_widget(self.feature_sidecar_shard_entry)
        self.feature_sidecar_shard_entry.pack(side="left", padx=(6, 12))
        self._body_label(feature_options_row, "Sparse >= ").pack(side="left")
        self.feature_sparse_zero_threshold_entry = ctk.CTkEntry(
            feature_options_row,
            textvariable=self.feature_sparse_zero_threshold_var,
            width=70,
            **self._theme["entry"],
        )
        self._register_entry_widget(self.feature_sparse_zero_threshold_entry)
        self.feature_sparse_zero_threshold_entry.pack(side="left", padx=(6, 0))

        modalities_row = self._make_sub_frame(genes_inner)
        modalities_row.grid(row=4, column=0, sticky="ew", pady=(0, 8))
        self._body_label(modalities_row, "Modalities").pack(side="left")
        self.modalities_entry = ctk.CTkEntry(
            modalities_row,
            textvariable=self.modalities_var,
            width=260,
            **self._theme["entry"],
        )
        self._register_entry_widget(self.modalities_entry)
        self.modalities_entry.pack(side="left", padx=(6, 0))
        self._subheader_label(
            modalities_row,
            "comma-separated; non-default modalities require sidecar",
        ).pack(side="left", padx=(8, 0))

        self.manual_genes_editor = SearchableListEditor(
            genes_inner,
            label="features",
            height=8,
            help_text="Search var_names and build the exported feature list with + Add / Remove.",
            palette=self._app_palette,
            on_change=self._update_export_estimate,
        )
        self.manual_genes_editor.grid(row=5, column=0, sticky="ew")

        selection_card = ctk.CTkFrame(genes_tab, **self._theme["card_frame"])
        self._register_theme_widget("card_frame", selection_card)
        selection_card.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        selection_card.columnconfigure(0, weight=1)

        selection_inner = self._make_sub_frame(selection_card)
        selection_inner.grid(row=0, column=0, sticky="ew", padx=12, pady=12)
        selection_inner.columnconfigure(0, weight=1)
        self.selection_mode_check = ctk.CTkCheckBox(
            selection_inner,
            text="Enable tick selection mode (from Inspect H5AD)",
            variable=self.selection_mode_var,
            **self._theme["checkbox"],
        )
        self._register_checkbox_widget(self.selection_mode_check)
        self.selection_mode_check.grid(row=0, column=0, sticky="w")
        self._subheader_label(
            selection_inner,
            (
                "When enabled, selected items below are used during export for additional colors, "
                "groupby lists, and features."
            ),
        ).grid(row=1, column=0, sticky="w", pady=(4, 8))

        self.selection_mode_content = self._make_sub_frame(selection_inner)
        self.selection_mode_content.grid(row=2, column=0, sticky="ew")
        self.selection_mode_content.columnconfigure(0, weight=1)
        self.selection_mode_content.columnconfigure(1, weight=1)

        self.selection_additional_picker = SearchableMultiSelectEditor(
            self.selection_mode_content,
            label="Tick additional_colors (obs)",
            height=7,
            help_text="Multi-select obs fields to include as additional viewer colors.",
            palette=self._app_palette,
        )
        self.selection_additional_picker.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        self.selection_groupby_picker = SearchableMultiSelectEditor(
            self.selection_mode_content,
            label="Tick groupby lists (obs)",
            height=7,
            help_text="Multi-select obs columns for marker/neighbor/interaction groupby lists.",
            palette=self._app_palette,
        )
        self.selection_groupby_picker.grid(row=0, column=1, sticky="ew")

        self.selection_genes_picker = SearchableMultiSelectEditor(
            self.selection_mode_content,
            label="Tick features",
            height=8,
            help_text="Multi-select features from var_names.",
            palette=self._app_palette,
        )
        self.selection_genes_picker.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))

        selection_actions = self._make_sub_frame(self.selection_mode_content)
        selection_actions.grid(row=2, column=0, columnspan=2, sticky="w", pady=(10, 0))
        self.selection_apply_btn = self._secondary_button(
            selection_actions,
            "Apply selections to inputs",
            self._apply_tick_selections_to_inputs,
            width=190,
        )
        self.selection_apply_btn.pack(side="left")
        self.selection_sync_btn = self._secondary_button(
            selection_actions,
            "Sync from current inputs",
            self._load_inputs_into_tick_selection,
            width=185,
        )
        self.selection_sync_btn.pack(side="left", padx=(8, 0))

        advanced_tab.columnconfigure(0, weight=1)
        self._section_label(advanced_tab, "ADVANCED ANALYTICS").grid(row=0, column=0, sticky="w", pady=(0, 6))
        self._subheader_label(
            advanced_tab,
            "Fine tune marker, neighbor, interaction, and preview server behavior.",
        ).grid(row=1, column=0, sticky="w", pady=(0, 8))
        self._divider(advanced_tab, height=1).grid(row=2, column=0, sticky="ew", pady=(0, 10))
        self.advanced_content = self._make_sub_frame(advanced_tab)
        self.advanced_content.grid(row=3, column=0, sticky="ew")
        self.advanced_content.columnconfigure(1, weight=1)

        min_panel_row = self._make_sub_frame(self.advanced_content)
        min_panel_entry = ctk.CTkEntry(min_panel_row, textvariable=self.min_panel_size_var, width=90, **self._theme["entry"])
        self._register_entry_widget(min_panel_entry)
        min_panel_entry.pack(side="left")
        self._body_label(min_panel_row, "px").pack(side="left", padx=(8, 0))
        self._option_row(
            self.advanced_content,
            0,
            "Min panel size",
            widget=min_panel_row,
            hint="Minimum section panel width in exported KaroSpace HTML.",
        )

        spot_row = self._make_sub_frame(self.advanced_content)
        self.spot_size_combo = ctk.CTkComboBox(
            spot_row,
            variable=self.spot_size_var,
            values=["auto", "adaptive", "density"],
            width=120,
            state="normal",
            **self._theme["combo"],
        )
        self._register_combo_widget(self.spot_size_combo)
        self.spot_size_combo.pack(side="left")
        self._body_label(spot_row, "or numeric value").pack(side="left", padx=(8, 0))
        self._option_row(
            self.advanced_content,
            2,
            "Spot size",
            widget=spot_row,
            hint="Use auto/adaptive/density or a positive number.",
        )

        marker_row = self._make_sub_frame(self.advanced_content)
        marker_top_n_entry = ctk.CTkEntry(
            marker_row,
            textvariable=self.pseudobulk_embed_top_n_per_comparison_var,
            width=90,
            **self._theme["entry"],
        )
        self._register_entry_widget(marker_top_n_entry)
        marker_top_n_entry.pack(side="left")
        self._body_label(marker_row, "significant DE genes per comparison").pack(side="left", padx=(8, 0))
        self._option_row(
            self.advanced_content,
            4,
            "Auto-embedded DE genes",
            widget=marker_row,
            hint="Maps to pseudobulk_embed_top_n_per_comparison in embedded feature mode.",
        )

        neighbor_row = self._make_sub_frame(self.advanced_content)
        self.neighbor_auto_check = ctk.CTkCheckBox(
            neighbor_row,
            text="Auto neighbor groupby = [initial color]",
            variable=self.neighbor_auto_var,
            **self._theme["checkbox"],
        )
        self._register_checkbox_widget(self.neighbor_auto_check)
        self.neighbor_auto_check.pack(side="left")
        self._body_label(neighbor_row, "Permutations").pack(side="left", padx=(12, 4))
        neighbor_perm_entry = ctk.CTkEntry(neighbor_row, textvariable=self.neighbor_permutations_var, width=76, **self._theme["entry"])
        self._register_entry_widget(neighbor_perm_entry)
        neighbor_perm_entry.pack(side="left")
        self._body_label(neighbor_row, "Seed").pack(side="left", padx=(12, 4))
        neighbor_seed_entry = ctk.CTkEntry(neighbor_row, textvariable=self.neighbor_stats_seed_var, width=76, **self._theme["entry"])
        self._register_entry_widget(neighbor_seed_entry)
        neighbor_seed_entry.pack(side="left")
        self._option_row(
            self.advanced_content,
            6,
            "Neighbor stats",
            widget=neighbor_row,
            hint="Auto neighbor annotations = [main cell annotation]. Otherwise uses analysis annotations.",
        )

        pseudobulk_row_1 = self._make_sub_frame(self.advanced_content)
        self.pseudobulk_enabled_check = ctk.CTkCheckBox(
            pseudobulk_row_1,
            text="Enable category pseudobulk DE",
            variable=self.pseudobulk_enabled_var,
            **self._theme["checkbox"],
        )
        self._register_checkbox_widget(self.pseudobulk_enabled_check)
        self.pseudobulk_enabled_check.pack(side="left")
        self._body_label(pseudobulk_row_1, "Replicate").pack(side="left", padx=(12, 4))
        self.pseudobulk_replicate_entry = ctk.CTkEntry(
            pseudobulk_row_1,
            textvariable=self.pseudobulk_replicate_annotation_var,
            width=120,
            **self._theme["entry"],
        )
        self._register_entry_widget(self.pseudobulk_replicate_entry)
        self.pseudobulk_replicate_entry.pack(side="left")
        self._body_label(pseudobulk_row_1, "Counts layer").pack(side="left", padx=(12, 4))
        self.pseudobulk_counts_layer_entry = ctk.CTkEntry(
            pseudobulk_row_1,
            textvariable=self.pseudobulk_counts_layer_var,
            width=110,
            **self._theme["entry"],
        )
        self._register_entry_widget(self.pseudobulk_counts_layer_entry)
        self.pseudobulk_counts_layer_entry.pack(side="left")
        self._option_row(
            self.advanced_content,
            8,
            "Pseudobulk DE",
            widget=pseudobulk_row_1,
            hint="Main cell annotation is included automatically; analysis annotations are added as additional pseudobulk annotations.",
        )

        pseudobulk_row_2 = self._make_sub_frame(self.advanced_content)
        for label, variable, width in (
            ("Min cells/sample", self.pseudobulk_min_cells_per_pseudobulk_var, 70),
            ("Min reps", self.pseudobulk_min_replicates_var, 58),
            ("Min pct", self.pseudobulk_min_pct_expressed_var, 62),
            ("Padj", self.pseudobulk_padj_cutoff_var, 62),
            ("Log2FC", self.pseudobulk_log2fc_cutoff_var, 62),
            ("CPUs", self.pseudobulk_n_cpus_var, 54),
        ):
            self._body_label(pseudobulk_row_2, label).pack(side="left", padx=(0, 4))
            entry = ctk.CTkEntry(pseudobulk_row_2, textvariable=variable, width=width, **self._theme["entry"])
            self._register_entry_widget(entry)
            entry.pack(side="left", padx=(0, 8))
        self._option_row(
            self.advanced_content,
            9,
            "Pseudobulk thresholds",
            widget=pseudobulk_row_2,
            hint="Also supports cell/gene count filters below through the compact advanced fields.",
        )

        pseudobulk_row_3 = self._make_sub_frame(self.advanced_content)
        self._body_label(pseudobulk_row_3, "P adjust").pack(side="left")
        self.pseudobulk_p_adjust_combo = ctk.CTkComboBox(
            pseudobulk_row_3,
            variable=self.pseudobulk_p_adjust_method_var,
            values=["fdr_bh", "bonferroni", "holm", "none"],
            width=120,
            state="readonly",
            **self._theme["combo"],
        )
        self._register_combo_widget(self.pseudobulk_p_adjust_combo)
        self.pseudobulk_p_adjust_combo.pack(side="left", padx=(6, 12))
        self._body_label(pseudobulk_row_3, "Fit").pack(side="left")
        self.pseudobulk_fit_type_combo = ctk.CTkComboBox(
            pseudobulk_row_3,
            variable=self.pseudobulk_deseq2_fit_type_var,
            values=["parametric", "mean"],
            width=120,
            state="readonly",
            **self._theme["combo"],
        )
        self._register_combo_widget(self.pseudobulk_fit_type_combo)
        self.pseudobulk_fit_type_combo.pack(side="left", padx=(6, 12))
        self._body_label(pseudobulk_row_3, "Min cell counts").pack(side="left")
        min_cell_counts_entry = ctk.CTkEntry(
            pseudobulk_row_3,
            textvariable=self.pseudobulk_min_cell_counts_var,
            width=70,
            **self._theme["entry"],
        )
        self._register_entry_widget(min_cell_counts_entry)
        min_cell_counts_entry.pack(side="left", padx=(4, 10))
        self._body_label(pseudobulk_row_3, "Min gene counts").pack(side="left")
        min_gene_counts_entry = ctk.CTkEntry(
            pseudobulk_row_3,
            textvariable=self.pseudobulk_min_gene_counts_var,
            width=70,
            **self._theme["entry"],
        )
        self._register_entry_widget(min_gene_counts_entry)
        min_gene_counts_entry.pack(side="left", padx=(4, 0))
        self._option_row(
            self.advanced_content,
            10,
            "Pseudobulk fit",
            widget=pseudobulk_row_3,
        )

        pathway_row = self._make_sub_frame(self.advanced_content)
        self._body_label(pathway_row, "Organism").pack(side="left")
        pathway_organism_entry = ctk.CTkEntry(pathway_row, textvariable=self.pathway_organism_var, width=100, **self._theme["entry"])
        self._register_entry_widget(pathway_organism_entry)
        pathway_organism_entry.pack(side="left", padx=(4, 10))
        self._body_label(pathway_row, "Top N").pack(side="left")
        pathway_top_entry = ctk.CTkEntry(pathway_row, textvariable=self.pathway_top_n_var, width=58, **self._theme["entry"])
        self._register_entry_widget(pathway_top_entry)
        pathway_top_entry.pack(side="left", padx=(4, 10))
        self._body_label(pathway_row, "Min overlap").pack(side="left")
        pathway_overlap_entry = ctk.CTkEntry(pathway_row, textvariable=self.pathway_min_overlap_var, width=58, **self._theme["entry"])
        self._register_entry_widget(pathway_overlap_entry)
        pathway_overlap_entry.pack(side="left", padx=(4, 10))
        self._body_label(pathway_row, "GSEA perms").pack(side="left")
        pathway_perm_entry = ctk.CTkEntry(pathway_row, textvariable=self.pathway_gsea_permutations_var, width=70, **self._theme["entry"])
        self._register_entry_widget(pathway_perm_entry)
        pathway_perm_entry.pack(side="left", padx=(4, 0))
        self._option_row(
            self.advanced_content,
            11,
            "Pathways",
            widget=pathway_row,
            hint="GMT files can be supplied below as comma-separated paths; blank uses KaroSpace defaults.",
        )

        pathway_gmt_row = self._make_sub_frame(self.advanced_content)
        pathway_gmt_entry = ctk.CTkEntry(pathway_gmt_row, textvariable=self.pathway_gmt_var, **self._theme["entry"])
        self._register_entry_widget(pathway_gmt_entry)
        pathway_gmt_entry.pack(side="left", fill="x", expand=True)
        self._option_row(self.advanced_content, 12, "Pathway GMT", widget=pathway_gmt_row)

        interaction_row_1 = self._make_sub_frame(self.advanced_content)
        self.interaction_enabled_check = ctk.CTkCheckBox(
            interaction_row_1,
            text="Enable interaction markers",
            variable=self.interaction_markers_enabled_var,
            **self._theme["checkbox"],
        )
        self._register_checkbox_widget(self.interaction_enabled_check)
        self.interaction_enabled_check.pack(side="left")
        self._option_row(
            self.advanced_content,
            13,
            "Interaction markers",
            widget=interaction_row_1,
            hint="Uses main cell annotation and pseudobulk additional annotations.",
        )

        interaction_row_2 = self._make_sub_frame(self.advanced_content)
        self._body_label(interaction_row_2, "Top targets").pack(side="left")
        interaction_top_targets_entry = ctk.CTkEntry(
            interaction_row_2,
            textvariable=self.interaction_markers_top_targets_var,
            width=70,
            **self._theme["entry"],
        )
        self._register_entry_widget(interaction_top_targets_entry)
        interaction_top_targets_entry.pack(side="left", padx=(4, 10))
        self._body_label(interaction_row_2, "Top genes").pack(side="left")
        interaction_top_genes_entry = ctk.CTkEntry(
            interaction_row_2,
            textvariable=self.interaction_markers_top_genes_var,
            width=70,
            **self._theme["entry"],
        )
        self._register_entry_widget(interaction_top_genes_entry)
        interaction_top_genes_entry.pack(side="left", padx=(4, 10))
        self._body_label(interaction_row_2, "Min cells").pack(side="left")
        interaction_min_cells_entry = ctk.CTkEntry(
            interaction_row_2,
            textvariable=self.interaction_markers_min_cells_var,
            width=70,
            **self._theme["entry"],
        )
        self._register_entry_widget(interaction_min_cells_entry)
        interaction_min_cells_entry.pack(side="left", padx=(4, 10))
        self._body_label(interaction_row_2, "Min neighbors").pack(side="left")
        interaction_min_neighbors_entry = ctk.CTkEntry(
            interaction_row_2,
            textvariable=self.interaction_markers_min_neighbors_var,
            width=70,
            **self._theme["entry"],
        )
        self._register_entry_widget(interaction_min_neighbors_entry)
        interaction_min_neighbors_entry.pack(side="left", padx=(4, 0))
        self._option_row(
            self.advanced_content,
            14,
            "Interaction limits",
            widget=interaction_row_2,
            hint="Maps to interaction_markers_top_targets/top_genes/min_cells/min_neighbors.",
        )

        discovery_row = self._make_sub_frame(self.advanced_content)
        for label, variable, width in (
            ("Gene correlations", self.gene_correlation_top_n_var, 70),
            ("Category means", self.category_means_n_genes_var, 70),
            ("Spatial variable", self.spatial_variable_genes_n_var, 70),
            ("Scalebar unit", self.scalebar_unit_var, 70),
        ):
            self._body_label(discovery_row, label).pack(side="left", padx=(0, 4))
            entry = ctk.CTkEntry(discovery_row, textvariable=variable, width=width, **self._theme["entry"])
            self._register_entry_widget(entry)
            entry.pack(side="left", padx=(0, 8))
        self._option_row(
            self.advanced_content,
            15,
            "Discovery panels",
            widget=discovery_row,
            hint="Set numeric values to 0 to disable optional gene discovery summaries.",
        )

        metadata_json_row = self._make_sub_frame(self.advanced_content)
        metadata_json_row.columnconfigure(0, weight=1)
        metadata_value_order_entry = ctk.CTkEntry(
            metadata_json_row,
            textvariable=self.metadata_value_order_var,
            placeholder_text='{"condition":["control","treated"]}',
            **self._theme["entry"],
        )
        self._register_entry_widget(metadata_value_order_entry)
        metadata_value_order_entry.pack(side="left", fill="x", expand=True)
        self._option_row(
            self.advanced_content,
            16,
            "Metadata value order JSON",
            widget=metadata_json_row,
        )

        metadata_labels_row = self._make_sub_frame(self.advanced_content)
        metadata_labels_entry = ctk.CTkEntry(
            metadata_labels_row,
            textvariable=self.metadata_labels_var,
            placeholder_text='{"sample_id":"Sample"}',
            **self._theme["entry"],
        )
        self._register_entry_widget(metadata_labels_entry)
        metadata_labels_entry.pack(side="left", fill="x", expand=True)
        self._option_row(self.advanced_content, 17, "Metadata labels JSON", widget=metadata_labels_row)

        overlay_json_row = self._make_sub_frame(self.advanced_content)
        self._body_label(overlay_json_row, "Rotations").pack(side="left")
        section_rotations_entry = ctk.CTkEntry(overlay_json_row, textvariable=self.section_rotations_var, width=180, **self._theme["entry"])
        self._register_entry_widget(section_rotations_entry)
        section_rotations_entry.pack(side="left", padx=(4, 10))
        self._body_label(overlay_json_row, "Images JSON").pack(side="left")
        section_images_entry = ctk.CTkEntry(overlay_json_row, textvariable=self.section_images_var, width=180, **self._theme["entry"])
        self._register_entry_widget(section_images_entry)
        section_images_entry.pack(side="left", padx=(4, 0))
        self._option_row(
            self.advanced_content,
            18,
            "Section overlays",
            widget=overlay_json_row,
            hint="Rotations accept section:angle CSV or JSON. Images expects the KaroSpace section_images JSON object.",
        )

        deconv_row = self._make_sub_frame(self.advanced_content)
        self._body_label(deconv_row, "Deconvolutions JSON").pack(side="left")
        deconv_entry = ctk.CTkEntry(deconv_row, textvariable=self.deconvolutions_var, width=220, **self._theme["entry"])
        self._register_entry_widget(deconv_entry)
        deconv_entry.pack(side="left", padx=(4, 10))
        self._body_label(deconv_row, "Images max px").pack(side="left")
        section_images_max_entry = ctk.CTkEntry(deconv_row, textvariable=self.section_images_max_px_var, width=80, **self._theme["entry"])
        self._register_entry_widget(section_images_max_entry)
        section_images_max_entry.pack(side="left", padx=(4, 0))
        self._option_row(self.advanced_content, 19, "Overlay extras", widget=deconv_row)

        loader_row = self._make_sub_frame(self.advanced_content)
        self._body_label(loader_row, "Section order").pack(side="left")
        section_order_entry = ctk.CTkEntry(loader_row, textvariable=self.section_order_var, width=180, **self._theme["entry"])
        self._register_entry_widget(section_order_entry)
        section_order_entry.pack(side="left", padx=(4, 10))
        self._body_label(loader_row, "Metadata max cols").pack(side="left")
        metadata_max_entry = ctk.CTkEntry(loader_row, textvariable=self.metadata_max_columns_var, width=70, **self._theme["entry"])
        self._register_entry_widget(metadata_max_entry)
        metadata_max_entry.pack(side="left", padx=(4, 10))
        self.tutorial_check = ctk.CTkCheckBox(loader_row, text="Tutorial", variable=self.tutorial_var, **self._theme["checkbox"])
        self._register_checkbox_widget(self.tutorial_check)
        self.tutorial_check.pack(side="left", padx=(4, 0))
        self._option_row(
            self.advanced_content,
            20,
            "Loader/viewer extras",
            widget=loader_row,
        )

        viewer_info_row = self._make_sub_frame(self.advanced_content)
        viewer_info_entry = ctk.CTkEntry(viewer_info_row, textvariable=self.viewer_info_html_file_var, **self._theme["entry"])
        self._register_entry_widget(viewer_info_entry)
        viewer_info_entry.pack(side="left", fill="x", expand=True)
        viewer_info_button = self._secondary_button(
            viewer_info_row,
            "Info HTML",
            lambda: self._choose_file(self.viewer_info_html_file_var, optional=True),
            width=96,
        )
        viewer_info_button.pack(side="left", padx=(8, 0))
        self._option_row(
            self.advanced_content,
            21,
            "Viewer info HTML file",
            widget=viewer_info_row,
        )

        serve_row = self._make_sub_frame(self.advanced_content)
        self.serve_check = ctk.CTkCheckBox(serve_row, text="Serve after export", variable=self.serve_var, **self._theme["checkbox"])
        self._register_checkbox_widget(self.serve_check)
        self.serve_check.pack(side="left")
        self._body_label(serve_row, "Port").pack(side="left", padx=(12, 4))
        serve_port_entry = ctk.CTkEntry(serve_row, textvariable=self.port_var, width=90, **self._theme["entry"])
        self._register_entry_widget(serve_port_entry)
        serve_port_entry.pack(side="left")
        self._option_row(
            self.advanced_content,
            22,
            "Preview server",
            widget=serve_row,
            hint="Optional local server to open the latest generated KaroSpace_*.html file.",
        )
        button_row = self._make_sub_frame(controls_outer)
        button_row.grid(row=2, column=0, sticky="ew", padx=18, pady=(16, 22))

        self.inspect_btn = self._secondary_button(button_row, "Inspect Dataset", self._inspect_h5ad, width=145)
        self._style_secondary_action_button(self.inspect_btn)
        self.inspect_btn.pack(side="left")

        self.inspect_loading_label = ctk.CTkLabel(button_row, text="⟳ Inspecting...", **self._theme["section_label"])
        self._register_theme_widget("section_label", self.inspect_loading_label)

        self.export_btn = self._secondary_button(button_row, "Build Viewer", self._on_export_button, width=140)
        self.export_btn.pack(side="right")
        self._inspection_gated_widgets.append(self.export_btn)

        runtime_top = self._make_sub_frame(side)
        runtime_top.grid(row=0, column=0, sticky="ew")
        runtime_top.columnconfigure(0, weight=1)
        self.runtime_title_label = self._section_label(runtime_top, "RUNTIME")
        self.runtime_title_label.grid(row=0, column=0, sticky="w")
        self.runtime_chip_label = self._pill_label(runtime_top, text="READY", muted=True)
        self.runtime_chip_label.grid(row=0, column=1, sticky="e")
        self._right_panel_widgets.append(self.runtime_chip_label)

        self.progress = ctk.CTkProgressBar(side, mode="determinate", **self._theme["progress"])
        self._register_theme_widget("progress", self.progress)
        self.progress.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        self.progress.set(0.0)
        self._right_panel_widgets.append(self.progress)

        launch_row = self._make_sub_frame(side)
        launch_row.grid(row=2, column=0, sticky="ew", pady=(14, 12))
        self.open_output_btn = self._secondary_button(launch_row, "Open Output Folder", self._open_output_folder, width=165)
        self.open_output_btn.pack(side="left")
        self.open_viewer_btn = self._secondary_button(launch_row, "Open Viewer", self._open_viewer, width=125)
        self.open_viewer_btn.pack(side="left", padx=(10, 0))
        self._right_panel_widgets.extend([self.open_output_btn, self.open_viewer_btn])

        log_wrap = self._make_sub_frame(side)
        log_wrap.grid(row=3, column=0, sticky="nsew")
        log_wrap.columnconfigure(0, weight=1)
        log_wrap.rowconfigure(1, weight=1)

        self.event_log_label = self._section_label(log_wrap, "EVENT LOG")
        self.event_log_label.grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.log_text = ctk.CTkTextbox(log_wrap, wrap="word", **self._theme["textbox"])
        self.log_text.grid(row=1, column=0, sticky="nsew")
        self.log_text.configure(state="disabled")

        self.downsample_var.trace_add("write", lambda *_: self._update_export_estimate())
        self.section_groupby_var.trace_add("write", lambda *_: self._update_export_estimate())
        self.neighbor_auto_var.trace_add("write", lambda *_: self._update_neighbor_groupby_state())
        self.selection_mode_var.trace_add("write", lambda *_: self._update_selection_mode_visibility())
        self.status_var.trace_add("write", lambda *_: self._sync_runtime_chip())
        self.h5ad_var.trace_add("write", lambda *_: self._refresh_input_gate())
        self.theme_var.trace_add("write", lambda *_: self._sync_theme_toggle())
        self._apply_preset("default", log=False)
        self._sync_app_theme_to_viewer_setting()
        self._sync_runtime_chip()
        self._update_neighbor_groupby_state()
        self._set_selection_mode_visible(False)
        self._refresh_input_gate()
        self._update_export_estimate()

    def _path_field(
        self,
        parent: tk.Widget,
        row: int,
        label: str,
        variable: tk.StringVar,
        choose_file: bool,
        optional: bool = False,
        gated: bool = False,
    ) -> int:
        row_widgets: list[tk.Widget] = []
        label_widget = self._field_label(parent, label)
        label_widget.grid(row=row, column=0, sticky="nw", pady=(0, 8), padx=(0, 14))
        row_widgets.append(label_widget)
        placeholder = "/absolute/path/to/input.h5ad" if variable is self.h5ad_var else None
        entry = self._entry(parent, variable, placeholder=placeholder)
        entry.grid(row=row, column=1, sticky="ew", pady=(0, 8))
        row_widgets.append(entry)

        if choose_file:
            button = self._secondary_button(parent, "Browse", lambda: self._choose_file(variable, optional=optional), width=96)
            self._secondary_action_buttons.append(button)
            self._style_secondary_action_button(button)
        else:
            button = self._secondary_button(parent, "Browse", lambda: self._choose_dir(variable), width=96)
            self._secondary_action_buttons.append(button)
            self._style_secondary_action_button(button)
        button.grid(row=row, column=2, sticky="e", pady=(0, 8), padx=(10, 0))
        row_widgets.append(button)
        if gated:
            self._inspection_gated_widgets.extend(row_widgets)
        return row + 1

    def _option_row(
        self,
        parent: tk.Widget,
        row: int,
        label: str,
        widget: tk.Widget,
        hint: str | None = None,
        gated: bool = False,
    ) -> int:
        row_widgets: list[tk.Widget] = []
        label_widget = self._field_label(parent, label)
        label_widget.grid(row=row, column=0, sticky="nw", pady=(0, 4), padx=(0, 14))
        row_widgets.append(label_widget)
        widget.grid(row=row, column=1, columnspan=2, sticky="ew", pady=(0, 4))
        row_widgets.append(widget)
        row += 1
        if hint:
            hint_widget = self._subheader_label(parent, hint)
            hint_widget.grid(row=row, column=1, columnspan=2, sticky="w", pady=(0, 10))
            row_widgets.append(hint_widget)
            row += 1
        if gated:
            self._inspection_gated_widgets.extend(row_widgets)
        return row

    def _entry(self, parent: tk.Widget, variable: tk.StringVar, *, placeholder: str | None = None) -> ctk.CTkEntry:
        kwargs = dict(self._theme["entry"])
        if not placeholder:
            entry = ctk.CTkEntry(parent, textvariable=variable, **kwargs)
            self._register_entry_widget(entry)
            return entry

        entry = ctk.CTkEntry(parent, **kwargs)
        self._register_entry_widget(entry)
        placeholder_state = {"active": False, "syncing": False}

        def show_placeholder() -> None:
            if variable.get().strip():
                return
            placeholder_state["syncing"] = True
            placeholder_state["active"] = True
            entry.configure(text_color=self._app_palette["muted"])
            entry.delete(0, "end")
            entry.insert(0, placeholder)
            placeholder_state["syncing"] = False

        def show_value(value: str) -> None:
            placeholder_state["syncing"] = True
            placeholder_state["active"] = False
            entry.configure(text_color=self._app_palette["text"])
            entry.delete(0, "end")
            entry.insert(0, value)
            placeholder_state["syncing"] = False

        def sync_from_variable(*_args: object) -> None:
            if placeholder_state["syncing"]:
                return
            value = variable.get()
            if value.strip():
                show_value(value)
            elif entry.focus_get() is entry:
                placeholder_state["active"] = False
                entry.configure(text_color=self._app_palette["text"])
                entry.delete(0, "end")
            else:
                show_placeholder()

        def on_focus_in(_event: object) -> None:
            if placeholder_state["active"]:
                placeholder_state["active"] = False
                entry.configure(text_color=self._app_palette["text"])
                entry.delete(0, "end")

        def on_focus_out(_event: object) -> None:
            if not entry.get().strip():
                variable.set("")
                show_placeholder()

        def on_key_release(_event: object) -> None:
            if placeholder_state["active"] or placeholder_state["syncing"]:
                return
            placeholder_state["syncing"] = True
            variable.set(entry.get())
            placeholder_state["syncing"] = False

        variable.trace_add("write", sync_from_variable)
        entry.bind("<FocusIn>", on_focus_in)
        entry.bind("<FocusOut>", on_focus_out)
        entry.bind("<KeyRelease>", on_key_release)
        self._placeholder_refreshers.append(sync_from_variable)
        show_placeholder()
        return entry

    def _coords_dropdown(self, parent: tk.Widget) -> ctk.CTkOptionMenu:
        self.coords_menu = ctk.CTkOptionMenu(
            parent,
            variable=self.coords_var,
            values=["auto", "obsm:spatial", "obs:centroid_x_y"],
            **self._theme["combo"],
        )
        self._register_combo_widget(self.coords_menu)
        return self.coords_menu

    def _groupby_dropdown(self, parent: tk.Widget) -> ctk.CTkComboBox:
        self.groupby_combo = ctk.CTkComboBox(
            parent,
            variable=self.section_groupby_var,
            values=[],
            state="normal",
            **self._theme["combo"],
        )
        self._register_combo_widget(self.groupby_combo)
        return self.groupby_combo

    def _color_dropdown(self, parent: tk.Widget) -> ctk.CTkComboBox:
        self.color_combo = ctk.CTkComboBox(
            parent,
            variable=self.initial_color_var,
            values=[],
            state="normal",
            **self._theme["combo"],
        )
        self._register_combo_widget(self.color_combo)
        return self.color_combo

    def _outline_dropdown(self, parent: tk.Widget) -> ctk.CTkComboBox:
        self.outline_combo = ctk.CTkComboBox(
            parent,
            variable=self.outline_by_var,
            values=[],
            state="normal",
            **self._theme["combo"],
        )
        self._register_combo_widget(self.outline_combo)
        return self.outline_combo

    def _update_neighbor_groupby_state(self) -> None:
        # Groupby list is shared by marker/neighbor/interaction settings.
        # Keep it editable even when neighbor auto mode is enabled.
        self.groupby_editor.set_enabled(True)

    def _update_selection_mode_visibility(self) -> None:
        self._set_selection_mode_visible(bool(self.selection_mode_var.get()))

    def _set_selection_mode_visible(self, visible: bool) -> None:
        if visible:
            self.selection_mode_content.grid()
        else:
            self.selection_mode_content.grid_remove()

    def _load_inputs_into_tick_selection(self, *, log: bool = True) -> None:
        self.selection_additional_picker.set_selected(self.additional_colors_editor.get_items())
        self.selection_groupby_picker.set_selected(self.groupby_editor.get_items())
        self.selection_genes_picker.set_selected(self.manual_genes_editor.get_items())
        if log:
            self._log("Selection mode synced from current input lists.")

    def _apply_tick_selections_to_inputs(self) -> None:
        additional = self.selection_additional_picker.get_selected()
        groupby = self.selection_groupby_picker.get_selected()
        genes = self.selection_genes_picker.get_selected()

        self.additional_colors_editor.set_items(additional)
        self.groupby_editor.set_items(groupby)
        if genes:
            self.manual_genes_editor.set_items(genes)

        self.status_var.set("Selection picks applied")
        self._log(
            f"Applied selection mode picks: additional_colors={len(additional)}, groupby={len(groupby)}, genes={len(genes)}"
        )
        self._update_export_estimate()

    @staticmethod
    def _merge_unique(*groups: list[str]) -> list[str]:
        seen: set[str] = set()
        merged: list[str] = []
        for group in groups:
            for raw in group:
                value = str(raw).strip()
                if not value or value in seen:
                    continue
                seen.add(value)
                merged.append(value)
        return merged

    def _matches_inspected_h5ad(self, h5ad_path: Path) -> bool:
        inspected = self._inspected_h5ad_path
        if inspected is None:
            return False
        return inspected == h5ad_path.expanduser().resolve()

    def _apply_preset(self, name: str, *, log: bool = True) -> None:
        # Shared baseline.
        if not self.outdir_var.get().strip():
            self.outdir_var.set(str((Path.cwd() / "karospace_export").resolve()))
        self.coords_var.set("auto")
        self.spatialdata_table_var.set("")
        self.section_order_var.set("")
        self.metadata_value_order_var.set("")
        self.metadata_max_columns_var.set("")
        self.serve_var.set(False)
        self.port_var.set("8000")
        self.downsample_var.set("")
        self.section_groupby_var.set("sample_id")
        self.initial_color_var.set("leiden")
        self.title_var.set("KaroSpace")
        if not self.theme_var.get().strip():
            self.theme_var.set("dark")
        self.outline_by_var.set("condition")
        self.metadata_labels_var.set("")
        self.viewer_info_html_file_var.set("")
        self.tutorial_var.set(False)
        self.min_panel_size_var.set("120")
        self.spot_size_var.set("auto")
        self.numba_jit_var.set(False)
        self.feature_encoding_var.set("auto")
        self.feature_value_encoding_var.set("uint16")
        self.feature_storage_var.set("embedded")
        self.feature_manifest_path_var.set("")
        self.feature_sidecar_shard_size_var.set("256")
        self.feature_sparse_zero_threshold_var.set("0.8")
        self.modalities_var.set("")
        self.pseudobulk_embed_top_n_per_comparison_var.set("20")
        self.neighbor_auto_var.set(True)
        self.neighbor_permutations_var.set("auto")
        self.neighbor_stats_seed_var.set("0")
        self.pseudobulk_enabled_var.set(True)
        self.pseudobulk_replicate_annotation_var.set("")
        self.pseudobulk_simple_constrast_categories_var.set("")
        self.pseudobulk_counts_layer_var.set("counts")
        self.pseudobulk_min_cell_counts_var.set("0")
        self.pseudobulk_min_gene_counts_var.set("0")
        self.pseudobulk_min_cells_per_pseudobulk_var.set("20")
        self.pseudobulk_min_replicates_var.set("2")
        self.pseudobulk_min_pct_expressed_var.set("0")
        self.pseudobulk_p_adjust_method_var.set("fdr_bh")
        self.pseudobulk_padj_cutoff_var.set("0.05")
        self.pseudobulk_log2fc_cutoff_var.set("0.5")
        self.pseudobulk_deseq2_fit_type_var.set("parametric")
        self.pseudobulk_n_cpus_var.set("1")
        self.pathway_gmt_var.set("")
        self.pathway_organism_var.set("Human")
        self.pathway_top_n_var.set("20")
        self.pathway_min_overlap_var.set("3")
        self.pathway_gsea_permutations_var.set("100")
        self.interaction_markers_enabled_var.set(False)
        self.interaction_markers_top_targets_var.set("8")
        self.interaction_markers_top_genes_var.set("20")
        self.interaction_markers_min_cells_var.set("30")
        self.interaction_markers_min_neighbors_var.set("1")
        self.section_rotations_var.set("")
        self.deconvolutions_var.set("")
        self.gene_correlation_top_n_var.set("10")
        self.category_means_n_genes_var.set("500")
        self.spatial_variable_genes_n_var.set("200")
        self.scalebar_unit_var.set("um")
        self.section_images_var.set("")
        self.section_images_max_px_var.set("4096")
        self.section_groupby_var.set("sample_id")
        self.initial_color_var.set("leiden")
        self.outline_by_var.set("condition")
        self.min_panel_size_var.set("150")
        self.additional_colors_editor.set_items(["leiden_1", "leiden_2", "gmm_mana_10"])
        self.groupby_editor.set_items([])
        self.section_metadata_editor.set_items(["course", "region", "condition"])
        self.section_metadata_extra_editor.set_items([])
        self.manual_genes_editor.set_items(["Cd4", "Cd8a", "Gfap", "Mki67"])
        self.pseudobulk_embed_top_n_per_comparison_var.set("20")
        self.neighbor_auto_var.set(True)
        self.neighbor_permutations_var.set("auto")
        self.interaction_markers_enabled_var.set(False)
        self.status_var.set("Ready")

        self._update_neighbor_groupby_state()
        self._load_inputs_into_tick_selection(log=False)
        if log:
            self._log("Applied default input values.")

    def _choose_file(self, variable: tk.StringVar, optional: bool = False) -> None:
        initial_dir = str(Path(variable.get()).expanduser().parent) if variable.get() else str(Path.home() / "Downloads")
        path = filedialog.askopenfilename(initialdir=initial_dir)
        if path:
            if variable is self.h5ad_var:
                self._inspect_locked_after_press = False
                self._has_inspected_input_file = False
                self._clear_inspection_metadata()
            variable.set(path)
        elif not optional and not variable.get():
            self._log("File selection canceled.")

    def _choose_dir(self, variable: tk.StringVar) -> None:
        initial_dir = variable.get() or str(Path.home() / "Downloads")
        path = filedialog.askdirectory(initialdir=initial_dir)
        if path:
            variable.set(path)

    def _log(self, message: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{stamp}] {message}\n"
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _inspect_h5ad(self) -> None:
        path_text = self.h5ad_var.get().strip()
        if not path_text:
            messagebox.showerror("Missing input", "Pick an input .h5ad first, or enter a SpatialData .zarr path.")
            return

        path = Path(path_text).expanduser().resolve()
        if not path.exists():
            messagebox.showerror("Missing file", f"Input file not found:\n{path}")
            return

        self._inspect_locked_after_press = True
        self._refresh_input_gate()
        self._set_inspect_loading(True)
        self._log(f"Inspecting {path}")
        adata = None
        try:
            if path.suffix.lower() == ".zarr":
                import importlib

                data_loader = importlib.import_module("karospace.data_loader")
                coerce = getattr(data_loader, "_coerce_input_to_anndata")
                adata, _source_label, _table_key = coerce(
                    str(path),
                    self._parse_optional_text(self.spatialdata_table_var.get()),
                )
            else:
                ad_mod = _get_anndata()
                try:
                    adata = ad_mod.read_h5ad(path, backed="r")
                except Exception:
                    adata = ad_mod.read_h5ad(path)

            obs_cols = [str(c) for c in adata.obs.columns]
            obs_col_set = set(obs_cols)
            total_var_count = int(adata.n_vars)
            max_gene_choices = 120000
            var_name_set: set[str] | None = None
            if total_var_count > max_gene_choices:
                var_names = [str(g) for g in adata.var_names[:max_gene_choices]]
                self._log(
                    f"Large gene table detected ({total_var_count}). "
                    f"Loaded first {max_gene_choices} genes into pickers for responsiveness."
                )
            else:
                var_names = [str(g) for g in adata.var_names]
                var_name_set = set(var_names)

            self.additional_colors_editor.set_choices(obs_cols)
            self.groupby_editor.set_choices(obs_cols)
            self.section_metadata_editor.set_choices(obs_cols)
            self.section_metadata_extra_editor.set_choices(obs_cols)
            self.manual_genes_editor.set_choices(var_names)
            self.selection_additional_picker.set_choices(obs_cols)
            self.selection_groupby_picker.set_choices(obs_cols)
            self.selection_genes_picker.set_choices(var_names)
            if hasattr(self, "groupby_combo"):
                self.groupby_combo.configure(values=obs_cols)
            if hasattr(self, "color_combo"):
                self.color_combo.configure(values=obs_cols)
            if hasattr(self, "outline_combo"):
                self.outline_combo.configure(values=[""] + obs_cols)

            if self.section_groupby_var.get().strip() not in obs_col_set:
                if "sample_id" in obs_col_set:
                    self.section_groupby_var.set("sample_id")
                elif obs_cols:
                    self.section_groupby_var.set(obs_cols[0])
            section_groupby = self.section_groupby_var.get().strip()
            section_counts = (
                [int(value) for value in adata.obs[section_groupby].value_counts(dropna=False).tolist()]
                if section_groupby in obs_col_set
                else []
            )
            initial_color = self.initial_color_var.get().strip()
            initial_in_obs = initial_color in obs_col_set
            if not initial_in_obs:
                clustering_color = next(
                    (
                        column
                        for column in obs_cols
                        if column.lower().startswith(("louvain", "leiden"))
                    ),
                    None,
                )
                if clustering_color:
                    self.initial_color_var.set(clustering_color)
                elif obs_cols:
                    self.initial_color_var.set(obs_cols[0])
            if self.outline_by_var.get().strip() and self.outline_by_var.get().strip() not in obs_col_set:
                if "condition" in obs_col_set:
                    self.outline_by_var.set("condition")
                else:
                    self.outline_by_var.set("")

            existing_additional = [name for name in self.additional_colors_editor.get_items() if name in obs_col_set]
            if not existing_additional:
                existing_additional = [c for c in obs_cols if c in {"cell_type", "leiden", "sample", "sample_id", "condition"}]
                if not existing_additional:
                    existing_additional = obs_cols[: min(4, len(obs_cols))]
            self.additional_colors_editor.set_items(existing_additional)

            existing_groupby = [name for name in self.groupby_editor.get_items() if name in obs_col_set]
            if not existing_groupby:
                existing_groupby = [c for c in obs_cols if c in {"sample_id", "sample", "condition", "batch", "donor"}]
                if not existing_groupby and obs_cols:
                    existing_groupby = [obs_cols[0]]
            self.groupby_editor.set_items(existing_groupby)

            existing_section_metadata = [
                name for name in self.section_metadata_editor.get_items() if name in obs_col_set
            ]
            if not existing_section_metadata:
                existing_section_metadata = [
                    c for c in obs_cols if c in {"course", "region", "condition", "sample_id", "sample", "batch"}
                ]
                if not existing_section_metadata and obs_cols:
                    existing_section_metadata = obs_cols[: min(4, len(obs_cols))]
            self.section_metadata_editor.set_items(existing_section_metadata)

            existing_section_metadata_extra = [
                name for name in self.section_metadata_extra_editor.get_items() if name in obs_col_set
            ]
            self.section_metadata_extra_editor.set_items(existing_section_metadata_extra)

            if var_name_set is None:
                existing_genes = self.manual_genes_editor.get_items()
            else:
                existing_genes = [name for name in self.manual_genes_editor.get_items() if name in var_name_set]
            if not existing_genes:
                if var_name_set is None:
                    existing_genes = [g for g in ["Mki67", "Cd4", "Cd8a", "Gfap"] if g in var_names]
                else:
                    existing_genes = [g for g in ["Mki67", "Cd4", "Cd8a", "Gfap"] if g in var_name_set]
                if not existing_genes:
                    existing_genes = var_names[: min(10, len(var_names))]
            self.manual_genes_editor.set_items(existing_genes)
            self._load_inputs_into_tick_selection(log=False)

            if obs_cols:
                self._log(f"Loaded {len(obs_cols)} obs columns into additional_colors/groupby pickers.")
            if var_names:
                self._log(f"Loaded {len(var_names)} features into feature picker.")

            has_spatial = "spatial" in adata.obsm
            has_centroid = {"centroid_x", "centroid_y"}.issubset(set(obs_cols))
            if has_spatial:
                self.coords_var.set("obsm:spatial")
                inspected_coords_mode = "obsm:spatial"
            elif has_centroid:
                self.coords_var.set("obs:centroid_x_y")
                inspected_coords_mode = "obs:centroid_x_y"
            else:
                self.coords_var.set("auto")
                inspected_coords_mode = None

            self._inspected_h5ad_path = path
            self._inspected_var_name_set = var_name_set
            self._inspected_coords_mode = inspected_coords_mode
            self._inspected_n_cells = int(adata.n_obs)
            self._inspected_n_genes = int(adata.n_vars)
            self._inspected_obs_cols = set(obs_cols)
            self._inspected_section_counts_by_column = {}
            if section_groupby and section_counts:
                self._inspected_section_counts_by_column[section_groupby] = section_counts
            self._has_inspected_input_file = True

            self._log(
                f"obs columns: {len(obs_cols)} | cells: {adata.n_obs} | genes: {adata.n_vars} | "
                f"coords: {'obsm:spatial' if has_spatial else 'obs centroids' if has_centroid else 'not detected'}"
            )
            self.status_var.set("Inspection complete")
            self._refresh_input_gate()
            self._update_export_estimate()
        except Exception as exc:
            self._has_inspected_input_file = False
            self._clear_inspection_metadata()
            self._refresh_input_gate()
            messagebox.showerror("Inspect failed", str(exc))
            self._log(f"Inspect failed: {exc}")
        finally:
            if adata is not None and getattr(adata, "isbacked", False):
                file_obj = getattr(adata, "file", None)
                if file_obj is not None:
                    file_obj.close()
            self._set_inspect_loading(False)

    @staticmethod
    def _parse_positive_int(label: str, raw: str) -> int:
        text = str(raw).strip()
        try:
            value = int(text)
        except ValueError as exc:
            raise ValueError(f"{label} must be an integer.") from exc
        if value <= 0:
            raise ValueError(f"{label} must be > 0.")
        return value

    @staticmethod
    def _parse_non_negative_int(label: str, raw: str) -> int:
        text = str(raw).strip()
        try:
            value = int(text)
        except ValueError as exc:
            raise ValueError(f"{label} must be an integer.") from exc
        if value < 0:
            raise ValueError(f"{label} must be >= 0.")
        return value

    @staticmethod
    def _parse_non_negative_float(label: str, raw: str) -> float:
        text = str(raw).strip()
        try:
            value = float(text)
        except ValueError as exc:
            raise ValueError(f"{label} must be a number.") from exc
        if value < 0:
            raise ValueError(f"{label} must be >= 0.")
        return value

    @staticmethod
    def _parse_probability(label: str, raw: str) -> float:
        value = ExportApp._parse_non_negative_float(label, raw)
        if value > 1:
            raise ValueError(f"{label} must be between 0 and 1.")
        return value

    @staticmethod
    def _parse_csv_list(raw: str) -> list[str] | None:
        values = [item.strip() for item in str(raw or "").split(",") if item.strip()]
        return values or None

    @staticmethod
    def _parse_optional_text(raw: str) -> str | None:
        text = str(raw or "").strip()
        if not text or text.lower() in {"none", "null"}:
            return None
        return text

    @staticmethod
    def _parse_json_mapping(raw: str, label: str) -> dict | None:
        text = str(raw or "").strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{label} must be valid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValueError(f"{label} must be a JSON object.")
        return parsed

    @classmethod
    def _parse_metadata_value_order(cls, raw: str) -> dict[str, list[str]] | None:
        parsed = cls._parse_json_mapping(raw, "Metadata value order JSON")
        if parsed is None:
            return None
        out: dict[str, list[str]] = {}
        for key, values in parsed.items():
            if not isinstance(values, list):
                raise ValueError("Metadata value order JSON values must be lists.")
            out[str(key)] = [str(value) for value in values]
        return out or None

    @classmethod
    def _parse_metadata_labels(cls, raw: str) -> dict[str, str] | None:
        parsed = cls._parse_json_mapping(raw, "Metadata labels JSON")
        if parsed is None:
            return None
        out = {str(key): str(value) for key, value in parsed.items() if str(key).strip() and value is not None}
        return out or None

    @classmethod
    def _parse_string_mapping(cls, raw: str, label: str) -> dict[str, str] | None:
        parsed = cls._parse_json_mapping(raw, label)
        if parsed is None:
            return None
        out = {str(key): str(value) for key, value in parsed.items() if str(key).strip() and value is not None}
        return out or None

    @classmethod
    def _parse_section_images(cls, raw: str) -> dict[str, object] | None:
        parsed = cls._parse_json_mapping(raw, "Section images JSON")
        return parsed or None

    @staticmethod
    def _parse_json_object_or_list(raw: str, label: str) -> object | None:
        text = str(raw or "").strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{label} must be valid JSON: {exc}") from exc
        if not isinstance(parsed, (dict, list)):
            raise ValueError(f"{label} must be a JSON object or list.")
        return parsed

    @staticmethod
    def _parse_section_rotations(raw: str) -> dict[str, float] | None:
        text = str(raw or "").strip()
        if not text:
            return None
        if text.startswith("{"):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Section rotations JSON must be valid JSON: {exc}") from exc
            if not isinstance(parsed, dict):
                raise ValueError("Section rotations JSON must be an object.")
            source = parsed.items()
        else:
            items = []
            for token in text.split(","):
                token = token.strip()
                if not token:
                    continue
                if ":" not in token:
                    raise ValueError("Section rotations must use section_id:angle CSV or JSON object syntax.")
                key, value = token.split(":", 1)
                items.append((key.strip(), value.strip()))
            source = items

        out: dict[str, float] = {}
        for key, value in source:
            section_id = str(key).strip()
            if not section_id:
                continue
            try:
                out[section_id] = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Invalid rotation angle for section {section_id!r}.") from exc
        return out or None

    @staticmethod
    def _parse_spot_size(raw: str) -> float | str | None:
        text = str(raw).strip()
        if not text:
            return "auto"
        if text.lower() in {"auto", "adaptive", "density"}:
            return "auto"
        try:
            value = float(text)
        except ValueError as exc:
            raise ValueError("Spot size must be auto/adaptive/density or a positive number.") from exc
        if value <= 0:
            raise ValueError("Spot size must be > 0.")
        return value

    @staticmethod
    def _parse_neighbor_permutations(raw: str) -> int | None:
        text = str(raw).strip().lower()
        if not text or text == "auto":
            return None
        try:
            value = int(text)
        except ValueError as exc:
            raise ValueError("Neighbor permutations must be an integer or 'auto'.") from exc
        if value < 0:
            raise ValueError("Neighbor permutations must be >= 0.")
        return value

    def _read_adata_for_feature_ops(self, path: Path):
        if path.suffix.lower() == ".zarr":
            import importlib

            data_loader = importlib.import_module("karospace.data_loader")
            coerce = getattr(data_loader, "_coerce_input_to_anndata")
            adata, _source_label, _table_key = coerce(
                str(path),
                self._parse_optional_text(self.spatialdata_table_var.get()),
            )
            return adata

        ad_mod = _get_anndata()
        try:
            return ad_mod.read_h5ad(path, backed="r")
        except Exception:
            return ad_mod.read_h5ad(path)

    def _load_var_names(self, h5ad_path: Path) -> set[str]:
        if self._matches_inspected_h5ad(h5ad_path) and self._inspected_var_name_set is not None:
            return set(self._inspected_var_name_set)

        adata = None
        try:
            adata = self._read_adata_for_feature_ops(h5ad_path)
            return {str(v) for v in adata.var_names}
        finally:
            if adata is not None and getattr(adata, "isbacked", False):
                file_obj = getattr(adata, "file", None)
                if file_obj is not None:
                    file_obj.close()

    def _resolve_features(
        self,
        h5ad_path: Path,
        *,
        manual_genes_override: list[str] | None = None,
    ) -> list[str] | None:
        genes = manual_genes_override if manual_genes_override is not None else self.manual_genes_editor.get_items()
        genes = self._merge_unique(genes)
        if not genes:
            raise ValueError("Add at least one feature.")

        var_names = self._load_var_names(h5ad_path)
        missing = [gene for gene in genes if gene not in var_names]
        if missing:
            preview = ", ".join(missing[:10])
            raise ValueError(f"{len(missing)} features are missing in var_names: {preview}")
        return genes

    def _parse_config(self) -> BuilderConfig:
        h5ad_text = self.h5ad_var.get().strip()
        outdir_text = self.outdir_var.get().strip()

        if not h5ad_text:
            raise ValueError("Input file is required.")
        if not outdir_text:
            raise ValueError("Output directory is required.")

        h5ad_path = Path(h5ad_text).expanduser().resolve()
        outdir = Path(outdir_text).expanduser().resolve()
        if not h5ad_path.exists():
            raise ValueError(f"Input file not found: {h5ad_path}")

        outdir.mkdir(parents=True, exist_ok=True)

        coords_raw = self.coords_var.get().strip().lower() or "auto"
        if coords_raw not in {"auto", "obsm:spatial", "obs:centroid_x_y"}:
            raise ValueError("Coordinates must be auto, obsm:spatial, or obs:centroid_x_y.")
        coords_mode = None if coords_raw == "auto" else coords_raw

        spatialdata_table = self._parse_optional_text(self.spatialdata_table_var.get())
        section_groupby = self.section_groupby_var.get().strip()
        if not section_groupby:
            raise ValueError("Section key is required.")
        initial_color = self.initial_color_var.get().strip()
        if not initial_color:
            raise ValueError("Main cell annotation is required.")
        title = self.title_var.get().strip() or "KaroSpace"
        outline_by = self.outline_by_var.get().strip() or None
        min_panel_size = self._parse_positive_int("Min panel size", self.min_panel_size_var.get())
        spot_size = self._parse_spot_size(self.spot_size_var.get())

        downsample_text = self.downsample_var.get().strip()
        downsample = None
        if downsample_text:
            downsample = self._parse_positive_int("Downsample", downsample_text)

        additional_colors = self._merge_unique(self.additional_colors_editor.get_items())
        groupby_lists = self._merge_unique(self.groupby_editor.get_items())
        section_metadata = self._merge_unique(self.section_metadata_editor.get_items())
        section_metadata_extra = self._merge_unique(self.section_metadata_extra_editor.get_items())
        selection_mode = bool(self.selection_mode_var.get())
        manual_genes_override: list[str] | None = None

        if selection_mode:
            selected_additional = self.selection_additional_picker.get_selected()
            selected_groupby = self.selection_groupby_picker.get_selected()
            if selected_additional:
                additional_colors = self._merge_unique(selected_additional)
            if selected_groupby:
                groupby_lists = self._merge_unique(selected_groupby)
            selected_genes = self.selection_genes_picker.get_selected()
            if selected_genes:
                manual_genes_override = self._merge_unique(selected_genes)

        genes = self._resolve_features(
            h5ad_path,
            manual_genes_override=manual_genes_override,
        )

        feature_encoding = self.feature_encoding_var.get().strip().lower() or "auto"
        if feature_encoding not in {"auto", "dense", "sparse"}:
            raise ValueError("Feature encoding must be auto, dense, or sparse.")
        feature_value_encoding = self.feature_value_encoding_var.get().strip().lower() or "uint16"
        if feature_value_encoding not in {"uint16", "uint8"}:
            raise ValueError("Feature value encoding must be uint16 or uint8.")
        feature_storage = self.feature_storage_var.get().strip().lower() or "embedded"
        if feature_storage not in {"embedded", "sidecar"}:
            raise ValueError("Feature storage must be embedded or sidecar.")
        feature_manifest_path = self._parse_optional_text(self.feature_manifest_path_var.get())
        feature_sidecar_shard_size = self._parse_positive_int(
            "Feature sidecar shard size", self.feature_sidecar_shard_size_var.get()
        )
        feature_sparse_zero_threshold = self._parse_probability(
            "Feature sparse zero threshold", self.feature_sparse_zero_threshold_var.get()
        )
        modalities = self._parse_csv_list(self.modalities_var.get())

        neighbor_permutations = self._parse_neighbor_permutations(self.neighbor_permutations_var.get())
        neighbor_seed = self._parse_non_negative_int("Neighbor stats seed", self.neighbor_stats_seed_var.get() or "0")
        if bool(self.neighbor_auto_var.get()):
            neighbor_stats_groupby = [initial_color]
        else:
            neighbor_stats_groupby = groupby_lists or None
        interaction_enabled = bool(self.interaction_markers_enabled_var.get())
        pseudobulk_enabled = bool(self.pseudobulk_enabled_var.get())
        pseudobulk = "auto" if pseudobulk_enabled else None
        interaction_markers = "auto" if interaction_enabled else None
        pseudobulk_additional_annotations = groupby_lists or None
        pseudobulk_replicate_annotation = self._parse_optional_text(self.pseudobulk_replicate_annotation_var.get())
        pseudobulk_simple_constrast_categories = self._parse_json_object_or_list(
            self.pseudobulk_simple_constrast_categories_var.get(),
            "Pseudobulk simple contrast categories JSON",
        )
        pseudobulk_counts_layer = self._parse_optional_text(self.pseudobulk_counts_layer_var.get())
        pseudobulk_min_cell_counts = self._parse_non_negative_int(
            "Pseudobulk min cell counts", self.pseudobulk_min_cell_counts_var.get()
        )
        pseudobulk_min_gene_counts = self._parse_non_negative_int(
            "Pseudobulk min gene counts", self.pseudobulk_min_gene_counts_var.get()
        )
        pseudobulk_min_cells_per_pseudobulk = self._parse_positive_int(
            "Pseudobulk min cells per sample", self.pseudobulk_min_cells_per_pseudobulk_var.get()
        )
        pseudobulk_min_replicates = self._parse_positive_int(
            "Pseudobulk min replicates", self.pseudobulk_min_replicates_var.get()
        )
        pseudobulk_min_pct_expressed = self._parse_non_negative_float(
            "Pseudobulk min pct expressed", self.pseudobulk_min_pct_expressed_var.get()
        )
        pseudobulk_p_adjust_method = self.pseudobulk_p_adjust_method_var.get().strip().lower() or "fdr_bh"
        if pseudobulk_p_adjust_method not in {"fdr_bh", "bonferroni", "holm", "none"}:
            raise ValueError("Pseudobulk p adjust method must be fdr_bh, bonferroni, holm, or none.")
        pseudobulk_padj_cutoff = self._parse_probability("Pseudobulk padj cutoff", self.pseudobulk_padj_cutoff_var.get())
        pseudobulk_log2fc_cutoff = self._parse_non_negative_float(
            "Pseudobulk log2FC cutoff", self.pseudobulk_log2fc_cutoff_var.get()
        )
        pseudobulk_deseq2_fit_type = self.pseudobulk_deseq2_fit_type_var.get().strip().lower() or "parametric"
        if pseudobulk_deseq2_fit_type not in {"parametric", "mean"}:
            raise ValueError("Pseudobulk DESeq2 fit type must be parametric or mean.")
        pseudobulk_n_cpus = self._parse_positive_int("Pseudobulk CPUs", self.pseudobulk_n_cpus_var.get())
        pseudobulk_embed_top_n_per_comparison = self._parse_non_negative_int(
            "Auto-embedded DE genes", self.pseudobulk_embed_top_n_per_comparison_var.get()
        )
        pathway_gmt = self._parse_csv_list(self.pathway_gmt_var.get())
        pathway_organism = self.pathway_organism_var.get().strip() or "Human"
        pathway_top_n = self._parse_positive_int("Pathway top N", self.pathway_top_n_var.get())
        pathway_min_overlap = self._parse_positive_int("Pathway min overlap", self.pathway_min_overlap_var.get())
        pathway_gsea_permutations = self._parse_non_negative_int(
            "Pathway GSEA permutations", self.pathway_gsea_permutations_var.get()
        )
        interaction_top_targets = self._parse_positive_int(
            "Interaction top targets", self.interaction_markers_top_targets_var.get()
        )
        interaction_top_genes = self._parse_positive_int(
            "Interaction top genes", self.interaction_markers_top_genes_var.get()
        )
        interaction_min_cells = self._parse_positive_int(
            "Interaction min cells", self.interaction_markers_min_cells_var.get()
        )
        interaction_min_neighbors = self._parse_positive_int(
            "Interaction min neighbors", self.interaction_markers_min_neighbors_var.get()
        )
        metadata_value_order = self._parse_metadata_value_order(self.metadata_value_order_var.get())
        metadata_labels = self._parse_metadata_labels(self.metadata_labels_var.get())
        metadata_max_columns = None
        metadata_max_columns_text = self.metadata_max_columns_var.get().strip()
        if metadata_max_columns_text:
            metadata_max_columns = self._parse_positive_int("Metadata max columns", metadata_max_columns_text)
        section_order = self._parse_csv_list(self.section_order_var.get())
        viewer_info_html = None
        viewer_info_path = self._parse_optional_text(self.viewer_info_html_file_var.get())
        if viewer_info_path is not None:
            path = Path(viewer_info_path).expanduser()
            if not path.exists():
                raise ValueError(f"Viewer info HTML file not found: {path}")
            viewer_info_html = path.read_text(encoding="utf-8")
        section_rotations = self._parse_section_rotations(self.section_rotations_var.get())
        deconvolutions = self._parse_string_mapping(self.deconvolutions_var.get(), "Deconvolutions JSON")
        gene_correlation_top_n = self._parse_non_negative_int("Gene correlations", self.gene_correlation_top_n_var.get())
        category_means_n_genes = self._parse_non_negative_int("Category means", self.category_means_n_genes_var.get())
        spatial_variable_genes_n = self._parse_non_negative_int(
            "Spatial variable genes", self.spatial_variable_genes_n_var.get()
        )
        scalebar_unit = self.scalebar_unit_var.get().strip() or "um"
        section_images = self._parse_section_images(self.section_images_var.get())
        section_images_max_px = self._parse_positive_int("Section images max px", self.section_images_max_px_var.get())

        return BuilderConfig(
            h5ad_path=h5ad_path,
            outdir=outdir,
            coords_mode=coords_mode,
            spatialdata_table=spatialdata_table,
            section_groupby=section_groupby,
            section_order=section_order,
            section_metadata=section_metadata or None,
            section_metadata_extra=section_metadata_extra or None,
            metadata_value_order=metadata_value_order,
            metadata_max_columns=metadata_max_columns,
            initial_color=initial_color,
            title=title,
            outline_by=outline_by,
            metadata_labels=metadata_labels,
            viewer_info_html=viewer_info_html,
            tutorial=bool(self.tutorial_var.get()),
            min_panel_size=min_panel_size,
            spot_size=spot_size,
            enable_numba_jit=bool(self.numba_jit_var.get()),
            downsample=downsample,
            additional_colors=additional_colors or None,
            genes=genes,
            feature_encoding=feature_encoding,
            feature_value_encoding=feature_value_encoding,
            feature_storage=feature_storage,
            feature_manifest_path=feature_manifest_path,
            feature_sidecar_shard_size=feature_sidecar_shard_size,
            feature_sparse_zero_threshold=feature_sparse_zero_threshold,
            modalities=modalities,
            neighbor_stats_groupby=neighbor_stats_groupby,
            neighbor_stats_permutations=neighbor_permutations,
            neighbor_stats_seed=neighbor_seed,
            pseudobulk=pseudobulk,
            pseudobulk_additional_annotations=pseudobulk_additional_annotations,
            pseudobulk_replicate_annotation=pseudobulk_replicate_annotation,
            pseudobulk_simple_constrast_categories=pseudobulk_simple_constrast_categories,
            pseudobulk_counts_layer=pseudobulk_counts_layer,
            pseudobulk_min_cell_counts=pseudobulk_min_cell_counts,
            pseudobulk_min_gene_counts=pseudobulk_min_gene_counts,
            pseudobulk_min_cells_per_pseudobulk=pseudobulk_min_cells_per_pseudobulk,
            pseudobulk_min_replicates=pseudobulk_min_replicates,
            pseudobulk_min_pct_expressed=pseudobulk_min_pct_expressed,
            pseudobulk_p_adjust_method=pseudobulk_p_adjust_method,
            pseudobulk_padj_cutoff=pseudobulk_padj_cutoff,
            pseudobulk_log2fc_cutoff=pseudobulk_log2fc_cutoff,
            pseudobulk_deseq2_fit_type=pseudobulk_deseq2_fit_type,
            pseudobulk_n_cpus=pseudobulk_n_cpus,
            pseudobulk_embed_top_n_per_comparison=pseudobulk_embed_top_n_per_comparison,
            pathway_gmt=pathway_gmt,
            pathway_organism=pathway_organism,
            pathway_top_n=pathway_top_n,
            pathway_min_overlap=pathway_min_overlap,
            pathway_gsea_permutations=pathway_gsea_permutations,
            interaction_markers=interaction_markers,
            interaction_markers_top_targets=interaction_top_targets,
            interaction_markers_top_genes=interaction_top_genes,
            interaction_markers_min_cells=interaction_min_cells,
            interaction_markers_min_neighbors=interaction_min_neighbors,
            section_rotations=section_rotations,
            deconvolutions=deconvolutions,
            gene_correlation_top_n=gene_correlation_top_n,
            category_means_n_genes=category_means_n_genes,
            spatial_variable_genes_n=spatial_variable_genes_n,
            scalebar_unit=scalebar_unit,
            section_images=section_images,
            section_images_max_px=section_images_max_px,
        )

    @staticmethod
    def _import_karospace_api(*, enable_numba_jit: bool = False):
        import importlib
        import importlib.metadata as importlib_metadata
        import inspect

        # scanpy imports numba with cache=True in some code paths; in certain
        # environments this crashes during import. Disable JIT by default for
        # robust GUI startup/export unless the user explicitly enables performance mode.
        os.environ["NUMBA_DISABLE_JIT"] = "0" if bool(enable_numba_jit) else "1"

        def _install_scanpy_inspect_fallback() -> None:
            original_getsource = getattr(inspect, "getsource", None)
            if original_getsource is None:
                return
            if getattr(original_getsource, "_ksb_scanpy_fallback", False):
                return

            def _obj_module_name(obj) -> str:
                module_name = str(getattr(obj, "__module__", "") or "")
                if module_name:
                    return module_name
                if inspect.ismodule(obj):
                    return str(getattr(obj, "__name__", "") or "")
                obj_cls = getattr(obj, "__class__", None)
                if obj_cls is None:
                    return ""
                return str(getattr(obj_cls, "__module__", "") or "")

            def _ksb_safe_getsource(obj) -> str:
                try:
                    return original_getsource(obj)
                except OSError:
                    module_name = _obj_module_name(obj)
                    if module_name.startswith("scanpy"):
                        return ""
                    raise

            setattr(_ksb_safe_getsource, "_ksb_scanpy_fallback", True)
            inspect.getsource = _ksb_safe_getsource

        def _install_metadata_version_fallback() -> None:
            original_version = getattr(importlib_metadata, "version", None)
            if original_version is None:
                return
            if getattr(original_version, "_ksb_scikit_fallback", False):
                return

            def _ksb_version_with_fallback(distribution_name: str) -> str:
                try:
                    return original_version(distribution_name)
                except importlib_metadata.PackageNotFoundError as missing_error:
                    normalized = str(distribution_name).replace("_", "-").lower()
                    if normalized not in {"scikit-learn", "sklearn"}:
                        raise
                    for alias in ("scikit-learn", "scikit_learn", "sklearn"):
                        if alias == distribution_name:
                            continue
                        try:
                            return original_version(alias)
                        except importlib_metadata.PackageNotFoundError:
                            continue
                    try:
                        import sklearn  # type: ignore

                        version = getattr(sklearn, "__version__", "")
                        if version:
                            return str(version)
                    except Exception:
                        pass
                    raise missing_error

            setattr(_ksb_version_with_fallback, "_ksb_scikit_fallback", True)
            importlib_metadata.version = _ksb_version_with_fallback

        def _missing_module_name(error: BaseException) -> str | None:
            current: BaseException | None = error
            while current is not None:
                if isinstance(current, ModuleNotFoundError):
                    return getattr(current, "name", None)
                current = current.__cause__
            return None

        def _missing_metadata_name(error: BaseException) -> str | None:
            current: BaseException | None = error
            while current is not None:
                if isinstance(current, importlib_metadata.PackageNotFoundError):
                    name = getattr(current, "name", None)
                    if name:
                        return str(name)
                current = current.__cause__
            return None

        def _has_scanpy_source_error(error: BaseException) -> bool:
            current: BaseException | None = error
            while current is not None:
                if isinstance(current, OSError) and "could not get source code" in str(current).lower():
                    return True
                current = current.__cause__
            return False

        def _raise_dependency_error(error: BaseException) -> None:
            missing = _missing_module_name(error)
            if missing:
                raise RuntimeError(
                    f"Missing dependency '{missing}' required by KaroSpace. "
                    "Install dependencies in this environment (for example: "
                    "pip install scanpy or pip install -e /path/to/spatial-viewer)."
                ) from error
            missing_metadata = _missing_metadata_name(error)
            if missing_metadata:
                raise RuntimeError(
                    f"Missing package metadata for '{missing_metadata}' required by KaroSpace/scanpy. "
                    "If you are using a desktop binary, rebuild it with updated PyInstaller metadata bundling. "
                    "For source installs, reinstall dependencies in the active environment."
                ) from error
            message = str(error)
            if "cannot cache function" in message and "numba" in message.lower():
                raise RuntimeError(
                    "scanpy/numba failed during import cache initialization. "
                    "Set NUMBA_DISABLE_JIT=1 and restart KaroSpaceBuilder."
                ) from error
            if _has_scanpy_source_error(error):
                raise RuntimeError(
                    "scanpy import failed while inspecting plotting source code in a frozen app. "
                    "Rebuild KaroSpaceBuilder with updated packaging, then retry export."
                ) from error

        _install_scanpy_inspect_fallback()
        _install_metadata_version_fallback()

        def _is_new_export_api(export_func) -> bool:
            try:
                return "main_cell_annotation" in inspect.signature(export_func).parameters
            except Exception:
                return False

        def _snapshot_karospace_modules() -> dict[str, object]:
            return {name: module for name, module in sys.modules.items() if name == "karospace" or name.startswith("karospace.")}

        def _clear_karospace_modules() -> None:
            for name in list(sys.modules):
                if name == "karospace" or name.startswith("karospace."):
                    del sys.modules[name]

        def _restore_karospace_modules(snapshot: dict[str, object]) -> None:
            _clear_karospace_modules()
            sys.modules.update(snapshot)

        def _candidate_paths() -> list[Path]:
            root = Path(__file__).resolve().parents[2]
            return [
                (root / "KaroSpace").resolve(),
                (root / "spatial-viewer").resolve(),
                (Path.cwd().parent / "KaroSpace").resolve(),
                (Path.cwd().parent / "spatial-viewer").resolve(),
            ]

        def _try_candidate(candidate: Path, previous_modules: dict[str, object]):
            package_dir = candidate / "karospace"
            if not package_dir.exists():
                return None
            candidate_str = str(candidate)
            if candidate_str not in sys.path:
                sys.path.insert(0, candidate_str)
            try:
                _clear_karospace_modules()
                module = importlib.import_module("karospace")
                load_func = module.load_spatial_data
                export_func = module.export_to_html
                if _is_new_export_api(export_func):
                    return load_func, export_func
            except Exception:
                return None
            finally:
                if "karospace" not in sys.modules or not _is_new_export_api(getattr(sys.modules.get("karospace"), "export_to_html", None)):
                    _restore_karospace_modules(previous_modules)
            return None

        try:
            module = importlib.import_module("karospace")
            load_spatial_data = module.load_spatial_data
            export_to_html = module.export_to_html
            if _is_new_export_api(export_to_html):
                return load_spatial_data, export_to_html
            installed_modules = _snapshot_karospace_modules()
            for candidate in _candidate_paths():
                resolved = _try_candidate(candidate, installed_modules)
                if resolved is not None:
                    return resolved
            _restore_karospace_modules(installed_modules)
            return load_spatial_data, export_to_html
        except Exception as exc:
            root_exc = exc
            empty_modules: dict[str, object] = {}
            for candidate in _candidate_paths():
                package_dir = candidate / "karospace"
                if not package_dir.exists():
                    continue
                candidate_str = str(candidate)
                if candidate_str not in sys.path:
                    sys.path.insert(0, candidate_str)
                try:
                    _clear_karospace_modules()
                    module = importlib.import_module("karospace")
                    return module.load_spatial_data, module.export_to_html
                except Exception as inner_exc:
                    _restore_karospace_modules(empty_modules)
                    _raise_dependency_error(inner_exc)
                    continue
            _raise_dependency_error(root_exc)
            raise RuntimeError(
                "Could not import 'karospace'. Install it in this environment before exporting "
                "(for example: pip install -e /path/to/spatial-viewer)."
            ) from root_exc

    @staticmethod
    def _detect_coords_mode(h5ad_path: Path) -> str:
        ad_mod = _get_anndata()
        adata = None
        try:
            try:
                adata = ad_mod.read_h5ad(h5ad_path, backed="r")
            except Exception:
                adata = ad_mod.read_h5ad(h5ad_path)
            if "spatial" in adata.obsm:
                return "obsm:spatial"
            obs_cols = set(str(c) for c in adata.obs.columns)
            if {"centroid_x", "centroid_y"}.issubset(obs_cols):
                return "obs:centroid_x_y"
            raise ValueError(
                "Could not detect coordinates. Add adata.obsm['spatial'] or obs columns centroid_x/centroid_y."
            )
        finally:
            if adata is not None and getattr(adata, "isbacked", False):
                file_obj = getattr(adata, "file", None)
                if file_obj is not None:
                    file_obj.close()

    @staticmethod
    def _build_centroid_spatial_h5ad(h5ad_path: Path) -> Path:
        ad_mod = _get_anndata()
        np_mod = _get_numpy()
        adata = ad_mod.read_h5ad(h5ad_path)
        if "centroid_x" not in adata.obs.columns or "centroid_y" not in adata.obs.columns:
            raise ValueError("coords=obs:centroid_x_y requires obs columns centroid_x and centroid_y.")
        coords = adata.obs[["centroid_x", "centroid_y"]].to_numpy(dtype=np_mod.float32)
        adata.obsm["spatial"] = coords
        with tempfile.NamedTemporaryFile(suffix=".h5ad", prefix="karospace_builder_coords_", delete=False) as handle:
            temp_path = Path(handle.name)
        adata.write_h5ad(temp_path)
        return temp_path

    def _resolve_export_input(self, config: BuilderConfig) -> tuple[Path, str, Path | None]:
        mode = config.coords_mode
        if mode is None and self._matches_inspected_h5ad(config.h5ad_path) and self._inspected_coords_mode:
            mode = self._inspected_coords_mode
        if mode is None:
            mode = self._detect_coords_mode(config.h5ad_path)
        if mode == "obsm:spatial":
            return config.h5ad_path, "spatial", None
        if mode == "obs:centroid_x_y":
            temp_h5ad = self._build_centroid_spatial_h5ad(config.h5ad_path)
            return temp_h5ad, "spatial", temp_h5ad
        raise ValueError(f"Unsupported coordinates mode: {mode}")

    @staticmethod
    def _format_bytes(num_bytes: int) -> str:
        if num_bytes < 1024:
            return f"{num_bytes} B"
        size = float(num_bytes)
        for unit in ("KiB", "MiB", "GiB", "TiB"):
            size /= 1024.0
            if size < 1024.0 or unit == "TiB":
                return f"{size:.1f} {unit}"
        return f"{num_bytes} B"

    @staticmethod
    def _dedupe_names(values: list[str] | None) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for raw in values or []:
            name = str(raw).strip()
            if not name or name in seen:
                continue
            seen.add(name)
            out.append(name)
        return out

    def _sanitize_analytics_groupbys(
        self,
        dataset,
        *,
        marker_genes_groupby: list[str] | None,
        neighbor_stats_groupby: list[str] | None,
        interaction_markers_groupby: list[str] | None,
        neighbor_stats_permutations: int | None,
    ) -> tuple[list[str] | None, list[str], list[str] | None, list[str]]:
        warnings: list[str] = []
        marker = self._dedupe_names(marker_genes_groupby)
        neighbor = self._dedupe_names(neighbor_stats_groupby)
        interaction = self._dedupe_names(interaction_markers_groupby)

        adata = getattr(dataset, "adata", None)
        obs = getattr(adata, "obs", None)
        if obs is None:
            if neighbor_stats_groupby is None:
                warnings.append(
                    "Neighbor stats source columns could not be inspected; auto-neighbor fallback is disabled for safety."
                )
            return marker or None, neighbor, interaction or None, warnings

        obs_cols = {str(c) for c in getattr(obs, "columns", [])}
        unique_cache: dict[str, int | None] = {}

        def unique_count(column: str) -> int | None:
            if column in unique_cache:
                return unique_cache[column]
            try:
                count = int(obs[column].nunique(dropna=True))
            except Exception:
                count = None
            unique_cache[column] = count
            return count

        def drop_missing(columns: list[str], label: str) -> list[str]:
            kept: list[str] = []
            for column in columns:
                if column not in obs_cols:
                    warnings.append(f"Skipping {label} '{column}': not found in adata.obs.")
                    continue
                kept.append(column)
            return kept

        marker = drop_missing(marker, "marker groupby")
        neighbor = drop_missing(neighbor, "neighbor groupby")
        interaction = drop_missing(interaction, "interaction groupby")

        marker_kept: list[str] = []
        for column in marker:
            count = unique_count(column)
            if count is not None and count < 2:
                warnings.append(f"Skipping marker groupby '{column}': only {count} unique value.")
                continue
            if count is not None and count > self._MARKER_GROUPBY_MAX_UNIQUE:
                warnings.append(
                    f"Skipping marker groupby '{column}': {count:,} unique values exceeds "
                    f"{self._MARKER_GROUPBY_MAX_UNIQUE:,}."
                )
                continue
            marker_kept.append(column)

        interaction_kept: list[str] = []
        for column in interaction:
            count = unique_count(column)
            if count is not None and count < 2:
                warnings.append(f"Skipping interaction groupby '{column}': only {count} unique value.")
                continue
            if count is not None and count > self._INTERACTION_GROUPBY_MAX_UNIQUE:
                warnings.append(
                    f"Skipping interaction groupby '{column}': {count:,} unique values exceeds "
                    f"{self._INTERACTION_GROUPBY_MAX_UNIQUE:,}."
                )
                continue
            interaction_kept.append(column)

        permutation_factor = 3 if int(neighbor_stats_permutations or 0) > 0 else 1
        neighbor_kept: list[str] = []
        for column in neighbor:
            count = unique_count(column)
            if count is not None and count < 2:
                warnings.append(f"Skipping neighbor groupby '{column}': only {count} unique value.")
                continue
            if count is not None:
                dense_bytes = 8 * count * count * permutation_factor
                if dense_bytes > self._NEIGHBOR_MATRIX_BUDGET_BYTES:
                    warnings.append(
                        f"Skipping neighbor groupby '{column}': {count:,} unique values would require ~"
                        f"{self._format_bytes(dense_bytes)} dense memory."
                    )
                    continue
            neighbor_kept.append(column)

        if neighbor_stats_groupby is None:
            warnings.append("Neighbor stats auto-fallback disabled in builder; add explicit groupby columns if needed.")

        return marker_kept or None, neighbor_kept, interaction_kept or None, warnings

    def _set_busy(self, busy: bool) -> None:
        widgets = [
            self.inspect_btn,
            self.numba_jit_check,
            self.selection_mode_check,
            self.selection_apply_btn,
            self.selection_sync_btn,
            self.theme_toggle_btn,
        ]
        for widget in widgets:
            self._configure_widget_state(widget, not busy)
        self.additional_colors_editor.set_enabled(not busy)
        self.groupby_editor.set_enabled(not busy)
        self.section_metadata_editor.set_enabled(not busy)
        self.section_metadata_extra_editor.set_enabled(not busy)
        self.manual_genes_editor.set_enabled(not busy)
        self.selection_additional_picker.set_enabled(not busy)
        self.selection_groupby_picker.set_enabled(not busy)
        self.selection_genes_picker.set_enabled(not busy)

        if busy:
            self._set_progress(0, "Queued")
        else:
            if self.status_var.get().startswith("Export running..."):
                self.status_var.set("Ready")
        self._refresh_input_gate()

    @staticmethod
    def _coerce_progress_value(value: object) -> int:
        try:
            percent = int(round(float(value)))
        except (TypeError, ValueError):
            percent = 0
        return max(0, min(100, percent))

    def _set_progress(self, value: object, stage: str | None = None) -> None:
        percent = self._coerce_progress_value(value)
        self.progress.set(percent / 100.0)
        if stage:
            self.status_var.set(f"Export running... {percent}% | {stage}")

    def _on_export(self) -> None:
        if self._export_thread and self._export_thread.is_alive():
            messagebox.showinfo("Export running", "An export is already running.")
            return

        try:
            config = self._parse_config()
        except Exception as exc:
            messagebox.showerror("Invalid options", str(exc))
            return

        self._cancel_requested.clear()
        self._set_busy(True)
        self._log(f"Starting export: {config.h5ad_path} -> {config.outdir}")
        self._log(
            "Export options: "
            f"coords={config.coords_mode or 'auto'}, "
            f"section_key={config.section_groupby}, "
            f"main_cell_annotation={config.initial_color}, "
            f"feature_storage={config.feature_storage}, "
            f"downsample={config.downsample if config.downsample is not None else 'all'}."
        )
        self._log(
            "Gene settings: "
            f"features={len(config.genes or [])}, "
            f"feature_encoding={config.feature_encoding}."
        )
        self._log(
            "Analytics settings: "
            f"pseudobulk={'on' if config.pseudobulk else 'off'}, "
            f"pseudobulk_annotations={len(config.pseudobulk_additional_annotations or [])}, "
            f"neighbor_annotations={len(config.neighbor_stats_groupby or [])}, "
            f"neighbor_permutations={config.neighbor_stats_permutations if config.neighbor_stats_permutations is not None else 'auto'}, "
            f"interaction_markers={'on' if config.interaction_markers else 'off'}."
        )
        self._log(
            "Runtime mode: "
            f"numba_jit={'on' if config.enable_numba_jit else 'off (safe mode)'}."
        )
        serve_after_export = bool(self.serve_var.get())
        thread = threading.Thread(target=self._run_export, args=(config, serve_after_export), daemon=True)
        self._export_thread = thread
        thread.start()

    def _raise_if_cancelled(self) -> None:
        if self._cancel_requested.is_set():
            raise _ExportCancelled()

    def _run_export(self, config: BuilderConfig, serve_after_export: bool) -> None:
        stdout_tee = _EventLogTee(sys.stdout, self._queue)
        stderr_tee = _EventLogTee(sys.stderr, self._queue)
        with contextlib.redirect_stdout(stdout_tee), contextlib.redirect_stderr(stderr_tee):
            try:
                self._run_export_body(config, serve_after_export)
            finally:
                stdout_tee.flush()
                stderr_tee.flush()

    def _run_export_body(self, config: BuilderConfig, serve_after_export: bool) -> None:
        temp_h5ad: Path | None = None
        total_started = time.perf_counter()

        def emit_progress(percent: int, stage: str, detail: str | None = None) -> None:
            self._queue.put(("progress", (percent, stage, detail)))

        try:
            self._raise_if_cancelled()
            emit_progress(5, "Importing API", "Resolving karospace export functions.")
            load_spatial_data, export_to_html = self._import_karospace_api(enable_numba_jit=config.enable_numba_jit)

            self._raise_if_cancelled()
            emit_progress(12, "Preparing input", "Resolving coordinates mode and source data.")
            input_path, spatial_key, temp_h5ad = self._resolve_export_input(config)
            if temp_h5ad is not None:
                self._queue.put(("log", "Converted obs centroid_x/centroid_y to temporary obsm['spatial']."))

            self._raise_if_cancelled()
            emit_progress(
                25,
                "Loading spatial data",
                f"Reading {input_path} with groupby='{config.section_groupby}' and spatial_key='{spatial_key}'.",
            )
            load_started = time.perf_counter()
            import inspect

            load_params = inspect.signature(load_spatial_data).parameters
            if "section_key" in load_params:
                load_kwargs: dict[str, object] = {
                    "section_key": config.section_groupby,
                    "spatial_key": spatial_key,
                }
                if config.spatialdata_table:
                    load_kwargs["spatialdata_table"] = config.spatialdata_table
                if config.section_order is not None:
                    load_kwargs["section_order"] = config.section_order
                if config.section_metadata is not None:
                    load_kwargs["section_metadata"] = config.section_metadata
                if config.section_metadata_extra is not None:
                    load_kwargs["section_metadata_extra"] = config.section_metadata_extra
                if config.metadata_value_order is not None:
                    load_kwargs["metadata_value_order"] = config.metadata_value_order
                if config.metadata_max_columns is not None:
                    load_kwargs["metadata_max_columns"] = config.metadata_max_columns
                dataset = load_spatial_data(str(input_path), **load_kwargs)
            else:
                dataset = load_spatial_data(
                    str(input_path),
                    groupby=config.section_groupby,
                    spatial_key=spatial_key,
                )
            load_elapsed = time.perf_counter() - load_started
            self._raise_if_cancelled()
            emit_progress(
                55,
                "Validating analytics",
                f"Dataset loaded: sections={int(dataset.n_sections)}, cells={int(dataset.n_cells)} in {load_elapsed:.1f}s.",
            )

            marker_groupby, neighbor_groupby, interaction_groupby, guard_warnings = self._sanitize_analytics_groupbys(
                dataset,
                marker_genes_groupby=None,
                neighbor_stats_groupby=config.neighbor_stats_groupby,
                interaction_markers_groupby=(config.pseudobulk_additional_annotations if config.interaction_markers else None),
                neighbor_stats_permutations=config.neighbor_stats_permutations,
            )
            for warning in guard_warnings:
                self._queue.put(("log", warning))

            neighbor_permutations = config.neighbor_stats_permutations if neighbor_groupby else 0
            emit_progress(
                68,
                "Preparing output",
                "Resolved analytics groupby columns: "
                f"pseudobulk_additional={len(config.pseudobulk_additional_annotations or [])}, "
                f"neighbor={len(neighbor_groupby)}, "
                f"interaction={len(interaction_groupby or []) if config.interaction_markers else 0}, "
                f"neighbor_permutations={neighbor_permutations if neighbor_permutations else 'off'}.",
            )

            output_html = self._build_output_html_path(config.outdir)
            self._raise_if_cancelled()
            emit_progress(76, "Writing viewer", f"Exporting HTML viewer to {output_html}.")
            export_started = time.perf_counter()
            export_params = inspect.signature(export_to_html).parameters
            if "main_cell_annotation" in export_params:
                export_kwargs: dict[str, object] = {
                    "output_path": str(output_html),
                    "main_cell_annotation": config.initial_color,
                    "title": config.title,
                    "min_panel_size": config.min_panel_size,
                    "spot_size": config.spot_size,
                    "downsample": config.downsample,
                    "outline_by": config.outline_by,
                    "metadata_labels": config.metadata_labels,
                    "viewer_info_html": config.viewer_info_html,
                    "tutorial": config.tutorial,
                    "cell_annotations": config.additional_colors,
                    "features": config.genes,
                    "feature_encoding": config.feature_encoding,
                    "feature_value_encoding": config.feature_value_encoding,
                    "feature_storage": config.feature_storage,
                    "feature_manifest_path": config.feature_manifest_path,
                    "feature_sidecar_shard_size": config.feature_sidecar_shard_size,
                    "feature_sparse_zero_threshold": config.feature_sparse_zero_threshold,
                    "pseudobulk": config.pseudobulk,
                    "pseudobulk_additional_annotations": config.pseudobulk_additional_annotations,
                    "pseudobulk_replicate_annotation": config.pseudobulk_replicate_annotation,
                    "pseudobulk_simple_constrast_categories": config.pseudobulk_simple_constrast_categories,
                    "pseudobulk_counts_layer": config.pseudobulk_counts_layer,
                    "pseudobulk_min_cell_counts": config.pseudobulk_min_cell_counts,
                    "pseudobulk_min_gene_counts": config.pseudobulk_min_gene_counts,
                    "pseudobulk_min_cells_per_pseudobulk": config.pseudobulk_min_cells_per_pseudobulk,
                    "pseudobulk_min_replicates": config.pseudobulk_min_replicates,
                    "pseudobulk_min_pct_expressed": config.pseudobulk_min_pct_expressed,
                    "pseudobulk_p_adjust_method": config.pseudobulk_p_adjust_method,
                    "pseudobulk_padj_cutoff": config.pseudobulk_padj_cutoff,
                    "pseudobulk_log2fc_cutoff": config.pseudobulk_log2fc_cutoff,
                    "pseudobulk_deseq2_fit_type": config.pseudobulk_deseq2_fit_type,
                    "pseudobulk_n_cpus": config.pseudobulk_n_cpus,
                    "pseudobulk_embed_top_n_per_comparison": config.pseudobulk_embed_top_n_per_comparison,
                    "pathway_gmt": config.pathway_gmt,
                    "pathway_organism": config.pathway_organism,
                    "pathway_top_n": config.pathway_top_n,
                    "pathway_min_overlap": config.pathway_min_overlap,
                    "pathway_gsea_permutations": config.pathway_gsea_permutations,
                    "neighbor_stats_annotations": neighbor_groupby,
                    "neighbor_stats_permutations": neighbor_permutations,
                    "neighbor_stats_seed": config.neighbor_stats_seed,
                    "interaction_markers": config.interaction_markers,
                    "interaction_markers_top_targets": config.interaction_markers_top_targets,
                    "interaction_markers_top_genes": config.interaction_markers_top_genes,
                    "interaction_markers_min_cells": config.interaction_markers_min_cells,
                    "interaction_markers_min_neighbors": config.interaction_markers_min_neighbors,
                    "section_rotations": config.section_rotations,
                    "deconvolutions": config.deconvolutions,
                    "gene_correlation_top_n": config.gene_correlation_top_n,
                    "category_means_n_genes": config.category_means_n_genes,
                    "spatial_variable_genes_n": config.spatial_variable_genes_n,
                    "scalebar_unit": config.scalebar_unit,
                    "modalities": config.modalities,
                    "section_images": config.section_images,
                    "section_images_max_px": config.section_images_max_px,
                }
                export_kwargs = {key: value for key, value in export_kwargs.items() if key in export_params}
                output_value = export_to_html(dataset, **export_kwargs)
            else:
                output_value = export_to_html(
                    dataset,
                    output_path=str(output_html),
                    color=config.initial_color,
                    title=config.title,
                    min_panel_size=config.min_panel_size,
                    spot_size=config.spot_size,
                    downsample=config.downsample,
                    outline_by=config.outline_by,
                    additional_colors=config.additional_colors,
                    genes=config.genes,
                    use_hvgs=False,
                    hvg_limit=len(config.genes or []),
                    marker_genes_groupby=marker_groupby,
                    marker_genes_top_n=config.pseudobulk_embed_top_n_per_comparison,
                    neighbor_stats_groupby=neighbor_groupby,
                    neighbor_stats_permutations=neighbor_permutations,
                    neighbor_stats_seed=config.neighbor_stats_seed,
                    interaction_markers_groupby=interaction_groupby if config.interaction_markers else None,
                    interaction_markers_top_targets=config.interaction_markers_top_targets,
                    interaction_markers_top_genes=config.interaction_markers_top_genes,
                    interaction_markers_min_cells=config.interaction_markers_min_cells,
                    interaction_markers_min_neighbors=config.interaction_markers_min_neighbors,
                )
            output_html_path = Path(output_value).expanduser()
            export_elapsed = time.perf_counter() - export_started
            self._raise_if_cancelled()
            emit_progress(95, "Finalizing", f"Viewer bundle created in {export_elapsed:.1f}s: {output_html_path}")

            result = AppResult(
                outdir=output_html_path.parent,
                n_cells=int(dataset.n_cells),
                n_sections=int(dataset.n_sections),
                output_html=output_html_path,
            )
            total_elapsed = time.perf_counter() - total_started
            emit_progress(100, "Complete", f"Total export time: {total_elapsed:.1f}s.")
            self._queue.put(("done", result))
            if serve_after_export:
                self._raise_if_cancelled()
                self._queue.put(("log", "Starting preview server for the exported viewer."))
                self._queue.put(("start_server", output_html_path))
        except _ExportCancelled:
            self._queue.put(("canceled", None))
        except Exception:
            self._queue.put(("error", traceback.format_exc()))
        finally:
            if temp_h5ad is not None:
                try:
                    temp_h5ad.unlink(missing_ok=True)
                except Exception:
                    pass

    def _poll_events(self) -> None:
        while True:
            try:
                kind, payload = self._queue.get_nowait()
            except queue.Empty:
                break

            if kind == "done":
                self._set_busy(False)
                self._cancel_requested.clear()
                result = payload
                assert isinstance(result, AppResult)
                self._last_outdir = result.outdir
                self._last_output_html = result.output_html
                self._log(
                    f"Export complete. sections={result.n_sections}, cells={result.n_cells}, html={result.output_html}"
                )
                self.status_var.set("Export complete")
            elif kind == "canceled":
                self._set_busy(False)
                self._cancel_requested.clear()
                self._log("Export canceled.")
                self.status_var.set("Canceled")
            elif kind == "start_server":
                outdir = payload
                assert isinstance(outdir, Path)
                self._start_server(outdir)
            elif kind == "progress":
                if not isinstance(payload, tuple) or len(payload) < 2:
                    continue
                percent, stage = payload[0], str(payload[1]).strip()
                detail = str(payload[2]).strip() if len(payload) >= 3 and payload[2] is not None else ""
                self._set_progress(percent, stage or None)
                if detail:
                    self._log(detail)
            elif kind == "log":
                self._log(str(payload))
            elif kind == "error":
                self._set_busy(False)
                self._cancel_requested.clear()
                details = str(payload)
                self._log("Export failed. See traceback in popup.")
                self.status_var.set("Export failed")
                messagebox.showerror("Export failed", details)

        self.after(120, self._poll_events)

    def _build_output_html_path(self, outdir: Path) -> Path:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = f"{self._OUTPUT_HTML_BASENAME}_{stamp}"
        candidate = outdir / f"{base}.html"
        counter = 1
        while candidate.exists():
            candidate = outdir / f"{base}_{counter:02d}.html"
            counter += 1
        return candidate

    def _resolve_viewer_html(self, outdir: Path) -> Path:
        pattern = f"{self._OUTPUT_HTML_BASENAME}_*.html"
        candidates = sorted(outdir.glob(pattern))
        if candidates:
            return candidates[-1]
        legacy_named = outdir / f"{self._OUTPUT_HTML_BASENAME}.html"
        if legacy_named.exists():
            return legacy_named
        legacy = outdir / "index.html"
        if legacy.exists():
            return legacy
        return outdir / pattern.replace("*", "YYYYMMDD_HHMMSS")

    def _resolve_viewer_from_state(self) -> Path | None:
        if self._last_output_html is not None and self._last_output_html.exists():
            return self._last_output_html
        outdir = self._last_outdir or (Path(self.outdir_var.get().strip()).expanduser() if self.outdir_var.get().strip() else None)
        if outdir is None:
            return None
        return self._resolve_viewer_html(outdir)

    def _start_server(self, target_path: Path | None = None) -> None:
        if target_path is None:
            viewer_file = self._resolve_viewer_from_state()
        else:
            viewer_file = target_path if target_path.suffix.lower() == ".html" else self._resolve_viewer_html(target_path)

        if viewer_file is None:
            messagebox.showinfo("No export", "Run an export first.")
            return
        target = viewer_file.parent

        try:
            port = int(self.port_var.get().strip())
        except ValueError:
            messagebox.showerror("Invalid port", "Port must be an integer.")
            return

        if self._server is not None:
            self._stop_server()

        handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(target))

        try:
            server = _ThreadingHTTPServer(("127.0.0.1", port), handler)
        except OSError as exc:
            messagebox.showerror("Server start failed", str(exc))
            self._log(f"Could not start server: {exc}")
            return

        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        self._server = server
        self._server_thread = thread
        self._log(f"Serving {target} at http://127.0.0.1:{port}/{viewer_file.name}")
        self.status_var.set(f"Serving on :{port}")
        webbrowser.open_new_tab(f"http://127.0.0.1:{port}/{viewer_file.name}")

    def _stop_server(self) -> None:
        if self._server is None:
            return

        self._server.shutdown()
        self._server.server_close()
        self._server = None
        self._server_thread = None
        self._log("Preview server stopped")
        if not (self._export_thread and self._export_thread.is_alive()):
            self.status_var.set("Ready")

    def _open_output_folder(self) -> None:
        path = self._last_outdir or (Path(self.outdir_var.get().strip()).expanduser() if self.outdir_var.get().strip() else None)
        if path is None:
            messagebox.showinfo("No output", "Pick an output directory first.")
            return
        self._open_path(path)

    def _open_viewer(self) -> None:
        viewer = self._resolve_viewer_from_state()
        if viewer is None:
            messagebox.showinfo("No output", "Run an export first.")
            return

        if self._server is not None:
            try:
                port = int(self.port_var.get().strip())
            except ValueError:
                port = 8000
            webbrowser.open_new_tab(f"http://127.0.0.1:{port}/{viewer.name}")
            return

        if not viewer.exists():
            messagebox.showerror("Viewer missing", f"Expected file not found:\n{viewer}")
            return

        webbrowser.open_new_tab(viewer.resolve().as_uri())

    def _open_path(self, path: Path) -> None:
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            elif os.name == "nt":  # pragma: no cover - platform branch
                os.startfile(str(path))
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:
            messagebox.showerror("Open failed", str(exc))
            self._log(f"Open path failed: {exc}")

    def _on_close(self) -> None:
        self._stop_server()
        self.destroy()


def main() -> int:
    if tk is None:
        raise RuntimeError(
            "Tkinter is not available in this Python environment. "
            f"Original import error: {TK_IMPORT_ERROR}"
        )

    app = ExportApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
