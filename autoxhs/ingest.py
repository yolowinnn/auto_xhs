"""Load a day's brief.yaml and raw materials from input/<DATE>/."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from .config import Config
from .models import Brief, Material

VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".bmp"}


def _natural_key(p: Path):
    return [int(t) if t.isdigit() else t.lower()
            for t in re.split(r"(\d+)", p.name)]


def material_kind(path: Path) -> str | None:
    ext = path.suffix.lower()
    if ext in VIDEO_EXTS:
        return "video"
    if ext in IMAGE_EXTS:
        return "image"
    return None


def load_brief(cfg: Config, date: str) -> Brief:
    d = cfg.date_input_dir(date)
    brief_path = d / "brief.yaml"
    raw: dict = {}
    if brief_path.exists():
        raw = yaml.safe_load(brief_path.read_text()) or {}
    return Brief(
        date=date,
        type=raw.get("type", "auto"),
        topic=raw.get("topic", ""),
        title=raw.get("title"),
        hook_title=raw.get("hook_title") or raw.get("hook"),
        body=raw.get("body"),
        script=raw.get("script"),
        explicit_segments=raw.get("segments"),
        tags=raw.get("tags") or [],
        voice=raw.get("voice"),
        bgm=raw.get("bgm"),
        visibility=raw.get("visibility"),
        images=raw.get("images"),
        raw=raw,
    )


def discover_materials(cfg: Config, date: str) -> list[Material]:
    """All usable media in the day's folder, natural-sorted by filename."""
    d = cfg.date_input_dir(date)
    if not d.exists():
        return []
    mats: list[Material] = []
    for p in sorted(d.iterdir(), key=_natural_key):
        if p.name == "brief.yaml" or p.name.startswith("."):
            continue
        kind = material_kind(p)
        if kind:
            mats.append(Material(path=p, kind=kind))
    return mats


def _resolve(d: Path, name: str) -> Path:
    """Resolve a material name from the brief to an absolute path."""
    p = Path(name)
    return p if p.is_absolute() else (d / name)


def ordered_materials(cfg: Config, date: str, brief: Brief) -> list[Material]:
    """Materials in the order the brief implies (explicit segments / images),
    else natural filename order."""
    d = cfg.date_input_dir(date)
    found = {m.path.name: m for m in discover_materials(cfg, date)}

    names: list[str] = []
    if brief.explicit_segments:
        names = [s["material"] for s in brief.explicit_segments if s.get("material")]
    elif brief.images:
        names = list(brief.images)

    if not names:
        return discover_materials(cfg, date)

    ordered: list[Material] = []
    for name in names:
        base = Path(name).name
        if base in found:
            ordered.append(found[base])
        else:
            p = _resolve(d, name)
            kind = material_kind(p)
            if kind and p.exists():
                ordered.append(Material(path=p, kind=kind))
    return ordered


def load(cfg: Config, date: str) -> tuple[Brief, list[Material]]:
    brief = load_brief(cfg, date)
    materials = ordered_materials(cfg, date, brief)
    return brief, materials
