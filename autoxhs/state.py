"""Tiny JSON state store so a daily run never double-posts."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .config import Config
from .models import RenderResult


def _path(cfg: Config) -> Path:
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    return cfg.state_dir / "posted.json"


def load(cfg: Config) -> dict:
    p = _path(cfg)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def is_posted(cfg: Config, date: str) -> bool:
    return date in load(cfg) and load(cfg)[date].get("status") == "posted"


def mark_posted(cfg: Config, date: str, result: RenderResult, response: dict) -> None:
    data = load(cfg)
    data[date] = {
        "status": "posted",
        "posted_at": datetime.now().isoformat(timespec="seconds"),
        "kind": result.kind,
        "title": result.title,
        "post_id": (response or {}).get("post_id") or (response or {}).get("data", {}).get("post_id"),
        "response": response,
    }
    _path(cfg).write_text(json.dumps(data, ensure_ascii=False, indent=2))
