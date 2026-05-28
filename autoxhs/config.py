"""Configuration loading: deep-merge config.yaml over config.example.yaml."""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

import yaml

from . import ffmpeg_utils

# Repo root = parent of this package directory.
ROOT = Path(__file__).resolve().parents[1]


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class Config:
    def __init__(self, data: dict, root: Path):
        self.data = data
        self.root = root
        self.ffmpeg = ffmpeg_utils.resolve_ffmpeg(self.get("ffmpeg.bin", "auto"))
        self.ffprobe = ffmpeg_utils.resolve_ffprobe(self.get("ffmpeg.ffprobe_bin", "auto"))

    # --- dotted lookups ---------------------------------------------------
    def get(self, path: str, default: Any = None) -> Any:
        node: Any = self.data
        for part in path.split("."):
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                return default
        return node

    # --- resolved directories --------------------------------------------
    def _dir(self, key: str, fallback: str) -> Path:
        p = Path(self.get(key, fallback))
        if not p.is_absolute():
            p = self.root / p
        return p

    @property
    def input_dir(self) -> Path:
        return self._dir("project.input_dir", "input")

    @property
    def output_dir(self) -> Path:
        return self._dir("project.output_dir", "output")

    @property
    def state_dir(self) -> Path:
        return self._dir("project.state_dir", "state")

    @property
    def fonts_dir(self) -> Path:
        return self._dir("captions.fonts_dir", "assets/fonts")

    def date_input_dir(self, date: str) -> Path:
        return self.input_dir / date

    def date_output_dir(self, date: str) -> Path:
        return self.output_dir / date

    # --- secrets ----------------------------------------------------------
    def anthropic_key(self) -> str | None:
        key = os.environ.get("ANTHROPIC_API_KEY")
        if key:
            return key.strip()
        keyfile = self.root / ".anthropic_key"
        if keyfile.exists():
            return keyfile.read_text().strip() or None
        return None


def load(config_path: str | Path | None = None, root: Path | None = None) -> Config:
    root = Path(root) if root else ROOT
    example = root / "config" / "config.example.yaml"
    defaults = yaml.safe_load(example.read_text()) if example.exists() else {}

    if config_path is None:
        config_path = root / "config" / "config.yaml"
    config_path = Path(config_path)
    user = {}
    if config_path.exists():
        user = yaml.safe_load(config_path.read_text()) or {}

    return Config(_deep_merge(defaults, user), root)
