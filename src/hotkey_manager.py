"""Global hotkey listener.

- macOS  : NSEvent.addGlobalMonitorForEventsMatchingMask (main-thread safe on macOS 15+)
- Linux  : pynput.keyboard.GlobalHotKeys (background thread, fine on X11/Wayland)

pynput crashes on macOS 15 (Sequoia) because its Carbon keyboard listener calls
TSMGetInputSourceProperty from a background thread, which macOS now enforces must
run on the main dispatch queue (dispatch_assert_queue crash / SIGTRAP).
"""
from __future__ import annotations

import sys
from typing import Callable, Optional

# ---------------------------------------------------------------------------
# NSEvent modifier-flag constants  (NSEventModifierFlags values)
# ---------------------------------------------------------------------------
_NS_SHIFT = 1 << 17   # NSEventModifierFlagShift    = 0x020000
_NS_CTRL  = 1 << 18   # NSEventModifierFlagControl  = 0x040000
_NS_ALT   = 1 << 19   # NSEventModifierFlagOption   = 0x080000
_NS_CMD   = 1 << 20   # NSEventModifierFlagCommand  = 0x100000
_NS_ALL   = _NS_SHIFT | _NS_CTRL | _NS_ALT | _NS_CMD

_PYNPUT_TO_NS: dict[str, int] = {
    "<ctrl>":  _NS_CTRL,
    "<alt>":   _NS_ALT,
    "<shift>": _NS_SHIFT,
    "<cmd>":   _NS_CMD,
    "<super>": _NS_CMD,
    "<win>":   _NS_CMD,
}


def _parse_hotkey(hotkey: str) -> tuple[int, str]:
    """Parse pynput-format string → (NSEvent modifier flags, char).

    ``'<ctrl>+<alt>+e'``  →  ``(_NS_CTRL | _NS_ALT, 'e')``
    """
    flags = 0
    char  = ""
    for part in hotkey.lower().split("+"):
        part = part.strip()
        if part in _PYNPUT_TO_NS:
            flags |= _PYNPUT_TO_NS[part]
        elif not (part.startswith("<") and part.endswith(">")):
            char = part
    return flags, char


class HotkeyManager:
    def __init__(self, config) -> None:
        self.config = config
        self._handle = None   # NSEvent monitor handle OR pynput listener
        self._callback: Optional[Callable[[], None]] = None

    def set_callback(self, cb: Callable[[], None]) -> None:
        self._callback = cb

    def start(self) -> None:
        """Register the hotkey.  MUST be called from the main thread."""
        self.stop()
        if sys.platform == "darwin":
            self._start_macos()
        else:
            self._start_pynput()

    def stop(self) -> None:
        if sys.platform == "darwin":
            self._stop_macos()
        else:
            self._stop_pynput()

    def restart(self) -> None:
        """Re-read config and restart with the potentially updated hotkey."""
        self.start()

    def _fired(self) -> None:
        if self._callback:
            self._callback()

    # ------------------------------------------------------------------
    # macOS – NSEvent global monitor (runs on main thread, no SIGTRAP)
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Accessibility helpers (macOS)
    # ------------------------------------------------------------------

    @staticmethod
    def accessibility_ok() -> bool:
        """Return True if this process has Accessibility permission.

        Uses ctypes so no extra package is needed beyond what is already
        loaded.  Global keyboard monitors silently receive no events when
        Accessibility is not granted.
        """
        try:
            import ctypes, ctypes.util
            lib = ctypes.cdll.LoadLibrary(
                ctypes.util.find_library("ApplicationServices") or
                "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
            )
            lib.AXIsProcessTrusted.restype = ctypes.c_bool
            return bool(lib.AXIsProcessTrusted())
        except Exception:
            return True   # assume OK if we cannot check

    @staticmethod
    def open_accessibility_settings() -> None:
        """Open System Settings → Privacy & Security → Accessibility."""
        import subprocess
        subprocess.Popen([
            "open",
            "x-apple.systempreferences:"
            "com.apple.preference.security?Privacy_Accessibility",
        ])

    def _start_macos(self) -> None:
        hotkey = self.config.get("hotkey", "<ctrl>+<alt>+e")
        if not self.accessibility_ok():
            print(
                "[hotkey] Accessibility permission is NOT granted.\n"
                "         The global hotkey will not work until you enable this app\n"
                "         in System Settings → Privacy & Security → Accessibility.\n"
                "         Opening System Settings now..."
            )
            self.open_accessibility_settings()
        try:
            from AppKit import NSEvent  # type: ignore[import]
            NSKeyDownMask = 1 << 10

            target_flags, target_char = _parse_hotkey(hotkey)
            if not target_char:
                print(f"[hotkey] Could not parse character from '{hotkey}'")
                return

            def _handler(event):
                flags = int(event.modifierFlags()) & _NS_ALL
                if flags != target_flags:
                    return
                chars = event.charactersIgnoringModifiers() or ""
                if chars.lower() == target_char.lower():
                    self._fired()

            self._handle = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
                NSKeyDownMask, _handler
            )
            if self._handle is None:
                print(
                    "[hotkey] NSEvent monitor returned None – "
                    "grant Accessibility access in System Settings > Privacy & Security."
                )
        except Exception as exc:
            print(f"[hotkey] macOS NSEvent monitor failed: {exc}")

    def _stop_macos(self) -> None:
        if self._handle is not None:
            try:
                from AppKit import NSEvent  # type: ignore[import]
                NSEvent.removeMonitor_(self._handle)
            except Exception:
                pass
            self._handle = None

    # ------------------------------------------------------------------
    # Linux – pynput (background thread; safe outside macOS)
    # ------------------------------------------------------------------

    def _start_pynput(self) -> None:
        hotkey = self.config.get("hotkey", "<ctrl>+<alt>+e")
        try:
            from pynput import keyboard
            self._handle = keyboard.GlobalHotKeys({hotkey: self._fired})
            self._handle.daemon = True
            self._handle.start()
        except Exception as exc:
            print(f"[hotkey] pynput failed for '{hotkey}': {exc}")

    def _stop_pynput(self) -> None:
        if self._handle is not None:
            try:
                self._handle.stop()
            except Exception:
                pass
            self._handle = None

    # ------------------------------------------------------------------
    # Display helpers
    # ------------------------------------------------------------------

    @staticmethod
    def to_display(hotkey: str) -> str:
        """``'<ctrl>+<alt>+e'``  →  ``'Ctrl + Alt + E'``"""
        labels = {
            "<ctrl>": "Ctrl", "<alt>": "Alt", "<shift>": "Shift",
            "<cmd>": "Cmd", "<super>": "Super", "<win>": "Win",
            "<space>": "Space", "<tab>": "Tab", "<enter>": "Enter",
        }
        parts = hotkey.lower().split("+")
        return " + ".join(labels.get(p.strip(), p.strip().upper()) for p in parts)

    @staticmethod
    def from_display(display: str) -> str:
        """Rough inverse of *to_display*, used by the settings dialog."""
        labels = {
            "Ctrl": "<ctrl>", "Alt": "<alt>", "Shift": "<shift>",
            "Cmd": "<cmd>", "Super": "<super>", "Win": "<win>",
            "Space": "<space>", "Tab": "<tab>", "Enter": "<enter>",
        }
        return "+".join(labels.get(p.strip(), p.strip().lower()) for p in display.split("+"))
