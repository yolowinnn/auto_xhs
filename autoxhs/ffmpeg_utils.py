"""ffmpeg/ffprobe discovery and thin subprocess helpers.

The default Homebrew ffmpeg is often built WITHOUT libass/freetype, so the
caption filters (`ass`, `drawtext`, `subtitles`) are missing. We therefore
prefer a build that has them (ffmpeg-full's keg path on Homebrew).
"""

from __future__ import annotations

import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

# Common locations of a libass-enabled ffmpeg on macOS (Homebrew ffmpeg-full is keg-only).
_FFMPEG_CANDIDATES = [
    "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg",
    "/usr/local/opt/ffmpeg-full/bin/ffmpeg",
]
_FFPROBE_CANDIDATES = [
    "/opt/homebrew/opt/ffmpeg-full/bin/ffprobe",
    "/usr/local/opt/ffmpeg-full/bin/ffprobe",
]


@lru_cache(maxsize=8)
def _has_filter(ffmpeg_bin: str, name: str) -> bool:
    try:
        out = subprocess.run(
            [ffmpeg_bin, "-hide_banner", "-filters"],
            capture_output=True, text=True, timeout=20,
        ).stdout
    except Exception:
        return False
    return any(f" {name} " in line for line in out.splitlines())


def resolve_ffmpeg(setting: str) -> str:
    """Resolve the ffmpeg binary. `setting` is a path, or "auto" to autodetect a
    build that supports the `ass` caption filter."""
    if setting and setting != "auto":
        return setting
    for cand in _FFMPEG_CANDIDATES:
        if Path(cand).exists() and _has_filter(cand, "ass"):
            return cand
    onpath = shutil.which("ffmpeg")
    if onpath:
        return onpath
    # Last resort: return the first candidate path so the error message is useful.
    return _FFMPEG_CANDIDATES[0]


def resolve_ffprobe(setting: str) -> str:
    if setting and setting != "auto":
        return setting
    for cand in _FFPROBE_CANDIDATES:
        if Path(cand).exists():
            return cand
    return shutil.which("ffprobe") or _FFPROBE_CANDIDATES[0]


def supports_captions(ffmpeg_bin: str) -> bool:
    return _has_filter(ffmpeg_bin, "ass")


def run(cmd: list[str], *, quiet: bool = True) -> None:
    """Run an ffmpeg/ffprobe command, raising RuntimeError with stderr on failure."""
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-25:])
        raise RuntimeError(
            f"command failed ({proc.returncode}): {' '.join(cmd[:3])} ...\n{tail}"
        )
    if not quiet and proc.stderr:
        print(proc.stderr.strip().splitlines()[-1])


def probe_duration(ffprobe_bin: str, path: Path) -> float:
    """Return media duration in seconds (0.0 if it can't be determined)."""
    try:
        out = subprocess.run(
            [ffprobe_bin, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=30,
        ).stdout.strip()
        return float(out)
    except (ValueError, subprocess.SubprocessError):
        return 0.0
