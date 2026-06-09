"""Settings dialog – tabbed, Win11-style dark UI."""
from __future__ import annotations

import sys
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QKeyEvent, QPainter
from PyQt6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDialog, QFrame,
    QGroupBox, QHBoxLayout, QLabel, QProgressBar,
    QPushButton, QRadioButton, QScrollArea, QSizePolicy, QSlider,
    QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from emoji_image_loader import STYLE_INFO, cached_styles, style_has_cache
from emoji_pack_manager import EmojiPackManager
from hotkey_manager import HotkeyManager
import startup_manager

# ---------------------------------------------------------------------------
# Colour constants (match picker_window)
# ---------------------------------------------------------------------------
BG          = "#202020"
BG_ELEVATED = "#2d2d2d"
BG_HOVER    = "#3a3a3a"
FG          = "#ffffff"
FG_DIM      = "#9d9d9d"
ACCENT      = "#0078d4"
BORDER      = "#3d3d3d"

_BASE_STYLE = f"""
    QDialog, QWidget {{
        background: {BG};
        color: {FG};
        font-size: 13px;
    }}
    QTabWidget::pane {{
        border: 1px solid {BORDER};
        border-radius: 6px;
        background: {BG};
    }}
    QTabBar::tab {{
        background: {BG_ELEVATED};
        color: {FG_DIM};
        padding: 7px 18px;
        border: none;
        border-bottom: 2px solid transparent;
    }}
    QTabBar::tab:selected {{
        color: {FG};
        border-bottom: 2px solid {ACCENT};
        background: {BG};
    }}
    QTabBar::tab:hover:!selected {{
        color: {FG};
        background: {BG_HOVER};
    }}
    QComboBox {{
        background: {BG_ELEVATED};
        border: 1px solid {BORDER};
        border-radius: 5px;
        color: {FG};
        padding: 4px 8px;
        min-height: 28px;
    }}
    QComboBox:focus {{ border-color: {ACCENT}; }}
    QComboBox QAbstractItemView {{
        background: {BG_ELEVATED};
        color: {FG};
        selection-background-color: {ACCENT};
        border: 1px solid {BORDER};
    }}
    QComboBox::drop-down {{ border: none; width: 24px; }}
    QCheckBox {{
        color: {FG};
        spacing: 8px;
    }}
    QCheckBox::indicator {{
        width: 18px; height: 18px;
        border-radius: 4px;
        border: 1.5px solid {BORDER};
        background: {BG_ELEVATED};
    }}
    QCheckBox::indicator:checked {{
        background: {ACCENT};
        border-color: {ACCENT};
        image: url(none);
    }}
    QRadioButton {{
        color: {FG};
        spacing: 8px;
    }}
    QRadioButton::indicator {{
        width: 16px; height: 16px;
        border-radius: 8px;
        border: 1.5px solid {BORDER};
        background: {BG_ELEVATED};
    }}
    QRadioButton::indicator:checked {{
        background: {ACCENT};
        border-color: {ACCENT};
    }}
    QPushButton {{
        background: {BG_ELEVATED};
        color: {FG};
        border: 1px solid {BORDER};
        border-radius: 5px;
        padding: 5px 14px;
        min-height: 28px;
    }}
    QPushButton:hover {{ background: {BG_HOVER}; border-color: {ACCENT}; }}
    QPushButton:pressed {{ background: {ACCENT}; border-color: {ACCENT}; }}
    QGroupBox {{
        border: 1px solid {BORDER};
        border-radius: 6px;
        margin-top: 12px;
        padding-top: 6px;
        color: {FG_DIM};
        font-size: 11px;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 8px;
    }}
    QSlider::groove:horizontal {{
        background: {BORDER};
        height: 4px;
        border-radius: 2px;
    }}
    QSlider::handle:horizontal {{
        background: {ACCENT};
        width: 14px; height: 14px;
        margin: -5px 0;
        border-radius: 7px;
    }}
    QSlider::sub-page:horizontal {{
        background: {ACCENT};
        border-radius: 2px;
    }}
"""


def _label(text: str, dim: bool = False) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(f"color: {'#9d9d9d' if dim else '#ffffff'}; font-size: 13px;")
    return lbl


def _section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet("color: #ffffff; font-size: 14px; font-weight: 600; padding-top: 8px;")
    return lbl


# ---------------------------------------------------------------------------
# Hotkey capture widget
# ---------------------------------------------------------------------------

class HotkeyCapture(QPushButton):
    """Click to start recording; press the desired key combination."""

    hotkey_captured = pyqtSignal(str)   # pynput-format string

    _MODS_PYNPUT = {
        Qt.Key.Key_Control:   "<ctrl>",
        Qt.Key.Key_Alt:       "<alt>",
        Qt.Key.Key_Shift:     "<shift>",
        Qt.Key.Key_Meta:      "<cmd>",
        Qt.Key.Key_Super_L:   "<super>",
        Qt.Key.Key_Super_R:   "<super>",
    }

    def __init__(self, current_hotkey: str, parent=None) -> None:
        super().__init__(parent)
        self._current = current_hotkey
        self._recording = False
        self._held_mods: list[str] = []
        self.setMinimumWidth(180)
        self._refresh_text()

    def _refresh_text(self) -> None:
        if self._recording:
            self.setText("⏺  Press key combination…")
            self.setStyleSheet(
                f"background: {BG_HOVER}; color: {FG}; border: 1.5px solid {ACCENT};"
                f" border-radius: 5px; padding: 5px 14px;"
            )
        else:
            self.setText(HotkeyManager.to_display(self._current))
            self.setStyleSheet("")

    def mousePressEvent(self, _event) -> None:   # type: ignore[override]
        if not self._recording:
            self._recording = True
            self._held_mods = []
            self._refresh_text()
            self.grabKeyboard()

    def keyPressEvent(self, event: QKeyEvent) -> None:   # type: ignore[override]
        if not self._recording:
            super().keyPressEvent(event)
            return
        key = Qt.Key(event.key())
        if key == Qt.Key.Key_Escape:
            self._stop_recording()
            return

        mod = self._MODS_PYNPUT.get(key)
        if mod and mod not in self._held_mods:
            self._held_mods.append(mod)
            return

        # Non-modifier key – build the combo
        mods  = list(self._held_mods)
        char  = event.text().lower()
        if not char or not char.isprintable():
            char = key.name.lower() if hasattr(key, "name") else ""
        if not char:
            return

        parts = mods + [char]
        hotkey = "+".join(parts)
        self._current = hotkey
        self._stop_recording()
        self.hotkey_captured.emit(hotkey)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:   # type: ignore[override]
        key = Qt.Key(event.key())
        mod = self._MODS_PYNPUT.get(key)
        if mod and mod in self._held_mods:
            self._held_mods.remove(mod)
        super().keyReleaseEvent(event)

    def _stop_recording(self) -> None:
        self._recording = False
        self.releaseKeyboard()
        self._refresh_text()


# ---------------------------------------------------------------------------
# Settings tabs
# ---------------------------------------------------------------------------

def _make_general_tab(config, hotkey_mgr, picker) -> QWidget:
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(16, 12, 16, 12)
    lay.setSpacing(10)

    # ── Hotkey ──────────────────────────────────────────────────────────
    lay.addWidget(_section_label("Global Shortcut"))
    row_hk = QHBoxLayout()
    row_hk.addWidget(_label("Open picker with"))
    hk_capture = HotkeyCapture(config.get("hotkey", "<ctrl>+<alt>+e"))
    row_hk.addWidget(hk_capture)
    row_hk.addStretch()
    lay.addLayout(row_hk)

    def _on_hotkey(new_hk: str) -> None:
        config.set("hotkey", new_hk)
        hotkey_mgr.restart()

    hk_capture.hotkey_captured.connect(_on_hotkey)

    # ── Output mode ─────────────────────────────────────────────────────
    lay.addWidget(_section_label("On Emoji Click"))

    modes = [
        ("type",      "Type into active window"),
        ("clipboard", "Copy to clipboard"),
        ("both",      "Both (type + copy)"),
    ]
    grp = QButtonGroup(w)
    current_mode = config.get("output_mode", "type")
    for value, text in modes:
        rb = QRadioButton(text)
        rb.setChecked(value == current_mode)
        grp.addButton(rb)
        lay.addWidget(rb)

        def _make_handler(v):
            def _h(checked):
                if checked:
                    config.set("output_mode", v)
            return _h

        rb.toggled.connect(_make_handler(value))

    # ── Behaviour ───────────────────────────────────────────────────────
    lay.addWidget(_section_label("Behaviour"))

    close_cb = QCheckBox("Close picker after selecting an emoji")
    close_cb.setChecked(bool(config.get("close_on_select", True)))
    close_cb.toggled.connect(lambda v: config.set("close_on_select", v))
    lay.addWidget(close_cb)

    # ── Startup ─────────────────────────────────────────────────────────
    lay.addWidget(_section_label("System"))

    boot_cb = QCheckBox("Launch on login / startup")
    boot_cb.setChecked(startup_manager.is_enabled())

    def _on_boot(checked: bool) -> None:
        config.set("start_on_boot", checked)
        if checked:
            startup_manager.enable()
        else:
            startup_manager.disable()

    boot_cb.toggled.connect(_on_boot)
    lay.addWidget(boot_cb)

    lay.addStretch()
    return w


def _rebuild_style_box(style_box: QComboBox, current_style: str) -> None:
    """Re-populate *style_box* with only the styles that have cache (+ system)."""
    style_box.blockSignals(True)
    style_box.clear()
    cached = cached_styles()
    # Always add system first
    style_box.addItem(STYLE_INFO["system"], "system")
    for s in cached:
        if s != "system":
            style_box.addItem(STYLE_INFO.get(s, s), s)
    # Restore selection (fall back to system if current style isn't cached anymore)
    idx = style_box.findData(current_style)
    if idx < 0:
        idx = style_box.findData("system")
    style_box.setCurrentIndex(idx)
    style_box.blockSignals(False)


def _make_appearance_tab(config, image_loader, picker) -> QWidget:
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(16, 12, 16, 12)
    lay.setSpacing(10)

    # ── Emoji style ─────────────────────────────────────────────────────
    lay.addWidget(_section_label("Emoji Style"))

    style_box = QComboBox()
    current_style = config.get("emoji_style", "system")
    _rebuild_style_box(style_box, current_style)
    lay.addWidget(style_box)

    note = _label(
        "Only styles that have been downloaded are shown below.\n"
        "Use the \"Manage Emoji Packs\" button to download or remove styles.",
        dim=True,
    )
    note.setWordWrap(True)
    lay.addWidget(note)

    # ── Manage packs button ─────────────────────────────────────────────
    manage_btn = QPushButton("📦  Manage Emoji Packs…")
    manage_btn.setStyleSheet(f"""
        QPushButton {{
            background: {BG_ELEVATED}; color: {FG};
            border: 1px solid {BORDER}; border-radius: 5px;
            padding: 6px 14px;
        }}
        QPushButton:hover {{ background: {BG_HOVER}; border-color: {ACCENT}; }}
        QPushButton:pressed {{ background: {ACCENT}; }}
    """)

    def _on_manage() -> None:
        dialog = EmojiPackManager(image_loader, w)
        dialog.packs_changed.connect(lambda: _rebuild_style_box(
            style_box, config.get("emoji_style", "system")
        ))
        dialog.exec()

    manage_btn.clicked.connect(_on_manage)
    lay.addWidget(manage_btn)

    # ── Download progress bar ───────────────────────────────────────────
    progress_bar = QProgressBar()
    progress_bar.setRange(0, 100)
    progress_bar.setValue(0)
    progress_bar.setTextVisible(True)
    progress_bar.setFixedHeight(18)
    progress_bar.setStyleSheet(f"""
        QProgressBar {{
            background: {BG_ELEVATED};
            border: 1px solid {BORDER};
            border-radius: 4px;
            text-align: center;
            color: {FG};
            font-size: 10px;
        }}
        QProgressBar::chunk {{
            background: {ACCENT};
            border-radius: 3px;
        }}
    """)
    progress_bar.hide()
    lay.addWidget(progress_bar)

    def _on_progress(done: int, total: int) -> None:
        if total == 0:
            progress_bar.hide()
            return
        pct = int(done / total * 100) if total else 0
        progress_bar.setValue(pct)
        progress_bar.setFormat(f"Downloading… {done} / {total}")
        progress_bar.show()
        if done >= total:
            progress_bar.setFormat("✓ Download complete")
            QTimer.singleShot(2000, progress_bar.hide)

    image_loader.progress_updated.connect(_on_progress)

    # ── Emoji size ──────────────────────────────────────────────────────
    lay.addWidget(_section_label("Emoji Size"))

    size_row = QHBoxLayout()
    size_slider = QSlider(Qt.Orientation.Horizontal)
    size_slider.setRange(24, 56)
    size_slider.setSingleStep(2)
    size_slider.setPageStep(4)
    size_slider.setValue(int(config.get("emoji_size", 42)))
    size_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
    size_slider.setTickInterval(8)
    size_label = QLabel(f"{size_slider.value()}px")
    size_label.setFixedWidth(36)
    size_label.setStyleSheet(f"color: {FG}; font-size: 13px;")
    size_row.addWidget(size_slider)
    size_row.addWidget(size_label)
    lay.addLayout(size_row)

    def _on_size_change(val: int) -> None:
        val = ((val + 1) // 2) * 2
        size_slider.setValue(val)
        size_label.setText(f"{val}px")
        config.set("emoji_size", val)
        picker.apply_grid_settings()

    size_slider.valueChanged.connect(_on_size_change)

    # ── Columns ─────────────────────────────────────────────────────────
    lay.addWidget(_section_label("Grid Columns"))

    cols_row = QHBoxLayout()
    cols_row.addWidget(_label("Number of columns"))
    cols_spin = QSpinBox()
    cols_spin.setRange(6, 12)
    cols_spin.setValue(int(config.get("columns", 8)))
    cols_spin.setFixedWidth(64)
    cols_spin.setStyleSheet(f"""
        QSpinBox {{
            background: {BG_ELEVATED};
            border: 1px solid {BORDER};
            border-radius: 5px;
            color: {FG};
            padding: 4px 6px;
        }}
        QSpinBox:focus {{ border-color: {ACCENT}; }}
    """)
    cols_row.addWidget(cols_spin)
    cols_row.addStretch()
    lay.addLayout(cols_row)

    def _on_cols_change(val: int) -> None:
        config.set("columns", val)
        picker.apply_grid_settings()

    cols_spin.valueChanged.connect(_on_cols_change)

    # ── Style change handler (wired after the box is built) ─────────────
    def _on_style_change(_idx: int) -> None:
        val = style_box.currentData()
        config.set("emoji_style", val)
        image_loader.set_style(val)
        picker.refresh_style()

    style_box.currentIndexChanged.connect(_on_style_change)

    lay.addStretch()
    return w


# ---------------------------------------------------------------------------
# SettingsWindow
# ---------------------------------------------------------------------------

class SettingsWindow(QDialog):
    def __init__(self, config, hotkey_mgr, image_loader, picker, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("MojiTap — Settings")
        self.setFixedSize(460, 500)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.setStyleSheet(_BASE_STYLE)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        tabs = QTabWidget(self)
        tabs.addTab(_make_general_tab(config, hotkey_mgr, picker), "General")
        tabs.addTab(_make_appearance_tab(config, image_loader, picker), "Appearance")
        lay.addWidget(tabs)

        # ── Bottom button row ────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(12, 8, 12, 12)
        btn_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)
        lay.addLayout(btn_row)
