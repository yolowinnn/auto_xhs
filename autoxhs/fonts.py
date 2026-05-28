"""Font resolution.

libass (captions) resolves fonts by *family name* via fontconfig, so we just
pass a family string. Pillow (carousel title cards) needs an actual font *file*,
so we hunt for a usable CJK .ttc/.otf on disk, preferring a bundled font in
assets/fonts for reproducibility.
"""

from __future__ import annotations

from pathlib import Path

# System CJK fonts that ship with macOS, in order of preference.
_MAC_FONT_FILES = [
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
]


def resolve_font_file(fonts_dir: Path) -> str | None:
    """Return a path to a usable CJK font file for Pillow rendering."""
    if fonts_dir.exists():
        for pattern in ("*.otf", "*.ttf", "*.ttc"):
            hits = sorted(fonts_dir.glob(pattern))
            if hits:
                return str(hits[0])
    for cand in _MAC_FONT_FILES:
        if Path(cand).exists():
            return cand
    return None
