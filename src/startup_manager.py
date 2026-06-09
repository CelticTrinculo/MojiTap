"""Launch-on-login helpers for macOS (LaunchAgent) and Linux (XDG autostart)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

_APP_ID   = "com.mojitap"
_APP_NAME = "MojiTap"
_EXEC     = sys.executable
_SCRIPT   = str(Path(__file__).resolve().parent / "main.py")
_FROZEN   = bool(getattr(sys, "frozen", False))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def is_enabled() -> bool:
    return _entry_path().exists()


def enable() -> None:
    path = _entry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_entry_content())


def disable() -> None:
    path = _entry_path()
    if path.exists():
        path.unlink()


# ---------------------------------------------------------------------------
# Platform helpers
# ---------------------------------------------------------------------------

def _entry_path() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "LaunchAgents" / f"{_APP_ID}.plist"
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
        return Path(xdg) / "autostart" / "mojitap.desktop"


def _entry_content() -> str:
    if sys.platform == "darwin":
        return _macos_plist()
    return _linux_desktop()


def _exec_command() -> str:
    """Return the correct Exec command for source or bundled runs."""
    return _EXEC if _FROZEN else f"{_EXEC} {_SCRIPT}"


def _icon_path() -> str:
    if _FROZEN:
        return str(Path(_EXEC).resolve().parent / "app_icon.png")
    return str(Path(__file__).resolve().parent.parent / "assets" / "app_icon.png")


def _macos_plist() -> str:
    args = f"        <string>{_EXEC}</string>\n"
    if not _FROZEN:
        args += f"        <string>{_SCRIPT}</string>\n"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{_APP_ID}</string>
    <key>ProgramArguments</key>
    <array>
{args}    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
    <key>StandardOutPath</key>
    <string>{Path.home()}/.cache/mojitap/stdout.log</string>
    <key>StandardErrorPath</key>
    <string>{Path.home()}/.cache/mojitap/stderr.log</string>
</dict>
</plist>
"""


def _linux_desktop() -> str:
    return (
        "[Desktop Entry]\n"
        f"Name={_APP_NAME}\n"
        f"Exec={_exec_command()}\n"
        f"Icon={_icon_path()}\n"
        "Type=Application\n"
        "X-GNOME-Autostart-enabled=true\n"
        "Comment=Emoji picker with global hotkey\n"
    )
