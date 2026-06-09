"""Emoji Pack Manager – download / uninstall emoji styles.

Opened from the Appearance tab in settings.  Lists all available emoji
packs (non-system styles) and lets the user download or remove them.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QFont, QDesktopServices
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from emoji_image_loader import (
    STYLE_INFO, STYLE_SOURCE, _CACHE_ROOT, cached_styles, style_has_cache,
)

# ---------------------------------------------------------------------------
# Colour constants (match settings_window)
# ---------------------------------------------------------------------------
BG          = "#202020"
BG_ELEVATED = "#2d2d2d"
BG_HOVER    = "#3a3a3a"
FG          = "#ffffff"
FG_DIM      = "#9d9d9d"
ACCENT      = "#0078d4"
BORDER      = "#3d3d3d"

_STYLE = f"""
    QDialog, QWidget {{ background: {BG}; color: {FG}; font-size: 13px; }}
    QPushButton {{
        background: {BG_ELEVATED}; color: {FG};
        border: 1px solid {BORDER}; border-radius: 5px;
        padding: 5px 14px; min-height: 26px;
    }}
    QPushButton:hover {{ background: {BG_HOVER}; border-color: {ACCENT}; }}
    QPushButton:pressed {{ background: {ACCENT}; }}
    QProgressBar {{
        background: {BG_ELEVATED}; border: 1px solid {BORDER};
        border-radius: 4px; text-align: center; color: {FG}; font-size: 10px;
    }}
    QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}
    QScrollArea {{ background: {BG}; border: none; }}
    QScrollBar:vertical {{
        background: {BG}; width: 8px; margin: 0; border: none;
    }}
    QScrollBar::handle:vertical {{
        background: #555; border-radius: 4px; min-height: 24px;
    }}
    QScrollBar::handle:vertical:hover {{ background: #777; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
"""


def _open_url(url: str) -> None:
    """Open *url* in the system's default web browser."""
    QDesktopServices.openUrl(QUrl(url))


class _PackRow(QWidget):
    """A single row in the pack list showing one emoji style."""

    download_requested = pyqtSignal(str)    # style key
    redownload_requested = pyqtSignal(str)  # style key
    uninstall_requested = pyqtSignal(str)   # style key

    def __init__(self, style_key: str, parent=None) -> None:
        super().__init__(parent)
        self._style_key = style_key
        self._label = STYLE_INFO.get(style_key, style_key)

        self.setFixedHeight(44)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(6)

        # Name label
        name_lbl = QLabel(self._label, self)
        name_lbl.setStyleSheet(f"color: {FG}; font-size: 13px;")
        layout.addWidget(name_lbl)

        # Source / info button
        source_url = STYLE_SOURCE.get(style_key)
        if source_url:
            src_btn = QPushButton("Info", self)
            src_btn.setFixedWidth(55)
            src_btn.setToolTip(f"Open project page: {source_url}")
            src_btn.setStyleSheet(f"""
                QPushButton {{
                    background: {BG_ELEVATED}; color: {FG};
                    border: 1px solid {BORDER}; border-radius: 5px;
                    padding: 4px 6px; font-size: 11px;
                }}
                QPushButton:hover {{
                    background: {BG_HOVER}; border-color: {ACCENT};
                }}
            """)
            src_btn.clicked.connect(lambda: _open_url(source_url))
            layout.addWidget(src_btn)

        layout.addStretch()

        # Status badge
        self._status_lbl = QLabel(self)
        self._status_lbl.setStyleSheet(f"color: {FG_DIM}; font-size: 12px;")
        layout.addWidget(self._status_lbl)

        # Redownload button (shown only when cached)
        self._redl_btn = QPushButton("Re-dl", self)
        self._redl_btn.setFixedWidth(55)
        self._redl_btn.setToolTip("Re-download all images for this style")
        self._redl_btn.setStyleSheet(f"""
            QPushButton {{
                background: {BG_ELEVATED}; color: {FG};
                border: 1px solid {BORDER}; border-radius: 5px;
                padding: 4px 6px; font-size: 11px;
            }}
            QPushButton:hover {{
                background: {BG_HOVER}; border-color: {ACCENT};
            }}
        """)
        self._redl_btn.clicked.connect(lambda: self.redownload_requested.emit(self._style_key))
        layout.addWidget(self._redl_btn)

        # Primary action button (Download / Uninstall)
        self._btn = QPushButton(self)
        self._btn.setFixedWidth(90)
        self._btn.clicked.connect(self._on_click)
        layout.addWidget(self._btn)

        self._refresh()

    def _refresh(self) -> None:
        cached = style_has_cache(self._style_key)
        if cached:
            count = len(list((_CACHE_ROOT / self._style_key).iterdir()))
            self._status_lbl.setText(f"{count} images")
            self._status_lbl.show()
            self._redl_btn.show()
            self._btn.setText("Uninstall")
            self._btn.setStyleSheet(f"""
                QPushButton {{
                    background: #5a1d1d; color: {FG};
                    border: 1px solid #8a2a2a; border-radius: 5px;
                    padding: 4px 10px;
                }}
                QPushButton:hover {{
                    background: #7a2525; border-color: #c43a3a;
                }}
                QPushButton:pressed {{ background: #9a3030; }}
            """)
        else:
            self._status_lbl.hide()
            self._redl_btn.hide()
            self._btn.setText("Download")
            self._btn.setStyleSheet("")

    def _on_click(self) -> None:
        cached = style_has_cache(self._style_key)
        if cached:
            self.uninstall_requested.emit(self._style_key)
        else:
            self.download_requested.emit(self._style_key)

    def refresh(self) -> None:
        self._refresh()


# ---------------------------------------------------------------------------
# EmojiPackManager dialog
# ---------------------------------------------------------------------------

class EmojiPackManager(QDialog):
    """Modal dialog to download / uninstall emoji packs."""

    packs_changed = pyqtSignal()   # emitted after install/uninstall so the
                                   # caller can rebuild the style dropdown

    def __init__(self, image_loader, parent=None) -> None:
        super().__init__(parent)
        self._image_loader = image_loader

        self.setWindowTitle("Emoji Pack Manager")
        self.setFixedSize(460, 420)
        self.setStyleSheet(_STYLE)

        self._rows: dict[str, _PackRow] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        header = QLabel("Download or remove emoji image packs", self)
        header.setStyleSheet(f"color: {FG_DIM}; font-size: 12px; padding: 10px 14px 4px;")
        root.addWidget(header)

        # Scrollable pack list
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setStyleSheet(f"QScrollArea {{ background: {BG}; border: none; }}")

        scroll_content = QWidget(scroll)
        scroll_content.setStyleSheet(f"background: {BG};")
        self._list_lay = QVBoxLayout(scroll_content)
        self._list_lay.setContentsMargins(0, 0, 0, 0)
        self._list_lay.setSpacing(0)
        self._list_lay.addStretch()

        scroll.setWidget(scroll_content)
        root.addWidget(scroll)

        # Progress bar (hidden until a download starts)
        self._progress = QProgressBar(self)
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setTextVisible(True)
        self._progress.setFixedHeight(20)
        self._progress.hide()
        root.addWidget(self._progress)

        # Bottom button row
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(12, 8, 12, 12)
        btn_row.addStretch()
        close_btn = QPushButton("Close", self)
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

        # Populate the list
        self._populate()

        # Wire progress
        image_loader.progress_updated.connect(self._on_progress)

    def _populate(self) -> None:
        """Build rows for every non-system style."""
        # Clear existing rows
        for row in self._rows.values():
            self._list_lay.removeWidget(row)
            row.deleteLater()
        self._rows.clear()

        # Remove the trailing stretch, re-add after populating
        stretch_item = self._list_lay.takeAt(self._list_lay.count() - 1)

        for style_key in STYLE_INFO:
            if style_key == "system":
                continue
            row = _PackRow(style_key, self)
            row.download_requested.connect(self._on_download)
            row.redownload_requested.connect(self._on_redownload)
            row.uninstall_requested.connect(self._on_uninstall)
            self._rows[style_key] = row
            self._list_lay.addWidget(row)

            # Separator line
            sep = QWidget(self)
            sep.setFixedHeight(1)
            sep.setStyleSheet(f"background: {BORDER};")
            self._list_lay.addWidget(sep)

        self._list_lay.addStretch()

    def _on_download(self, style_key: str) -> None:
        import emoji_data as ed
        ed.ensure_loaded()
        self._image_loader.set_style(style_key)
        self._image_loader.prefetch([e.char for e in ed.get_all()])

    def _on_redownload(self, style_key: str) -> None:
        """Clear existing cache for *style_key* and immediately re-download."""
        style_dir = _CACHE_ROOT / style_key
        if style_dir.exists():
            import shutil
            shutil.rmtree(style_dir, ignore_errors=True)
        self._on_download(style_key)

    def _on_uninstall(self, style_key: str) -> None:
        # Remove the on-disk cache for this style
        style_dir = _CACHE_ROOT / style_key
        if style_dir.exists():
            import shutil
            shutil.rmtree(style_dir, ignore_errors=True)
        # If the active style was just removed, switch to system
        if self._image_loader.style == style_key:
            self._image_loader.set_style("system")
        else:
            # Just clear memory so stale pixmaps aren't served
            self._image_loader._mem.clear()
        # Refresh the row so it shows "Download" again
        if style_key in self._rows:
            self._rows[style_key].refresh()
        self.packs_changed.emit()

    def _on_progress(self, done: int, total: int) -> None:
        if total == 0:
            self._progress.hide()
            return
        pct = int(done / total * 100) if total else 0
        self._progress.setValue(pct)
        self._progress.setFormat(f"Downloading… {done} / {total}")
        self._progress.show()
        if done >= total:
            self._progress.setFormat("✓ Download complete")
            # Refresh all rows so newly-cached packs show "Uninstall"
            for row in self._rows.values():
                row.refresh()
            self.packs_changed.emit()
            QTimer.singleShot(2000, self._progress.hide)
