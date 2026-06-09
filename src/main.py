"""
Entry point – system-tray daemon that hosts the emoji picker.

Usage:
    python src/main.py          # normal run
    python src/main.py --show   # open picker immediately on start
"""
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

# Ensure our src/ directory is on the path when invoked directly
sys.path.insert(0, str(Path(__file__).parent))

# On Linux/Wayland, running the picker through XWayland is currently more
# reliable for window placement and simulated paste behavior. Respect an
# explicit user setting if QT_QPA_PLATFORM is already defined.
if sys.platform == "linux" and not os.environ.get("QT_QPA_PLATFORM"):
    os.environ["QT_QPA_PLATFORM"] = "xcb"

from PyQt6.QtCore import QObject, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

import emoji_data
from config import Config
from emoji_image_loader import EmojiImageLoader
from hotkey_manager import HotkeyManager
from output_manager import OutputManager
from picker_window import PickerWindow
from settings_window import SettingsWindow


_ROOT_DIR = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
_LOG_DIR = Path.home() / ".cache" / "mojitap" / "logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)
_LOG_FILE = _LOG_DIR / "mojitap.log"

import logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler(str(_LOG_FILE), mode="a", encoding="utf-8"),
        logging.StreamHandler(sys.stderr),
    ],
)
logging.getLogger(__name__).info("=== MojiTap starting ===")


def _icon_path() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "assets" / "app_icon.png"  # type: ignore[attr-defined]
    return _ROOT_DIR / "assets" / "app_icon.png"


# ---------------------------------------------------------------------------
# Thread-safe hotkey → GUI bridge
# ---------------------------------------------------------------------------

class _Bridge(QObject):
    triggered = pyqtSignal()


class _PickerProxy:
    """Small indirection layer so settings always talk to the current picker."""

    def __init__(self) -> None:
        self._picker: PickerWindow | None = None

    @property
    def picker(self) -> PickerWindow | None:
        return self._picker

    def set_picker(self, picker: PickerWindow | None) -> None:
        self._picker = picker

    def refresh_skin_tone(self) -> None:
        if self._picker is not None:
            self._picker.refresh_skin_tone()

    def refresh_style(self) -> None:
        if self._picker is not None:
            self._picker.refresh_style()

    def apply_grid_settings(self) -> None:
        if self._picker is not None:
            self._picker.apply_grid_settings()


# ---------------------------------------------------------------------------
# Tray icon  (drawn programmatically so no external asset is needed)
# ---------------------------------------------------------------------------

def _make_tray_icon() -> QIcon:
    """Return the application icon, falling back to a generated badge."""
    icon_path = _icon_path()
    if icon_path.exists():
        icon = QIcon(str(icon_path))
        if not icon.isNull():
            return icon

    """Create a simple emoji-ish tray icon at 32 × 32."""
    px = QPixmap(32, 32)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

    # Background circle
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#0078d4"))
    p.drawEllipse(1, 1, 30, 30)

    # Smiley  😊  as text
    from picker_window import _emoji_font
    f = _emoji_font(28)
    p.setFont(f)
    p.setPen(QColor("white"))
    p.drawText(px.rect(), Qt.AlignmentFlag.AlignCenter, "😊")
    p.end()
    return QIcon(px)


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

def main() -> None:
    # High-DPI
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("MojiTap")
    app.setWindowIcon(_make_tray_icon())

    # ── Core objects ────────────────────────────────────────────────────
    config       = Config()
    output       = OutputManager(config)
    hotkey_mgr   = HotkeyManager(config)
    default_size = config.get("emoji_size", 42)
    image_loader = EmojiImageLoader(
        style=config.get("emoji_style", "system"),
        size=default_size - 6,  # image size = cell size minus padding
    )

    # Pre-load emoji data in background so first open is instant
    threading.Thread(target=emoji_data.ensure_loaded, daemon=True).start()

    # ── Windows ──────────────────────────────────────────────────────────
    picker_proxy  = _PickerProxy()
    settings_win: list[SettingsWindow] = []   # box so inner funcs can reassign

    def _make_picker() -> PickerWindow:
        picker = PickerWindow(config, output, image_loader)
        picker_proxy.set_picker(picker)
        return picker

    if sys.platform != "linux":
        _make_picker()

    # ── Hotkey bridge (thread-safe) ─────────────────────────────────────
    bridge = _Bridge()

    def _show_picker() -> None:
        output.record_active_window()
        if sys.platform == "linux":
            old_picker = picker_proxy.picker
            if old_picker is not None:
                old_picker.close()
                old_picker.deleteLater()
                picker_proxy.set_picker(None)
            picker = _make_picker()
        else:
            picker = picker_proxy.picker or _make_picker()
        picker.show_at_cursor()

    bridge.triggered.connect(_show_picker)
    hotkey_mgr.set_callback(bridge.triggered.emit)
    # Defer hotkey registration until the Qt/NSRunLoop is running.
    # NSEvent.addGlobalMonitorForEventsMatchingMask MUST be called from the
    # main thread with an active RunLoop; a QTimer fires in the first event loop tick.
    QTimer.singleShot(0, hotkey_mgr.start)

    # ── Settings ─────────────────────────────────────────────────────────
    def _open_settings() -> None:
        if settings_win and settings_win[0].isVisible():
            settings_win[0].activateWindow()
            return
        win = SettingsWindow(config, hotkey_mgr, image_loader, picker_proxy)
        if settings_win:
            settings_win[0] = win
        else:
            settings_win.append(win)
        win.show()

    # ── System tray ──────────────────────────────────────────────────────
    if not QSystemTrayIcon.isSystemTrayAvailable():
        print("[warn] No system tray available – picker will only open via hotkey.")

    tray = QSystemTrayIcon(app)
    tray.setIcon(_make_tray_icon())
    tray.setToolTip(
        f"MojiTap  ({HotkeyManager.to_display(config.get('hotkey', '<ctrl>+<alt>+e'))})"
    )

    menu = QMenu()
    menu.setStyleSheet("""
        QMenu {
            background: #2d2d2d;
            color: #ffffff;
            border: 1px solid #3d3d3d;
            border-radius: 6px;
            padding: 4px;
        }
        QMenu::item { padding: 6px 20px; border-radius: 4px; }
        QMenu::item:selected { background: #0078d4; }
        QMenu::separator { height: 1px; background: #3d3d3d; margin: 4px 0; }
    """)

    act_open = QAction("Open MojiTap", menu)
    menu.addAction(act_open)
    act_settings = QAction("Settings…", menu)
    menu.addAction(act_settings)
    menu.addSeparator()
    act_quit = QAction("Quit", menu)
    menu.addAction(act_quit)

    act_open.triggered.connect(_show_picker)
    act_settings.triggered.connect(_open_settings)
    act_quit.triggered.connect(app.quit)

    tray.setContextMenu(menu)
    tray.activated.connect(
        lambda reason: _show_picker()
        if reason == QSystemTrayIcon.ActivationReason.Trigger
        else None
    )
    tray.show()

    # ── Optional: open immediately on --show ────────────────────────────
    if "--show" in sys.argv:
        QTimer.singleShot(200, _show_picker)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
