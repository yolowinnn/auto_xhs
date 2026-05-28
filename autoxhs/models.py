"""Dataclasses passed between pipeline stages."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Material:
    path: Path
    kind: str  # "video" | "image"


@dataclass
class WordTiming:
    text: str
    start: float  # seconds, relative to the start of its segment
    end: float


@dataclass
class Segment:
    material: Material
    text: str                                  # narration for this beat
    audio_path: Optional[Path] = None
    audio_dur: float = 0.0                     # length of the narration audio
    duration: float = 0.0                      # on-screen duration (audio_dur + pad)
    words: list[WordTiming] = field(default_factory=list)


@dataclass
class Script:
    title: str
    hook_title: str
    body: str
    tags: list[str]
    segments: list[Segment]


@dataclass
class Brief:
    date: str
    type: str = "auto"                         # "video" | "carousel" | "auto"
    topic: str = ""
    title: Optional[str] = None
    hook_title: Optional[str] = None
    body: Optional[str] = None
    script: Optional[str] = None               # hand-written narration (LLM fallback)
    explicit_segments: Optional[list[dict]] = None  # [{material, text}, ...]
    tags: list[str] = field(default_factory=list)
    voice: Optional[str] = None
    bgm: Optional[str] = None
    visibility: Optional[str] = None
    images: Optional[list[str]] = None         # explicit image order for carousel
    raw: dict = field(default_factory=dict)


@dataclass
class RenderResult:
    kind: str                                  # "video" | "carousel"
    date: str
    title: str
    body: str
    tags: list[str]
    visibility: str
    video_path: Optional[Path] = None
    images: list[Path] = field(default_factory=list)

    def to_manifest(self) -> dict:
        return {
            "kind": self.kind,
            "date": self.date,
            "title": self.title,
            "body": self.body,
            "tags": self.tags,
            "visibility": self.visibility,
            "video_path": str(self.video_path) if self.video_path else None,
            "images": [str(p) for p in self.images],
        }
