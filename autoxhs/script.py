"""Turn a brief + materials into a Script (title / hook / body / tags / segments).

Uses the Anthropic API when a key is available; otherwise falls back to the
hand-written script/segments in brief.yaml so the pipeline always runs.
"""

from __future__ import annotations

import json
import re

from .config import Config
from .models import Brief, Material, Script, Segment

_SENT_SPLIT = re.compile(r"[。！？!?\n]+")


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT_SPLIT.split(text or "") if s.strip()]


def _distribute(items: list[str], n: int) -> list[list[str]]:
    """Split `items` into n groups, roughly even, order preserved."""
    if n <= 0:
        return []
    groups: list[list[str]] = [[] for _ in range(n)]
    if not items:
        return groups
    for i, it in enumerate(items):
        groups[min(i * n // len(items), n - 1)].append(it)
    return groups


def _clip(text: str, max_chars: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= max_chars else text[:max_chars]


def _ensure_tags_in_body(body: str, tags: list[str]) -> str:
    body = (body or "").strip()
    if not tags:
        return body
    if "#" in body:
        return body
    tagline = " ".join(f"#{t.lstrip('#')}" for t in tags)
    return f"{body}\n{tagline}".strip()


# --------------------------------------------------------------------------
# Fallback (no LLM)
# --------------------------------------------------------------------------
def _fallback(cfg: Config, brief: Brief, materials: list[Material]) -> Script:
    default_tags = cfg.get("publish.default_tags", []) or []
    tags = brief.tags or default_tags

    title = brief.title or brief.hook_title or brief.topic or "我的一天"
    if brief.script and not brief.title:
        sents = split_sentences(brief.script)
        if sents:
            title = sents[0]
    title = _clip(title, cfg.get("publish.title_max", 20))
    hook = _clip(brief.hook_title or title, 16)

    body = brief.body or brief.script or brief.topic or title
    body = _ensure_tags_in_body(body, tags)
    body = _clip(body, cfg.get("publish.content_max", 1000))

    # Build narration segments.
    segments: list[Segment] = []
    if brief.explicit_segments:
        by_name = {m.path.name: m for m in materials}
        for s in brief.explicit_segments:
            name = s.get("material", "")
            mat = by_name.get(name) or by_name.get(name.split("/")[-1])
            if mat:
                segments.append(Segment(material=mat, text=(s.get("text") or "").strip()))
    elif materials:
        sents = split_sentences(brief.script) if brief.script else []
        groups = _distribute(sents, len(materials))
        for mat, grp in zip(materials, groups):
            segments.append(Segment(material=mat, text="，".join(grp)))

    return Script(title=title, hook_title=hook, body=body, tags=tags, segments=segments)


# --------------------------------------------------------------------------
# LLM path
# --------------------------------------------------------------------------
def _read_system_prompt(cfg: Config) -> str:
    path = cfg.root / cfg.get("llm.system_prompt_file", "prompts/system_prompt.md")
    if path.exists():
        return path.read_text()
    example = cfg.root / "prompts" / "system_prompt.example.md"
    return example.read_text() if example.exists() else ""


def _build_user_message(brief: Brief, materials: list[Material]) -> str:
    mat_lines = "\n".join(
        f"{i+1}. {m.path.name} ({m.kind})" for i, m in enumerate(materials)
    ) or "(no media files)"
    parts = [
        f"日期: {brief.date}",
        f"账号人设/topic: {brief.raw.get('persona', '')} | {brief.topic}".strip(" |"),
    ]
    if brief.title:
        parts.append(f"建议标题: {brief.title}")
    if brief.hook_title:
        parts.append(f"建议封面大字: {brief.hook_title}")
    if brief.script:
        parts.append(f"已有解说稿(可润色):\n{brief.script}")
    parts.append(f"素材(按顺序):\n{mat_lines}")
    parts.append("请按系统提示词的 JSON 格式输出,segments 覆盖以上素材。")
    return "\n\n".join(parts)


def _parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text).strip()
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1:
        text = text[start:end + 1]
    return json.loads(text)


def _from_llm(cfg: Config, brief: Brief, materials: list[Material]) -> Script:
    import anthropic  # imported lazily; optional dependency

    client = anthropic.Anthropic(api_key=cfg.anthropic_key())
    resp = client.messages.create(
        model=cfg.get("llm.model", "claude-sonnet-4-6"),
        max_tokens=cfg.get("llm.max_tokens", 2000),
        system=_read_system_prompt(cfg),
        messages=[{"role": "user", "content": _build_user_message(brief, materials)}],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    data = _parse_json(text)

    tags = data.get("tags") or brief.tags or cfg.get("publish.default_tags", [])
    title = _clip(data.get("title") or brief.topic, cfg.get("publish.title_max", 20))
    hook = _clip(data.get("hook_title") or title, 16)
    body = _clip(_ensure_tags_in_body(data.get("body", ""), tags),
                 cfg.get("publish.content_max", 1000))

    by_name = {m.path.name: m for m in materials}
    segments: list[Segment] = []
    used = set()
    for s in data.get("segments", []):
        name = (s.get("material") or "").split("/")[-1]
        mat = by_name.get(name)
        if mat:
            segments.append(Segment(material=mat, text=(s.get("text") or "").strip()))
            used.add(name)
    # Make sure no material is silently dropped.
    for m in materials:
        if m.path.name not in used:
            segments.append(Segment(material=m, text=""))

    return Script(title=title, hook_title=hook, body=body, tags=tags, segments=segments)


def generate(cfg: Config, brief: Brief, materials: list[Material]) -> Script:
    provider = cfg.get("llm.provider", "anthropic")
    if provider == "anthropic" and cfg.anthropic_key():
        try:
            return _from_llm(cfg, brief, materials)
        except Exception as e:  # fall back rather than crash the daily run
            print(f"[script] LLM generation failed ({e}); using brief fallback.")
    return _fallback(cfg, brief, materials)
