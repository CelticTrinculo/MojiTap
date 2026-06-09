"""Main emoji picker window – Windows 11-style dark UI built with PyQt6."""
from __future__ import annotations

import sys
from typing import Optional

from PyQt6.QtCore import (
    QEasingCurve, QPoint, QPropertyAnimation, QRect, QRectF,
    QSize, Qt, QTimer, pyqtSignal,
)
from PyQt6.QtGui import (
    QColor, QFont, QFontInfo, QIcon, QPainter, QPainterPath,
    QPen, QPixmap, QRegion,
)
from PyQt6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QLineEdit,
    QMenu, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

import emoji_data as ed
from emoji_data import CATEGORY_META, RECENT_META, EmojiEntry

# ---------------------------------------------------------------------------
# Colour / geometry constants
# ---------------------------------------------------------------------------

BG          = "#202020"
BG_ELEVATED = "#2d2d2d"
BG_HOVER    = "#3a3a3a"
BG_PRESS    = "#464646"
FG          = "#ffffff"
FG_DIM      = "#9d9d9d"
ACCENT      = "#0078d4"
BORDER      = "#3d3d3d"

WIN_W       = 362
WIN_H       = 492
RADIUS      = 12   # window corner radius

TITLE_H     = 36
CAT_H       = 46
SEARCH_H    = 46
STATUS_H    = 30

CELL        = 42
COLS        = 8
PAD_H       = 7    # left/right padding inside the emoji canvas
SECTION_H   = 28
PAD_V       = 4

# Viewport width = WIN_W − scrollbar (~8 px) − (small margin)
CANVAS_W    = WIN_W - 2  # will be set precisely after scroll area is created


def _emoji_font(size: int) -> QFont:
    """Return a QFont suitable for rendering colour emoji.

    Must be called after a QApplication exists.
    """
    for family in ("Apple Color Emoji", "Noto Color Emoji",
                   "Segoe UI Emoji", "Twemoji Mozilla"):
        f = QFont(family)
        f.setPixelSize(size)
        info = QFontInfo(f)
        if info.family().lower() == family.lower():
            return f
    # Fallback – Qt picks an appropriate system emoji font
    f = QFont()
    f.setPixelSize(size)
    return f


# ---------------------------------------------------------------------------
# EmojiCanvas  –  custom-painted scrollable grid
# ---------------------------------------------------------------------------

class EmojiCanvas(QWidget):
    """
    High-performance custom-painted emoji grid.

    Sections are dicts ``{'title': str, 'emojis': list[EmojiEntry]}``.
    Only visible cells are painted.  All hit-testing is done with simple
    rect arithmetic (no per-cell widget overhead).
    """

    emoji_clicked = pyqtSignal(str)   # raw emoji char (possibly with skin tone)
    emoji_hovered = pyqtSignal(str)   # emoji name for status bar

    def __init__(
        self, parent: Optional[QWidget], image_loader,
        cell_size: int = 42, columns: int = 8,
    ) -> None:
        super().__init__(parent)
        self._image_loader = image_loader
        self._sections: list[dict] = []
        self._items:    list[tuple[str, object]] = []   # ('section'|'emoji', data)
        self._rects:    list[QRect]              = []
        self._hover:    int                      = -1
        self._skin_tone: str                     = ""

        # Grid settings
        self._cell_size   = cell_size
        self._columns     = columns

        # Fonts initialised here (after QApplication exists)
        self._efont = _emoji_font(max(cell_size - 4, 14))
        self._sfont = QFont()
        self._sfont.setPixelSize(12)
        self._sfont.setWeight(QFont.Weight.Medium)

        self.setMouseTracking(True)
        image_loader.image_ready.connect(self._on_image_ready)

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def set_sections(self, sections: list[dict], canvas_w: int = CANVAS_W) -> None:
        self._sections = sections
        self._build_layout(canvas_w)
        self.update()

    def set_skin_tone(self, modifier: str) -> None:
        self._skin_tone = modifier
        self.update()

    def apply_settings(self, cell_size: int, columns: int) -> None:
        """Update grid settings and rebuild layout."""
        changed = (
            cell_size != self._cell_size
            or columns != self._columns
        )
        self._cell_size   = cell_size
        self._columns     = columns
        if changed:
            self._efont = _emoji_font(max(cell_size - 4, 14))
            self._build_layout(self.width())
            self.update()

    def scroll_to_section(self, title: str) -> None:
        """Ask the parent QScrollArea to scroll so *title* is at the top."""
        p = self.parent()
        if p is None:
            return
        grand = p.parent()
        if grand is None:
            return
        scroll_area: QScrollArea = grand  # type: ignore[assignment]
        sb = scroll_area.verticalScrollBar()
        if sb is None:
            return
        for i, (itype, idata) in enumerate(self._items):
            if itype == "section" and idata == title:
                sb.setValue(self._rects[i].y())
                return

    def section_at_y(self, y: int) -> str:
        """Return the category name whose section header is above y."""
        last = ""
        for i, (itype, idata) in enumerate(self._items):
            if itype == "section":
                if self._rects[i].y() > y:
                    break
                last = str(idata)
        return last

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _build_layout(self, w: int) -> None:
        self._items = []
        self._rects = []

        cs   = self._cell_size
        cols = self._columns
        row_h = cs

        y = PAD_V
        for section in self._sections:
            title  = section.get("title", "")
            emojis = section.get("emojis", [])
            if not emojis:
                continue

            if title:
                self._items.append(("section", title))
                self._rects.append(QRect(PAD_H, y, w - 2 * PAD_H, SECTION_H))
                y += SECTION_H

            col = 0
            row_y = y
            for emoji in emojis:
                x = PAD_H + col * cs
                self._items.append(("emoji", emoji))
                self._rects.append(QRect(x, row_y, cs, row_h))
                col += 1
                if col >= cols:
                    col = 0
                    row_y += row_h

            if col > 0:
                row_y += row_h
            y = row_y + PAD_V

        total_h = max(y + PAD_V, 80)
        self.setFixedSize(w, total_h)

    # ------------------------------------------------------------------
    # Paint
    # ------------------------------------------------------------------

    def paintEvent(self, event) -> None:   # type: ignore[override]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        clip = event.rect()

        # Background (transparent, so the window BG shows through)
        p.fillRect(self.rect(), QColor(BG))

        hover_brush = QColor(BG_HOVER)
        press_brush = QColor(BG_PRESS)
        sec_pen     = QPen(QColor(FG_DIM))
        white_pen   = QPen(QColor(FG))

        cs  = self._cell_size

        for i, (itype, idata) in enumerate(self._items):
            r = self._rects[i]
            if r.bottom() < clip.top() or r.top() > clip.bottom():
                continue

            if itype == "section":
                p.setPen(sec_pen)
                p.setFont(self._sfont)
                p.drawText(r, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, str(idata))

            else:  # "emoji"
                entry: EmojiEntry = idata  # type: ignore[assignment]
                display_char = ed.apply_skin_tone(entry.char, self._skin_tone)

                # The emoji sits in the top cs×cs area of the rect
                emoji_r = QRect(r.x(), r.y(), cs, cs)

                # Hover highlight
                if i == self._hover:
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(hover_brush)
                    p.drawRoundedRect(emoji_r.adjusted(2, 2, -2, -2), 6, 6)

                # Custom image pack – scale to fill cell (with 2px margin)
                px = self._image_loader.get(display_char)
                if px and not px.isNull():
                    draw_size = cs - 4
                    target = QRect(
                        emoji_r.x() + (cs - draw_size) // 2,
                        emoji_r.y() + (cs - draw_size) // 2,
                        draw_size, draw_size,
                    )
                    p.drawPixmap(target, px)
                else:
                    # System font text rendering
                    p.setFont(self._efont)
                    p.setPen(white_pen)
                    p.drawText(emoji_r, Qt.AlignmentFlag.AlignCenter, display_char)

        p.end()

    # ------------------------------------------------------------------
    # Mouse
    # ------------------------------------------------------------------

    def mouseMoveEvent(self, event) -> None:   # type: ignore[override]
        pos = event.position().toPoint()
        idx = self._hit(pos)
        if idx != self._hover:
            old, self._hover = self._hover, idx
            if 0 <= old < len(self._rects):
                self.update(self._rects[old])
            if 0 <= idx < len(self._rects):
                self.update(self._rects[idx])

        if idx >= 0 and self._items[idx][0] == "emoji":
            self.emoji_hovered.emit(self._items[idx][1].name)  # type: ignore[union-attr]
        else:
            self.emoji_hovered.emit("")

    def mousePressEvent(self, event) -> None:   # type: ignore[override]
        # Accept the press so the release is also delivered to this widget,
        # preventing the button-release from leaking to windows underneath.
        if event.button() == Qt.MouseButton.LeftButton:
            event.accept()

    def mouseReleaseEvent(self, event) -> None:   # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            idx = self._hit(event.position().toPoint())
            if idx >= 0 and self._items[idx][0] == "emoji":
                entry: EmojiEntry = self._items[idx][1]   # type: ignore[assignment]
                char = ed.apply_skin_tone(entry.char, self._skin_tone)
                self.emoji_clicked.emit(char)

    def leaveEvent(self, event) -> None:   # type: ignore[override]
        if self._hover >= 0:
            old, self._hover = self._hover, -1
            if 0 <= old < len(self._rects):
                self.update(self._rects[old])
        self.emoji_hovered.emit("")

    def _hit(self, pos: QPoint) -> int:
        for i, r in enumerate(self._rects):
            if r.contains(pos):
                return i
        return -1

    def _on_image_ready(self, char: str, _px: QPixmap) -> None:
        for i, (itype, idata) in enumerate(self._items):
            if (
                itype == "emoji"
                and ed.apply_skin_tone(idata.char, self._skin_tone) == char  # type: ignore[union-attr]
            ):
                self.update(self._rects[i])


# ---------------------------------------------------------------------------
# CategoryBar
# ---------------------------------------------------------------------------

_CATEGORIES_ORDER = [
    ("recent", RECENT_META["icon"], "Recent"),
    *[
        (cat, CATEGORY_META[cat]["icon"], cat)
        for cat in sorted(CATEGORY_META, key=lambda c: CATEGORY_META[c]["order"])
    ],
]


class _CatButton(QWidget):
    clicked = pyqtSignal(str)   # category key

    def __init__(self, key: str, icon: str, tooltip: str, parent=None) -> None:
        super().__init__(parent)
        self.key     = key
        self.base_icon = icon
        self.icon    = icon
        self.tooltip = tooltip
        self.active  = False
        self.hovered = False
        self.setFixedSize(32, CAT_H)
        self.setToolTip(tooltip)
        self.setMouseTracking(True)
        self._font = _emoji_font(20)   # safe: QApplication already exists

    def setActive(self, v: bool) -> None:
        self.active = v
        self.update()

    def set_skin_tone(self, modifier: str) -> None:
        self.icon = ed.apply_skin_tone(self.base_icon, modifier)
        self.update()

    def paintEvent(self, _event) -> None:  # type: ignore[override]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        if self.hovered:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(BG_HOVER))
            p.drawRoundedRect(self.rect().adjusted(2, 2, -2, -2), 5, 5)

        p.setFont(self._font)
        p.setPen(QColor(FG))
        p.drawText(
            self.rect().adjusted(0, -2, 0, -4),
            Qt.AlignmentFlag.AlignCenter,
            self.icon,
        )

        # Active underline
        if self.active:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(ACCENT))
            p.drawRoundedRect(
                QRect(self.width() // 2 - 8, self.height() - 4, 16, 3), 2, 2
            )
        p.end()

    def enterEvent(self, _e) -> None:  # type: ignore[override]
        self.hovered = True
        self.update()

    def leaveEvent(self, _e) -> None:  # type: ignore[override]
        self.hovered = False
        self.update()

    def mousePressEvent(self, _e) -> None:  # type: ignore[override]
        self.clicked.emit(self.key)


_SKIN_TONE_CHOICES = [
    (0, "👍", "Default"),
    (1, "👍🏻", "Light"),
    (2, "👍🏼", "Medium-light"),
    (3, "👍🏽", "Medium"),
    (4, "👍🏾", "Medium-dark"),
    (5, "👍🏿", "Dark"),
]


class SkinToneButton(QWidget):
    tone_selected = pyqtSignal(int)

    def __init__(self, tone_index: int = 0, parent=None) -> None:
        super().__init__(parent)
        self._tone_index = tone_index if 0 <= tone_index < len(_SKIN_TONE_CHOICES) else 0
        self._hovered = False
        self._font = _emoji_font(18)
        self.setFixedSize(34, 34)
        self.setToolTip("Default skin tone")
        self.setMouseTracking(True)

    def set_tone_index(self, tone_index: int, *, emit_signal: bool = False) -> None:
        if not 0 <= tone_index < len(_SKIN_TONE_CHOICES):
            tone_index = 0
        changed = tone_index != self._tone_index
        self._tone_index = tone_index
        self.setToolTip(f"Skin tone: {_SKIN_TONE_CHOICES[tone_index][2]}")
        self.update()
        if changed and emit_signal:
            self.tone_selected.emit(tone_index)

    def paintEvent(self, _event) -> None:  # type: ignore[override]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        if self._hovered:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(BG_HOVER))
            p.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 6, 6)

        p.setFont(self._font)
        p.setPen(QColor(FG))
        p.drawText(
            self.rect().adjusted(0, -1, 0, -3),
            Qt.AlignmentFlag.AlignCenter,
            _SKIN_TONE_CHOICES[self._tone_index][1],
        )
        p.end()

    def enterEvent(self, _event) -> None:  # type: ignore[override]
        self._hovered = True
        self.update()

    def leaveEvent(self, _event) -> None:  # type: ignore[override]
        self._hovered = False
        self.update()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() != Qt.MouseButton.LeftButton:
            return

        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background: {BG_ELEVATED};
                color: {FG};
                border: 1px solid {BORDER};
                border-radius: 6px;
                padding: 4px;
            }}
            QMenu::item {{
                padding: 6px 18px;
                border-radius: 4px;
            }}
            QMenu::item:selected {{
                background: {ACCENT};
            }}
        """)

        for tone_index, icon, label in _SKIN_TONE_CHOICES:
            action = menu.addAction(f"{icon}  {label}")
            if action is not None:
                action.setCheckable(True)
                action.setChecked(tone_index == self._tone_index)
                action.triggered.connect(
                    lambda _checked=False, idx=tone_index: self.set_tone_index(idx, emit_signal=True)
                )

        menu.exec(self.mapToGlobal(self.rect().bottomLeft()))


class CategoryBar(QWidget):
    category_selected = pyqtSignal(str)   # category key
    skin_tone_selected = pyqtSignal(int)

    def __init__(self, tone_index: int = 0, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(CAT_H)
        self._buttons: dict[str, _CatButton] = {}
        self._tone_btn = SkinToneButton(tone_index, self)

        row = QHBoxLayout(self)
        row.setContentsMargins(4, 0, 4, 0)
        row.setSpacing(0)

        for key, icon, tooltip in _CATEGORIES_ORDER:
            btn = _CatButton(key, icon, tooltip, self)
            btn.clicked.connect(self.category_selected)
            self._buttons[key] = btn
            row.addWidget(btn)

        row.addStretch()
        self._tone_btn.tone_selected.connect(self.skin_tone_selected)
        row.addWidget(self._tone_btn)
        self.set_active("recent")

    def set_active(self, key: str) -> None:
        for k, btn in self._buttons.items():
            btn.setActive(k == key)

    def set_skin_tone(self, modifier: str) -> None:
        for btn in self._buttons.values():
            btn.set_skin_tone(modifier)
        try:
            tone_index = ed.SKIN_TONE_MODIFIERS.index(modifier)
        except ValueError:
            tone_index = 0
        self._tone_btn.set_tone_index(tone_index)


# ---------------------------------------------------------------------------
# SearchBar
# ---------------------------------------------------------------------------

class SearchBar(QWidget):
    text_changed = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(SEARCH_H)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)

        self._input = QLineEdit(self)
        self._input.setPlaceholderText("Search emojis")
        self._input.setClearButtonEnabled(True)
        self._input.setStyleSheet(f"""
            QLineEdit {{
                background: {BG_ELEVATED};
                border: 1px solid {BORDER};
                border-radius: 6px;
                color: {FG};
                padding: 4px 10px 4px 32px;
                font-size: 13px;
            }}
            QLineEdit:focus {{
                border-color: {ACCENT};
            }}
        """)
        self._input.textChanged.connect(self.text_changed)
        layout.addWidget(self._input)

        # Magnifier icon (drawn in paintEvent below, or just use text)
        self._icon_lbl = QLabel("🔍", self)
        self._icon_lbl.setStyleSheet(f"color: {FG_DIM}; font-size: 14px;")
        self._icon_lbl.setFixedSize(22, 22)
        self._icon_lbl.move(14, (SEARCH_H - 22) // 2)
        self._icon_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def clear(self) -> None:
        self._input.clear()

    def text(self) -> str:
        return self._input.text()

    def set_focus(self) -> None:
        self._input.setFocus()


# ---------------------------------------------------------------------------
# StatusBar
# ---------------------------------------------------------------------------

class StatusBar(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(STATUS_H)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)

        self._label = QLabel("", self)
        self._label.setStyleSheet(f"color: {FG_DIM}; font-size: 11px;")
        layout.addWidget(self._label)
        layout.addStretch()

    def set_text(self, text: str) -> None:
        self._label.setText(text)


# ---------------------------------------------------------------------------
# TitleBar  (drag handle + close button)
# ---------------------------------------------------------------------------

class TitleBar(QWidget):
    close_requested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(TITLE_H)
        self._drag_pos: Optional[QPoint] = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 0)
        layout.addStretch()

        close_btn = QLabel("✕", self)
        close_btn.setFixedSize(24, 24)
        close_btn.setAlignment(Qt.AlignmentFlag.AlignCenter)
        close_btn.setStyleSheet(f"""
            QLabel {{
                color: {FG_DIM};
                font-size: 12px;
                border-radius: 12px;
            }}
            QLabel:hover {{
                background: #c42b1c;
                color: white;
            }}
        """)
        close_btn.mousePressEvent = lambda ev: self.close_requested.emit()  # type: ignore[method-assign]
        layout.addWidget(close_btn)

    # Drag-to-move
    def mousePressEvent(self, event) -> None:   # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            win = self.window()
            if win is not None:
                self._drag_pos = event.globalPosition().toPoint() - win.frameGeometry().topLeft()

    def mouseMoveEvent(self, event) -> None:   # type: ignore[override]
        if self._drag_pos is not None and event.buttons() == Qt.MouseButton.LeftButton:
            win = self.window()
            if win is not None:
                win.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, _event) -> None:  # type: ignore[override]
        self._drag_pos = None


# ---------------------------------------------------------------------------
# PickerWindow
# ---------------------------------------------------------------------------

class PickerWindow(QWidget):
    def __init__(self, config, output_manager, image_loader) -> None:
        super().__init__(None)
        self.config         = config
        self.output_manager = output_manager
        self.image_loader   = image_loader

        self._search_active = False
        self._canvas_w      = 0  # set after _setup_window

        self._setup_window()
        self._setup_ui()
        self._load_full_grid()

    # ------------------------------------------------------------------
    # Window setup
    # ------------------------------------------------------------------

    def _setup_window(self) -> None:
        flags = Qt.WindowType.FramelessWindowHint
        if sys.platform == "linux":
            # Match plasma-emojier more closely on Plasma: use a normal
            # top-level window and let KWin decide initial placement.
            flags |= Qt.WindowType.Window
        else:
            flags |= (
                Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.Tool
            )
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # Compute initial size from config so the grid fits without gaps
        cols   = int(self.config.get("columns", 8))
        csize  = int(self.config.get("emoji_size", 42))
        init_w = cols * csize + 2 * PAD_H + 12
        init_w = max(init_w, 320)
        init_w = min(init_w, 900)
        self._canvas_w = init_w - 8   # viewport ≈ window minus scrollbar

        self.setMinimumSize(320, 400)
        self.resize(init_w, WIN_H)
        # Keep window non-user-resizable by fixing size after initial layout
        QTimer.singleShot(0, lambda: self.setFixedSize(self.size()))

    def _setup_ui(self) -> None:
        # Outer container gives us rounded-corner painting
        self._outer = QWidget(self)
        self._outer.setGeometry(0, 0, self.width(), self.height())
        self._outer.setStyleSheet(f"""
            QWidget {{
                background: {BG};
                border-radius: {RADIUS}px;
            }}
        """)

        root = QVBoxLayout(self._outer)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Title bar
        self._title_bar = TitleBar(self._outer)
        self._title_bar.close_requested.connect(self.hide)
        root.addWidget(self._title_bar)

        # Category bar
        self._cat_bar = CategoryBar(int(self.config.get("skin_tone", 0)), self._outer)
        self._cat_bar.category_selected.connect(self._on_category)
        self._cat_bar.skin_tone_selected.connect(self._on_skin_tone_selected)
        root.addWidget(self._cat_bar)

        # Separator
        sep = QWidget(self._outer)
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {BORDER};")
        root.addWidget(sep)

        # Search bar
        self._search = SearchBar(self._outer)
        self._search.text_changed.connect(self._on_search)
        root.addWidget(self._search)

        # Scroll area
        self._scroll = QScrollArea(self._outer)
        self._scroll.setWidgetResizable(False)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setStyleSheet(f"""
            QScrollArea {{
                background: {BG};
                border: none;
            }}
            QScrollBar:vertical {{
                background: {BG};
                width: 8px;
                margin: 0;
                border: none;
            }}
            QScrollBar::handle:vertical {{
                background: #555555;
                border-radius: 4px;
                min-height: 24px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: #777777;
            }}
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
        """)

        self._canvas = EmojiCanvas(
            None, self.image_loader,
            cell_size=int(self.config.get("emoji_size", 42)),
            columns=int(self.config.get("columns", 8)),
        )
        self._scroll.setWidget(self._canvas)
        root.addWidget(self._scroll)

        # Separator
        sep2 = QWidget(self._outer)
        sep2.setFixedHeight(1)
        sep2.setStyleSheet(f"background: {BORDER};")
        root.addWidget(sep2)

        # Status bar
        self._status = StatusBar(self._outer)
        root.addWidget(self._status)

        # Wire canvas signals
        self._canvas.emoji_clicked.connect(self._on_emoji_selected)
        self._canvas.emoji_hovered.connect(self._status.set_text)

        # Download progress
        self.image_loader.progress_updated.connect(self._on_download_progress)

        # Update active category on scroll
        sb = self._scroll.verticalScrollBar()
        if sb is not None:
            sb.valueChanged.connect(self._sync_cat_bar)

        # Skin tone
        modifier = self.config.skin_tone_modifier()
        self._canvas.set_skin_tone(modifier)
        self._cat_bar.set_skin_tone(modifier)

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def show_at_cursor(self) -> None:
        """Reveal the picker.

        On Linux/Plasma, mirror plasma-emojier: let KWin place the window on
        the active/mouse screen instead of forcing coordinates from the app.
        """
        self._search.clear()
        self._load_full_grid()

        if sys.platform != "linux":
            from PyQt6.QtGui import QCursor

            pos = QCursor.pos()
            app = QApplication.instance()
            screen_obj = app.screenAt(pos) or app.primaryScreen()
            screen = screen_obj.availableGeometry()

            ww = self.width()
            wh = self.height()
            # Centre is the only position now (Window Position was removed)
            x = screen.center().x() - ww // 2
            y = screen.center().y() - wh // 2

            x = max(screen.left(), min(x, screen.right()  - ww))
            y = max(screen.top(),  min(y, screen.bottom() - wh))
            self.move(x, y)

        self.show()
        self.raise_()
        self.activateWindow()
        self._search.set_focus()

    def refresh_skin_tone(self) -> None:
        modifier = self.config.skin_tone_modifier()
        self._canvas.set_skin_tone(modifier)
        self._cat_bar.set_skin_tone(modifier)

    def refresh_style(self) -> None:
        # Just rebuild the grid – don't re-download. The pack manager
        # handles all downloading/redownloading explicitly.
        self._load_full_grid(prefetch=False)

    def apply_grid_settings(self) -> None:
        """Re-read emoji_size, columns from config and resize window."""
        emoji_size = int(self.config.get("emoji_size", 42))
        columns    = int(self.config.get("columns", 8))

        # Resize window to fit the new grid dimensions
        needed_w = columns * emoji_size + 2 * PAD_H + 12
        needed_w = max(needed_w, 320)
        needed_w = min(needed_w, 900)
        self.setFixedSize(needed_w, self.height())

        self._canvas.apply_settings(
            cell_size=emoji_size,
            columns=columns,
        )
        # Update image loader size so future SVG renders use the right resolution
        self.image_loader.set_size(emoji_size - 6)

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _load_full_grid(self, prefetch: bool = True) -> None:
        """Build sections for all categories + recent and push to canvas.

        If *prefetch* is True (default), eagerly starts downloading all
        emoji images for the current style in background threads.
        """
        sections: list[dict] = []

        recent_chars = self.config.get("recent_emojis", [])
        if recent_chars:
            recent_entries = ed.make_recent_entries(recent_chars)
            sections.append({"title": "Recent", "emojis": recent_entries})

        for cat in ed.get_categories():
            sections.append({"title": cat, "emojis": ed.get_by_category(cat)})

        self._canvas.set_sections(sections, self._canvas_w)
        sb = self._scroll.verticalScrollBar()
        if sb is not None:
            sb.setValue(0)

        if prefetch:
            # Eagerly pre-fetch all emoji images in the background
            all_chars = [e.char for e in ed.get_all()]
            self.image_loader.prefetch(all_chars)

    def _on_category(self, key: str) -> None:
        if self._search_active:
            self._search.clear()
        if key == "recent":
            self._canvas.scroll_to_section("Recent")
        else:
            self._canvas.scroll_to_section(key)
        self._cat_bar.set_active(key)

    def _on_search(self, text: str) -> None:
        if not text.strip():
            if self._search_active:
                self._load_full_grid()
            return

        self._search_active = True
        results = ed.search(text)
        if results:
            sections = [{"title": "", "emojis": results}]
        else:
            sections = [{"title": "No results", "emojis": []}]
        self._canvas.set_sections(sections, self._canvas_w)

    def _on_skin_tone_selected(self, tone_index: int) -> None:
        self.config.set("skin_tone", tone_index)
        self.refresh_skin_tone()

    def _on_emoji_selected(self, char: str) -> None:
        self.config.add_recent_emoji(char)
        self.output_manager.output(char)
        if self.config.get("close_on_select", True):
            self.hide()

    def _on_download_progress(self, done: int, total: int) -> None:
        if total == 0:
            self._status.set_text("")
            return
        if done >= total:
            # Use a QTimer to clear the message after a short delay so the
            # user sees "Done" briefly, then the status bar goes back to empty.
            self._status.set_text("✓ All emoji images downloaded")
            QTimer.singleShot(2000, lambda: self._status.set_text(""))
        else:
            self._status.set_text(f"Downloading emoji images… {done}/{total}")

    def _sync_cat_bar(self, scroll_y: int) -> None:
        """Keep the category bar indicator in sync with the scroll position."""
        section = self._canvas.section_at_y(scroll_y)
        if section == "Recent":
            self._cat_bar.set_active("recent")
        elif section in CATEGORY_META:
            self._cat_bar.set_active(section)

    # ------------------------------------------------------------------
    # Window painting (rounded corners + drop shadow simulation)
    # ------------------------------------------------------------------

    def paintEvent(self, _event) -> None:   # type: ignore[override]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Subtle shadow effect (just a slightly transparent dark frame)
        for i in range(4, 0, -1):
            shadow_col = QColor(0, 0, 0, 15 * i)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(shadow_col)
            p.drawRoundedRect(
                self.rect().adjusted(-i, -i, i, i),
                RADIUS + i, RADIUS + i,
            )
        p.end()

    # ------------------------------------------------------------------
    # Focus-out → close
    # ------------------------------------------------------------------

    def event(self, event) -> bool:   # type: ignore[override]
        from PyQt6.QtCore import QEvent
        if event.type() == QEvent.Type.WindowDeactivate:
            # Defer the hide slightly so Qt/KWin can settle on the next
            # active window before we decide whether to dismiss.
            active = QApplication.activeWindow()
            if active is None or active is self:
                QTimer.singleShot(100, self._maybe_hide)
        return super().event(event)

    def _maybe_hide(self) -> None:
        active = QApplication.activeWindow()
        if active is None or (active is not self and not self.isAncestorOf(active)):
            self.hide()

    # ------------------------------------------------------------------
    # Canvas width resolution after first show
    # ------------------------------------------------------------------

    def resizeEvent(self, event) -> None:   # type: ignore[override]
        super().resizeEvent(event)
        # Keep the outer container filling the whole window
        # (guard: _outer may not exist yet during initial construction)
        if hasattr(self, '_outer'):
            self._outer.setGeometry(0, 0, self.width(), self.height())
        vp = self._scroll.viewport() if hasattr(self, '_scroll') else None
        if vp is None:
            return
        vp_w = vp.width()
        # Only accept the viewport width when it is large enough to fit all
        # columns – during Qt's initial layout pass the viewport temporarily
        # reports a very small (transient) width; accepting that value would
        # rebuild the canvas at ~2 columns and leave the grid broken.
        cols = int(self.config.get("columns", 8))
        csize = int(self.config.get("emoji_size", 42))
        if vp_w >= cols * csize and vp_w != self._canvas_w:
            self._canvas_w = vp_w
            # Rebuild grid so the canvas exactly fills the viewport.
            # This fixes a race where the initial layout has no scrollbar
            # (canvas is still short), giving a viewport that is too wide,
            # and later when the scrollbar appears the stale canvas overflows.
            if self._search_active:
                self._on_search(self._search.text())
            else:
                self._load_full_grid()
