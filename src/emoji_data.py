"""Emoji data – categories, entries, and search.

Category data is sourced from the Unicode emoji-test.txt file (downloaded once
on first run and cached at ~/.cache/mojitap/emoji_groups.json).
Emoji name/alias data comes from the *emoji* Python library.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Category display metadata (icon shown in the category bar, sort order)
# ---------------------------------------------------------------------------

CATEGORY_META: dict[str, dict] = {
    "Smileys & Emotion": {"icon": "😊", "order": 1},
    "People & Body":     {"icon": "🧑", "order": 2},
    "Animals & Nature":  {"icon": "🐶", "order": 3},
    "Food & Drink":      {"icon": "🍕", "order": 4},
    "Travel & Places":   {"icon": "✈️",  "order": 5},
    "Activities":        {"icon": "⚽", "order": 6},
    "Objects":           {"icon": "💡", "order": 7},
    "Symbols":           {"icon": "❤️",  "order": 8},
    "Flags":             {"icon": "🏳️", "order": 9},
}

RECENT_META = {"icon": "⏱", "order": 0, "label": "Recent"}

# Fitzpatrick skin-tone modifier characters (index 0 = no modifier)
SKIN_TONE_MODIFIERS = [
    "",
    "\U0001f3fb",  # light
    "\U0001f3fc",  # medium-light
    "\U0001f3fd",  # medium
    "\U0001f3fe",  # medium-dark
    "\U0001f3ff",  # dark
]
SKIN_TONE_SET = set(SKIN_TONE_MODIFIERS[1:])

_UNICODE_TEST_URL = "https://unicode.org/Public/emoji/15.1/emoji-test.txt"
_GROUPS_CACHE     = Path.home() / ".cache" / "mojitap" / "emoji_groups.json"

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class EmojiEntry:
    char: str
    name: str
    category: str
    subcategory: str
    sort_order: int
    keywords: list[str] = field(default_factory=list)
    has_skin_tones: bool = False


def strip_skin_tone(char: str) -> str:
    """Return *char* with Fitzpatrick modifiers removed."""
    return "".join(c for c in char if c not in SKIN_TONE_SET)


def apply_skin_tone(char: str, modifier: str) -> str:
    """Return the best skin-tone-adjusted form of *char*.

    The cache only stores base emojis, and the picker uses a single global tone
    selection. Normalize any incoming character back to its base form, then
    apply the selected modifier if that variant exists in the emoji database.
    """
    base = strip_skin_tone(char)
    if not modifier:
        return base
    data = _lib().EMOJI_DATA
    toned = base + modifier
    return toned if toned in data else base


# ---------------------------------------------------------------------------
# Unicode emoji-test.txt parser
# ---------------------------------------------------------------------------

def _parse_unicode_test(text: str) -> dict[str, dict]:
    """Parse emoji-test.txt → {char: {category, subcategory, sort_order}}."""
    result: dict[str, dict] = {}
    group    = ""
    subgroup = ""
    order    = 0
    for line in text.splitlines():
        line = line.rstrip()
        if line.startswith("# group:"):
            group = line[len("# group:"):].strip()
            continue
        if line.startswith("# subgroup:"):
            subgroup = line[len("# subgroup:"):].strip()
            continue
        if not line or line.startswith("#"):
            continue
        # data line: "1F600 ; fully-qualified # 😀 ..."
        m = re.match(r"^([0-9A-Fa-f ]+)\s*;\s*(\S+)", line)
        if not m:
            continue
        status = m.group(2)
        if status != "fully-qualified":
            continue
        cp_str = m.group(1).strip()
        try:
            char = "".join(chr(int(cp, 16)) for cp in cp_str.split())
        except ValueError:
            continue
        if group and group not in ("Component",):
            result[char] = {
                "category":   group,
                "subcategory": subgroup,
                "sort_order":  order,
            }
        order += 1
    return result


def _load_unicode_groups() -> dict[str, dict]:
    """Return {char: {category, subcategory, sort_order}}, fetching if needed."""
    _GROUPS_CACHE.parent.mkdir(parents=True, exist_ok=True)
    if _GROUPS_CACHE.exists():
        try:
            return json.loads(_GROUPS_CACHE.read_text(encoding="utf-8"))
        except Exception:
            pass

    # Download
    try:
        import urllib.request
        with urllib.request.urlopen(_UNICODE_TEST_URL, timeout=10) as r:
            text = r.read().decode("utf-8")
        groups = _parse_unicode_test(text)
        _GROUPS_CACHE.write_text(
            json.dumps(groups, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        return groups
    except Exception as exc:
        print(f"[emoji_data] Could not fetch Unicode groups: {exc}")
        return {}


# ---------------------------------------------------------------------------
# Internal cache
# ---------------------------------------------------------------------------

_cache_list:   list[EmojiEntry]            = []
_cache_by_cat: dict[str, list[EmojiEntry]] = {}
_built = False
_emoji_lib = None   # lazy import


def _lib():
    global _emoji_lib
    if _emoji_lib is None:
        import emoji as _e
        _emoji_lib = _e
    return _emoji_lib


def _build_cache() -> None:
    global _cache_list, _cache_by_cat, _built
    if _built:
        return
    _built = True

    lib    = _lib()
    data   = lib.EMOJI_DATA
    groups = _load_unicode_groups()   # char → {category, subcategory, sort_order}

    fq_status: Optional[int] = lib.STATUS.get("fully_qualified") if hasattr(lib, "STATUS") else None

    entries: list[EmojiEntry] = []
    seen:    set[str]         = set()

    for char, meta in data.items():
        if char in seen:
            continue
        # Keep only fully-qualified forms to avoid duplicates
        if fq_status is not None and meta.get("status") != fq_status:
            continue

        # Skip skin-tone variants – the base emoji is shown and the selected
        # modifier is applied at render/click time (EmojiCanvas.set_skin_tone).
        if any(t in char for t in SKIN_TONE_MODIFIERS[1:]):
            continue

        grp = groups.get(char, {})
        cat = grp.get("category", "")
        if not cat or cat == "Component":
            continue
        seen.add(char)

        raw_name = meta.get("en", "")
        name = raw_name.replace("_", " ").replace(":", "").strip()

        # Does this emoji have per-skin-tone variants?
        has_tones = any((char + t) in data for t in SKIN_TONE_MODIFIERS[1:])

        entries.append(EmojiEntry(
            char=char,
            name=name,
            category=cat,
            subcategory=grp.get("subcategory", ""),
            sort_order=grp.get("sort_order", 99999),
            keywords=[name] if name else [],
            has_skin_tones=has_tones,
        ))

    entries.sort(key=lambda e: e.sort_order)
    _cache_list = entries

    for entry in entries:
        _cache_by_cat.setdefault(entry.category, []).append(entry)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def ensure_loaded() -> None:
    """Pre-build the cache (safe to call from any thread)."""
    _build_cache()


def get_categories() -> list[str]:
    """Return category names sorted by display order."""
    _build_cache()
    return sorted(
        _cache_by_cat.keys(),
        key=lambda c: CATEGORY_META.get(c, {}).get("order", 99),
    )


def get_by_category(cat: str) -> list[EmojiEntry]:
    _build_cache()
    return _cache_by_cat.get(cat, [])


def get_all() -> list[EmojiEntry]:
    _build_cache()
    return _cache_list


def search(query: str) -> list[EmojiEntry]:
    """Full-text search across name and keyword aliases."""
    _build_cache()
    q = query.lower().strip()
    if not q:
        return []

    scored: list[tuple[int, EmojiEntry]] = []
    seen: set[str] = set()

    for entry in _cache_list:
        if entry.char in seen:
            continue
        nl = entry.name.lower()
        score = 0
        if nl == q:
            score = 100
        elif nl.startswith(q):
            score = 80
        elif q in nl:
            score = 60
        else:
            for kw in entry.keywords:
                if q in kw.lower():
                    score = 40
                    break
        if score:
            scored.append((score, entry))
            seen.add(entry.char)

    scored.sort(key=lambda x: (-x[0], x[1].sort_order))
    return [e for _, e in scored]


def make_recent_entries(chars: list[str]) -> list[EmojiEntry]:
    """Build EmojiEntry list from a list of raw emoji chars (recent history)."""
    _build_cache()
    # Look up from the main cache for proper names
    by_char = {e.char: e for e in _cache_list}
    result: list[EmojiEntry] = []
    seen:   set[str]         = set()
    for char in chars:
        base_char = strip_skin_tone(char)
        if base_char in seen:
            continue
        seen.add(base_char)
        if base_char in by_char:
            src = by_char[base_char]
            result.append(EmojiEntry(
                char=base_char,
                name=src.name,
                category="Recent",
                subcategory="",
                sort_order=0,
                keywords=src.keywords,
                has_skin_tones=src.has_skin_tones,
            ))
        else:
            result.append(EmojiEntry(char=base_char, name=base_char,
                                     category="Recent", subcategory="", sort_order=0))
    return result
