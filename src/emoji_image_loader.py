"""Async emoji image downloader/cache for multiple emoji packs.

Supported styles: ``system`` | ``twemoji`` | ``openmoji`` | ``noto``
                   | ``joypixels`` | ``emojitwo`` | ``fluent``
                   | ``tossface`` | ``gemoji``
"""
from __future__ import annotations

import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, Optional


logger = logging.getLogger(__name__)

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtGui import QPixmap

if TYPE_CHECKING:
    import requests

_CACHE_ROOT = Path.home() / ".cache" / "mojitap"

# URL templates.  Substitution keys:
#   {cp}   – lowercase hex codepoints joined by '-'   e.g. "1f600" or "1f1e6-1f1e8"
#   {CP}   – uppercase version                        e.g. "1F600"
#   {cp_}  – lowercase, joined by '_'                 e.g. "1f600" or "1f1e6_1f1e8"
#   {CP_}  – uppercase, joined by '_'                 e.g. "1F600" or "1F1E6_1F1E8"
_CDN: dict[str, str] = {
    "twemoji":   "https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/72x72/{cp}.png",
    "gemoji":    "https://github.githubassets.com/images/icons/emoji/unicode/{cp}.png",
    "openmoji":  "https://cdn.jsdelivr.net/npm/openmoji@17.0.0/color/svg/{CP}.svg",
    "noto":      "https://raw.githubusercontent.com/googlefonts/noto-emoji/main/png/72/emoji_u{cp_}.png",
    "joypixels": "https://cdn.jsdelivr.net/gh/joypixels/emoji-assets@latest/png/64/{cp}.png",
    "emojitwo":  "https://cdn.jsdelivr.net/gh/EmojiTwo/emojitwo@master/png/{cp}.png",
    "tossface":  "https://raw.githubusercontent.com/toss/tossface/main/dist/svg/u{CP_}.svg",
    # Fluent Emoji uses a name-based mapping via _fluent_url(); no template here.
}

# All supported styles with their display labels.
# "system" is always available (uses OS font) and has no CDN entry.
STYLE_INFO: dict[str, str] = {
    "system":    "System (OS emoji font)",
    "twemoji":   "Twemoji  (Twitter / X)",
    "noto":      "Noto Color Emoji  (Google)",
    "joypixels": "JoyPixels  (formerly EmojiOne)",
    "fluent":    "Fluent Emoji  (Microsoft)",
    "openmoji":  "OpenMoji  (open-source)",
    "emojitwo":  "EmojiTwo  (Twemoji fork)",
    "tossface":  "Tossface  (Toss, 🇰🇷)",
    "gemoji":    "GitHub Emoji  (gemoji)",
}

# Source / project-home URL for each downloadable style.
STYLE_SOURCE: dict[str, str] = {
    "twemoji":   "https://github.com/twitter/twemoji",
    "noto":      "https://github.com/googlefonts/noto-emoji",
    "joypixels": "https://www.joypixels.com/",
    "fluent":    "https://github.com/microsoft/fluentui-emoji",
    "openmoji":  "https://github.com/hfg-gmuend/openmoji",
    "emojitwo":  "https://github.com/EmojiTwo/emojitwo",
    "tossface":  "https://github.com/toss/tossface",
    "gemoji":    "https://github.com/github/gemoji",
}

# Styles that use SVG format (need special rendering via QSvgRenderer)
_SVG_STYLES = frozenset({"openmoji", "tossface"})

# Max concurrent downloads – limits connection pressure on CDNs
_MAX_WORKERS = 6

# Max concurrent downloads – limits connection pressure on CDNs
_MAX_WORKERS = 6

# Fluent Emoji – mapping cache path & repo details
_FLUENT_MAPPING_CACHE = _CACHE_ROOT / "fluent_mapping.json"
_FLUENT_REPO  = "microsoft/fluentui-emoji"
_FLUENT_BRANCH = "main"
_FLUENT_BASE  = f"https://raw.githubusercontent.com/{_FLUENT_REPO}/{_FLUENT_BRANCH}"


def _codepoints(char: str) -> list[str]:
    """Return hex codepoints, stripping variation selectors (U+FE0E/FE0F)."""
    return [f"{ord(c):04x}" for c in char if ord(c) not in (0xFE0E, 0xFE0F)]


def _char_to_cp_key(char: str) -> str:
    """Normalise a character to a mapping lookup key (space-separated codepoints)."""
    cps = _codepoints(char)
    return " ".join(cps) if cps else ""


def _cdn_url(style: str, char: str) -> Optional[str]:
    template = _CDN.get(style)
    if not template:
        return None
    cps = _codepoints(char)
    if not cps:
        return None
    return template.format(
        cp="-".join(cps),
        CP="-".join(c.upper() for c in cps),
        cp_="_".join(cps),
        CP_="_".join(c.upper() for c in cps),
    )


def _fluent_url(char: str, mapping: dict[str, dict[str, str]]) -> Optional[str]:
    """Build a fluentui-emoji raw GitHub URL for *char* using *mapping*.

    *mapping* is ``{codepoint_key: {"folder": …, "base": …}}`` built by
    :meth:`EmojiImageLoader._build_fluent_mapping`.
    """
    key = _char_to_cp_key(char)
    entry = mapping.get(key)
    if not entry:
        return None
    folder = entry["folder"]
    base   = entry["base"]
    # Use 3D style (the most distinctive Fluent style)
    return f"{_FLUENT_BASE}/assets/{folder}/3D/{base}_3d.png"


def _render_svg(data: bytes, size: int) -> Optional[QPixmap]:
    """Render SVG *data* to a *size*x*size* pixmap via QSvgRenderer."""
    try:
        from PyQt6.QtSvg import QSvgRenderer
        from PyQt6.QtGui import QImage, QPainter
    except ImportError:
        return None
    renderer = QSvgRenderer(data)
    if not renderer.isValid():
        return None
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(0)  # transparent background
    painter = QPainter(img)
    renderer.render(painter)
    painter.end()
    return QPixmap.fromImage(img)


# ---------------------------------------------------------------------------
# Public helpers – cache introspection
# ---------------------------------------------------------------------------

def style_has_cache(style: str) -> bool:
    """Return True if *style* has at least one cached file on disk."""
    if style == "system":
        return True  # system is always available
    d = _CACHE_ROOT / style
    return d.is_dir() and any(d.iterdir())


def cached_styles() -> list[str]:
    """Return sorted list of styles that have cached data on disk (plus system)."""
    result = ["system"]
    for style in STYLE_INFO:
        if style != "system" and style_has_cache(style):
            result.append(style)
    return result


class EmojiImageLoader(QObject):
    """Thread-safe loader that emits *image_ready* when a download completes.

    Optimisations
    -------------
    * ``requests.Session`` for HTTP connection pooling (keep-alive).
    * ``ThreadPoolExecutor`` to limit concurrent downloads to ``_MAX_WORKERS``.
    * Eager prefetch – call ``prefetch(all_emoji_chars)`` to start downloading
      all emojis immediately in the background when a style is selected.
    """

    image_ready = pyqtSignal(str, QPixmap)   # (emoji_char, pixmap)
    progress_updated = pyqtSignal(int, int)  # (completed, total)

    def __init__(self, style: str = "system", size: int = 36) -> None:
        super().__init__()
        # If the requested style has no cached files on disk, fall back to
        # system so the user sees emojis immediately instead of a blank grid.
        # They can still download the pack later via the pack manager.
        if style != "system" and not style_has_cache(style):
            logger.info(
                "No disk cache for '%s' at startup – using 'system' instead", style
            )
            style = "system"
        self.style = style
        logger.info("Initialised EmojiImageLoader style=%s size=%d", style, size)
        self.size  = size
        self._mem:     dict[str, QPixmap] = {}
        self._pending: set[str]           = set()
        self._session: requests.Session | None = None  # type: ignore[name-defined]
        self._executor = ThreadPoolExecutor(
            max_workers=_MAX_WORKERS,
            thread_name_prefix="emoji-dl",
        )
        self._progress_done  = 0
        self._progress_total = 0
        # Not-found tracking – chars that returned 404 for the current style
        # so we don't keep retrying them on every open.
        self._not_found: set[str] = set()
        self._load_not_found()
        # Fluent Emoji mapping: {codepoint_key: {"folder": …, "base": …}}
        self._fluent_mapping: dict[str, dict[str, str]] | None = None
        if style == "fluent":
            self._ensure_fluent_mapping()
        _CACHE_ROOT.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def set_style(self, style: str, all_chars: list[str] | None = None) -> None:
        """Switch emoji pack, clear memory cache, and eagerly pre-fetch.

        Pass *all_chars* (all emoji codepoints) so that downloading starts
        immediately in background batches.
        """
        if self.style != style:
            logger.info("Switching style %s -> %s", self.style, style)
            self.style = style
            self._mem.clear()
            self._pending.clear()
            self._progress_done  = 0
            self._progress_total = 0
            self._load_not_found()  # load 404 tracking for the new style
            if style == "fluent":
                self._ensure_fluent_mapping()
        if style != "system" and all_chars:
            logger.info("Pre-fetching %d emojis for style '%s'", len(all_chars), style)
            self.prefetch(all_chars)

    def set_size(self, size: int) -> None:
        """Update the render size for future downloads (e.g. when emoji_size changes).

        The memory cache is cleared so that SVGs (which are rendered at
        ``self.size``) will be re-rendered at the new size.  PNG images
        downloaded from CDNs are simply scaled at paint time regardless.
        """
        if self.size != size:
            self.size = size
            self._mem.clear()

    def get(self, char: str) -> Optional[QPixmap]:
        """Return a cached pixmap synchronously, or None (starts async load)."""
        if self.style == "system":
            return None  # rendered as text by the canvas painter

        if char in self._mem:
            return self._mem[char]

        disk = self._disk_path(char)
        if disk and disk.exists():
            px = self._load_from_disk(disk)
            if px:
                self._mem[char] = px
                return px

        # Don't retry emojis that are known to not exist in this style
        if char in self._not_found:
            return None

        # Kick off background download (bounded by ThreadPoolExecutor)
        if char not in self._pending:
            self._pending.add(char)
            self._executor.submit(self._download, char, self.style, self.size)
            self._progress_total += 1
            self.progress_updated.emit(self._progress_done, self._progress_total)
        return None

    def clear_cache(self) -> None:
        """Clear both memory and on-disk cache for the current style.

        Cancels any in-flight downloads, deletes the style's subdirectory
        under ``~/.cache/mojitap/``, and resets the HTTP session.
        The thread pool is re-created so future downloads still work.
        """
        style = self.style
        logger.info("Clearing cache for style '%s'", style)
        self._mem.clear()
        self._pending.clear()
        self._progress_done  = 0
        self._progress_total = 0
        self._executor.shutdown(wait=False)
        self._executor = ThreadPoolExecutor(
            max_workers=_MAX_WORKERS,
            thread_name_prefix="emoji-dl",
        )
        style_dir = _CACHE_ROOT / style
        if style_dir.exists():
            import shutil
            shutil.rmtree(style_dir, ignore_errors=True)
            logger.info("Deleted disk cache for '%s'", style)
        self._session = None
        self._not_found = set()
        # Also drop the fluent mapping so it is rebuilt on next use
        self._fluent_mapping = None

    def prefetch(self, chars: list[str]) -> None:
        """Pre-warm the cache for a list of emoji chars.

        Already-cached or already-pending chars are skipped.  The download
        queue is bounded by ``_MAX_WORKERS``.
        """
        new_count = 0
        for c in chars:
            if c in self._mem or c in self._pending:
                continue
            # Skip chars known to not exist in this style
            if c in self._not_found:
                continue
            # Check disk cache first – no point re-downloading what we have
            disk = self._disk_path(c)
            if disk and disk.exists():
                px = self._load_from_disk(disk)
                if px:
                    self._mem[c] = px
                    continue
            self._pending.add(c)
            self._executor.submit(self._download, c, self.style, self.size)
            new_count += 1
        if new_count:
            self._progress_total += new_count
            self.progress_updated.emit(self._progress_done, self._progress_total)

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _session_get(self) -> requests.Session:  # type: ignore[name-defined]
        """Lazy ``requests.Session`` – connection-pooling for keep-alive."""
        if self._session is None:
            import requests
            self._session = requests.Session()
        return self._session  # type: ignore[return-value]

    def _disk_path(self, char: str, style: str | None = None) -> Optional[Path]:
        cps = _codepoints(char)
        if not cps:
            return None
        resolved = style or self.style
        d = _CACHE_ROOT / resolved
        d.mkdir(parents=True, exist_ok=True)
        ext = "svg" if resolved in _SVG_STYLES else "png"
        return d / f"{'-'.join(cps)}.{ext}"

    def _load_from_disk(self, path: Path) -> Optional[QPixmap]:
        if path.suffix == ".svg":
            return _render_svg(path.read_bytes(), self.size)
        px = QPixmap(str(path))
        if px.isNull():
            return None
        return px.scaled(
            self.size, self.size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    # ------------------------------------------------------------------
    # Not-found tracking (persist 404s so we don't keep retrying)
    # ------------------------------------------------------------------

    def _not_found_path(self) -> Path:
        return _CACHE_ROOT / self.style / ".notfound.json"

    def _load_not_found(self) -> None:
        p = self._not_found_path()
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                self._not_found = set(data) if isinstance(data, list) else set()
                if self._not_found:
                    logger.debug(
                        "Loaded %d not-found entries for '%s'",
                        len(self._not_found), self.style,
                    )
            except Exception:
                self._not_found = set()
        else:
            self._not_found = set()

    def _save_not_found(self) -> None:
        p = self._not_found_path()
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(
                json.dumps(sorted(self._not_found), separators=(",", ":")),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Failed to save not-found cache: %s", exc)

    # ------------------------------------------------------------------
    # Fluent Emoji mapping
    # ------------------------------------------------------------------

    def _ensure_fluent_mapping(self) -> None:
        """Load or build the Fluent Emoji codepoint→path mapping."""
        if self._fluent_mapping is not None:
            return

        if _FLUENT_MAPPING_CACHE.exists():
            try:
                self._fluent_mapping = json.loads(
                    _FLUENT_MAPPING_CACHE.read_text(encoding="utf-8")
                )
                return
            except Exception:
                pass

        self._fluent_mapping = self._build_fluent_mapping()

        # Persist to cache
        try:
            _FLUENT_MAPPING_CACHE.write_text(
                json.dumps(self._fluent_mapping, separators=(",", ":")),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _build_fluent_mapping(self) -> dict[str, dict[str, str]]:
        """Download the Fluent Emoji repo tree and build a codepoint mapping.

        Returns ``{codepoint_key: {"folder": folder_name, "base": file_base}}``.
        """
        import urllib.parse

        session = self._session_get()

        # 1) Get the recursive tree
        tree_url = (
            f"https://api.github.com/repos/{_FLUENT_REPO}/git/trees/"
            f"{_FLUENT_BRANCH}?recursive=1"
        )
        try:
            resp = session.get(tree_url, timeout=15)
            if resp.status_code != 200:
                return {}
            tree = resp.json().get("tree", [])
        except Exception:
            return {}

        # 2) Find all folders that contain 3D PNGs
        folders: set[str] = set()
        for entry in tree:
            p = entry["path"]
            if p.endswith("_3d.png") and "/3D/" in p:
                # path: assets/<folder>/3D/<base>_3d.png
                parts = p.split("/")
                if len(parts) >= 3:
                    folders.add(parts[1])  # folder name

        # 3) Build a name→codepoint lookup from the emoji library
        try:
            import emoji as _emoji_lib
        except ImportError:
            return {}

        def _folder_from_en(en_name: str) -> str:
            """Derive expected fluent folder name from the emoji en name."""
            name = en_name.strip(":")
            folder = name.replace("_", " ")
            return folder[0].upper() + folder[1:] if folder else folder

        name_to_key: dict[str, str] = {}
        for char, meta in _emoji_lib.EMOJI_DATA.items():
            en = meta.get("en", "").strip(":")
            if en:
                folder = _folder_from_en(en)
                key = _char_to_cp_key(char)
                name_to_key[folder.lower()] = key

        # 4) Build the mapping
        mapping: dict[str, dict[str, str]] = {}
        for folder in sorted(folders):
            key = name_to_key.get(folder.lower())
            if key:
                base = folder.lower().replace(" ", "_")
                mapping[key] = {"folder": folder, "base": base}

        # 5) For any unmatched folders, try to fetch metadata.json directly
        #    (limited number, done one-by-one)
        unmatched = folders - {e["folder"] for e in mapping.values()}
        for folder in unmatched:
            try:
                encoded = urllib.parse.quote(folder)
                meta_url = (
                    f"https://raw.githubusercontent.com/{_FLUENT_REPO}/"
                    f"{_FLUENT_BRANCH}/assets/{encoded}/metadata.json"
                )
                r = session.get(meta_url, timeout=8)
                if r.status_code == 200:
                    md = r.json()
                    cp_str = md.get("unicode", "")
                    if cp_str:
                        key = cp_str  # space-separated codepoints already
                        base = folder.lower().replace(" ", "_")
                        mapping[key] = {"folder": folder, "base": base}
            except Exception:
                continue

        return mapping

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    def _download(self, char: str, style: str, size: int) -> None:
        cp = "-".join(_codepoints(char))
        try:
            # Retry loop (2 attempts with back-off) for transient failures
            if style == "fluent":
                url = _fluent_url(char, self._fluent_mapping or {})
            else:
                url = _cdn_url(style, char)
            if not url:
                logger.debug("No URL for %s/%s – skipping", style, cp)
                self._count_progress()
                return
            session = self._session_get()
            for attempt in range(2):
                try:
                    resp = session.get(url, timeout=8)
                    if resp.status_code == 200:
                        break
                    if resp.status_code == 404:
                        logger.debug("404 for %s/%s – not in this style", style, cp)
                        # Remember so we don't keep retrying
                        if self.style == style:
                            self._not_found.add(char)
                            self._save_not_found()
                        self._count_progress()
                        return
                    logger.warning("HTTP %d for %s/%s (attempt %d)",
                                   resp.status_code, style, cp, attempt)
                except Exception as exc:
                    logger.warning("Request failed for %s/%s (attempt %d): %s",
                                   style, cp, attempt, exc)
                    if attempt == 0:
                        time.sleep(0.3)
                        continue
                    self._count_progress()
                    return
            else:
                logger.warning("Both attempts failed for %s/%s", style, cp)
                self._count_progress()
                return

            disk = self._disk_path(char, style)
            if not disk:
                self._count_progress()
                return
            disk.write_bytes(resp.content)

            if style in _SVG_STYLES:
                px = _render_svg(resp.content, size)
            else:
                px = QPixmap()
                px.loadFromData(resp.content)
                if px and not px.isNull():
                    px = px.scaled(
                        size, size,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
            if px and not px.isNull():
                # Only populate memory cache if the style hasn't changed since
                # this download was submitted.  Otherwise a stale download that
                # was in-flight during a style switch would pollute the cache.
                if self.style == style:
                    self._mem[char] = px
                    self.image_ready.emit(char, px)
                    logger.info("Downloaded %s/%s OK (%.1f KB)", style, cp, len(resp.content) / 1024)
                else:
                    logger.debug("Stale download %s/%s (style changed to %s) – discarding",
                                 style, cp, self.style)
            self._count_progress()
        except Exception as exc:
            logger.error("Unhandled error downloading %s/%s: %s", style, cp, exc)
            self._count_progress()
        finally:
            self._pending.discard(char)

    def _count_progress(self) -> None:
        """Increment the done counter and emit progress.

        Called on EVERY terminal outcome of _download (success, 404, error)
        so the progress bar never gets stuck.
        """
        self._progress_done += 1
        self.progress_updated.emit(self._progress_done, self._progress_total)
