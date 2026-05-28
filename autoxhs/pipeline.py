"""End-to-end orchestration: ingest -> script -> render (video|carousel) -> publish.

`render` produces the post and a manifest.json in output/<DATE>/; publishing reads
that manifest, so generation and posting can be separate steps (the review gate).
"""

from __future__ import annotations

import json
from pathlib import Path

from . import assemble, captions, carousel, ingest, publish, state, tts
from . import script as script_mod
from .config import Config
from .models import RenderResult, Script


def decide_kind(brief, materials) -> str:
    if brief.type in ("video", "carousel"):
        return brief.type
    if any(m.kind == "video" for m in materials):
        return "video"
    if any(m.kind == "image" for m in materials):
        return "carousel"
    return "video"


def _resolve_bgm(cfg: Config, date: str, brief) -> Path | None:
    if not brief.bgm:
        return None
    p = Path(brief.bgm)
    return p if p.is_absolute() else cfg.date_input_dir(date) / brief.bgm


def render(cfg: Config, date: str) -> RenderResult:
    brief, materials = ingest.load(cfg, date)
    if not materials:
        raise RuntimeError(f"no materials found in {cfg.date_input_dir(date)} "
                           "(add clips/images + brief.yaml)")
    kind = decide_kind(brief, materials)
    scr = script_mod.generate(cfg, brief, materials)

    out_dir = cfg.date_output_dir(date)
    work = out_dir / "work"
    out_dir.mkdir(parents=True, exist_ok=True)
    visibility = brief.visibility or cfg.get("publish.default_visibility", "公开可见")

    if kind == "video":
        tts.synthesize_script(cfg, scr, work / "tts", voice=brief.voice)
        total = assemble.plan_durations(cfg, scr)
        ass = captions.build_ass(cfg, scr, total, work / "subs.ass")
        video_out = out_dir / f"{date}.mp4"
        assemble.assemble(cfg, scr, ass, video_out, work, total,
                          bgm=_resolve_bgm(cfg, date, brief))
        result = RenderResult(kind="video", date=date, title=scr.title, body=scr.body,
                              tags=scr.tags, visibility=visibility, video_path=video_out)
    else:
        imgs = carousel.build_carousel(cfg, scr, materials, out_dir / "images")
        if not imgs:
            raise RuntimeError("carousel produced no usable images")
        result = RenderResult(kind="carousel", date=date, title=scr.title, body=scr.body,
                              tags=scr.tags, visibility=visibility, images=imgs)

    _write_manifest(cfg, date, result, scr)
    return result


def _write_manifest(cfg: Config, date: str, result: RenderResult, scr: Script) -> None:
    out_dir = cfg.date_output_dir(date)
    manifest = result.to_manifest()
    manifest["segments"] = [
        {"material": s.material.path.name, "text": s.text, "dur": s.duration}
        for s in scr.segments
    ]
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2))
    (out_dir / "caption.txt").write_text(
        f"{result.title}\n\n{result.body}\n", encoding="utf-8")


def load_manifest(cfg: Config, date: str) -> RenderResult:
    p = cfg.date_output_dir(date) / "manifest.json"
    if not p.exists():
        raise RuntimeError(f"no manifest for {date}; run `generate {date}` first")
    m = json.loads(p.read_text())
    return RenderResult(
        kind=m["kind"], date=m["date"], title=m["title"], body=m["body"],
        tags=m.get("tags", []), visibility=m.get("visibility", "公开可见"),
        video_path=Path(m["video_path"]) if m.get("video_path") else None,
        images=[Path(x) for x in m.get("images", [])],
    )


def publish_post(cfg: Config, date: str, schedule_at: str | None = None) -> dict:
    result = load_manifest(cfg, date)
    resp = publish.publish(cfg, result, schedule_at=schedule_at)
    state.mark_posted(cfg, date, result, resp)
    return resp
