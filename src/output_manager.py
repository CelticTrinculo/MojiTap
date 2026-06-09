"""Platform-aware emoji output: type into focused window and/or clipboard."""
from __future__ import annotations

import os
import sys
import threading
import time
from typing import Optional

import pyperclip


class OutputManager:
    def __init__(self, config) -> None:
        self.config = config
        self._platform = sys.platform
        self._is_wayland = (
            self._platform == "linux"
            and (
                bool(os.environ.get("WAYLAND_DISPLAY"))
                or os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
            )
        )
        self._prev_window_id: Optional[str] = None
        self._prev_app_name: Optional[str] = None

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def record_active_window(self) -> None:
        """Call this immediately BEFORE showing the picker window."""
        if self._platform == "darwin":
            try:
                from AppKit import NSWorkspace  # type: ignore[import]
                app = NSWorkspace.sharedWorkspace().frontmostApplication()
                self._prev_app_name = app.localizedName() if app else None
            except Exception:
                self._prev_app_name = None
        elif self._platform == "linux" and not self._is_wayland:
            import subprocess
            try:
                r = subprocess.run(
                    ["xdotool", "getactivewindow"],
                    capture_output=True, text=True, timeout=1,
                )
                self._prev_window_id = r.stdout.strip() or None
            except Exception:
                self._prev_window_id = None

    def output(self, emoji_char: str) -> None:
        mode = self.config.get("output_mode", "type")
        if mode == "clipboard":
            self._to_clipboard(emoji_char)
        elif mode == "both":
            self._to_clipboard(emoji_char)
            self._schedule_type(emoji_char)
        elif mode == "type":
            self._schedule_type(emoji_char)
        # mode == "none"  →  intentional no-op

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _to_clipboard(self, char: str) -> None:
        if self._is_wayland:
            try:
                import subprocess
                subprocess.Popen(
                    ["wl-copy", "--", char],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    close_fds=True,
                )
                return
            except Exception:
                pass
        try:
            pyperclip.copy(char)
        except Exception:
            pass

    def _schedule_type(self, char: str) -> None:
        """Fire the typing logic in a daemon thread after a short delay so
        the original window has time to regain focus."""
        wid = self._prev_window_id
        # Wayland needs more time for the previous window to regain focus
        delay = 0.35 if self._is_wayland else 0.15
        threading.Thread(
            target=self._do_type,
            args=(char, delay, wid),
            daemon=True,
        ).start()

    def _do_type(self, char: str, delay: float, window_id: Optional[str]) -> None:
        time.sleep(delay)
        if self._platform == "darwin":
            self._type_macos(char)
        elif self._is_wayland:
            self._type_wayland(char)
        else:
            self._type_x11(char, window_id)

    def _type_x11(self, char: str, window_id: Optional[str]) -> None:
        import subprocess
        try:
            cmd = ["xdotool", "type", "--clearmodifiers", "--delay", "0"]
            if window_id:
                cmd += ["--window", window_id]
            cmd.append(char)
            subprocess.run(cmd, check=True, capture_output=True, timeout=4)
        except Exception:
            self._to_clipboard(char)

    def _type_wayland(self, char: str) -> None:
        import subprocess
        # 1. Copy emoji to clipboard via wl-copy
        copied = False
        try:
            subprocess.Popen(
                ["wl-copy", "--", char],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )
            time.sleep(0.05)  # let wl-copy register the selection
            copied = True
        except Exception:
            try:
                pyperclip.copy(char)
                copied = True
            except Exception:
                pass

        if not copied:
            return

        # 2. Paste via Ctrl+V using xdotool (routes through XWayland on KDE Plasma 6)
        try:
            subprocess.run(
                ["xdotool", "key", "--clearmodifiers", "ctrl+v"],
                capture_output=True,
                timeout=3,
            )
        except Exception:
            pass  # emoji is already in clipboard as fallback

    def _type_macos(self, char: str) -> None:
        """macOS: copy emoji to clipboard then paste via osascript Cmd+V.

        pynput.keyboard.Controller.type() calls TSMGetInputSourceProperty from
        a background thread, which crashes on macOS 15 (dispatch_assert_queue).
        osascript runs out-of-process, so no thread-safety issue.

        We explicitly activate the app that was frontmost before the picker
        opened, so Cmd+V lands in the right text field.
        """
        import subprocess
        self._to_clipboard(char)
        app = self._prev_app_name
        if app:
            script = (
                f'tell application "{app}" to activate\n'
                f'delay 0.05\n'
                f'tell application "System Events" to keystroke "v" '
                f'using {{command down}}'
            )
        else:
            script = (
                'tell application "System Events" to keystroke "v" '
                'using {command down}'
            )
        try:
            subprocess.run(["osascript", "-e", script], capture_output=True, timeout=4)
        except Exception:
            pass  # clipboard already has the emoji as fallback
