"""Configuration management – stored at ~/.config/mojitap/config.json."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, List

CONFIG_DIR  = Path.home() / ".config" / "mojitap"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_CONFIG: dict[str, Any] = {
    # Hotkey (pynput format)
    "hotkey": "<ctrl>+<alt>+e",
    # Output behaviour: "type" | "clipboard" | "both" | "none"
    # Default to "clipboard" on Linux: auto-typing via uinput/xdotool is
    # unreliable on KDE Plasma 6 / Wayland.  Clipboard always works.
    "output_mode": "clipboard" if sys.platform == "linux" else "type",
    # Visual emoji pack: "system" | "twemoji" | "gemoji" | "openmoji" | "noto" | "joypixels" | "emojitwo" | "fluent" | "tossface"
    "emoji_style": "system",
    # Launch with OS
    "start_on_boot": False,
    # MRU list (list of emoji chars)
    "recent_emojis": [],
    "max_recent": 30,
    # Fitzpatrick skin-tone modifier: 0 = default/yellow, 1–5 = light…dark
    "skin_tone": 0,
    # Grid geometry
    # Grid cell size in pixels (emoji font size = emoji_size - 14)
    "emoji_size": 42,
    "columns": 8,
    # UX tweaks
    "show_tooltip": True,
    "close_on_select": True,
    # Manual window placement for non-Linux platforms.
    # On Linux/Plasma we let the window manager place the picker, matching
    # plasma-emojier's same-monitor behavior.
    "window_position": "center",
}


class Config:
    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self.load()

    # ---------------------------------------------------------------- I/O

    def load(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    loaded: dict = json.load(f)
                self._data = {**DEFAULT_CONFIG, **loaded}
            except (json.JSONDecodeError, OSError):
                self._data = DEFAULT_CONFIG.copy()
        else:
            self._data = DEFAULT_CONFIG.copy()
            self.save()

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)

    # ---------------------------------------------------------------- access

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value
        self.save()

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.set(key, value)

    # ---------------------------------------------------------------- helpers

    def add_recent_emoji(self, char: str) -> None:
        recent: List[str] = list(self._data.get("recent_emojis", []))
        if char in recent:
            recent.remove(char)
        recent.insert(0, char)
        max_r: int = int(self._data.get("max_recent", 30))
        self._data["recent_emojis"] = recent[:max_r]
        self.save()

    def skin_tone_modifier(self) -> str:
        """Return the Unicode skin-tone modifier for the configured tone (or '')."""
        tone = int(self._data.get("skin_tone", 0))
        modifiers = ["", "\U0001f3fb", "\U0001f3fc", "\U0001f3fd", "\U0001f3fe", "\U0001f3ff"]
        return modifiers[tone] if 0 <= tone < len(modifiers) else ""
