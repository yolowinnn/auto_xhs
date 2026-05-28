"""Build a styled .ass file: a persistent hook title (top) + timed subtitles
(bottom), driven by the per-segment word timings from TTS. libass renders CJK
cleanly and handles outline/box styling, so we do everything in one .ass and
burn it with a single `ass` filter — no drawtext escaping headaches.
"""

from __future__ import annotations

from pathlib import Path

from .config import Config
from .models import Script, Segment, WordTiming


def _fmt_time(sec: float) -> str:
    sec = max(0.0, sec)
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h:d}:{m:02d}:{s:05.2f}"


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", "\\N")


_BREAK_AFTER = set("，。！？、；：,.!?;: ")


def _expand_chars(marks: list[WordTiming]) -> list[tuple[str, float, float]]:
    """Spread each timed span (a word or a whole sentence) evenly across its
    characters, yielding per-character (char, start, end) timing."""
    chars: list[tuple[str, float, float]] = []
    for m in marks:
        n = len(m.text)
        if n == 0 or m.end <= m.start:
            continue
        d = (m.end - m.start) / n
        for i, ch in enumerate(m.text):
            chars.append((ch, m.start + i * d, m.start + (i + 1) * d))
    return chars


def _group_chars(chars: list[tuple[str, float, float]], max_chars: int
                 ) -> list[tuple[float, float, str]]:
    """Regroup characters into short cues, breaking at punctuation or max length."""
    cues: list[tuple[float, float, str]] = []
    buf: list[tuple[str, float, float]] = []
    for ch, s, e in chars:
        buf.append((ch, s, e))
        if len(buf) >= max_chars or ch in _BREAK_AFTER:
            cues.append((buf[0][1], buf[-1][2], "".join(c for c, _, _ in buf)))
            buf = []
    if buf:
        cues.append((buf[0][1], buf[-1][2], "".join(c for c, _, _ in buf)))

    # Clean up and merge tiny orphan fragments (e.g. a single trailing char) into
    # the previous cue so we never flash a 1-character subtitle.
    out: list[tuple[float, float, str]] = []
    for s, e, t in cues:
        t = t.strip().strip("".join(_BREAK_AFTER))
        if not t:
            continue
        if out and (len(t) <= 2 or (e - s) < 0.35):
            ps, _, pt = out[-1]
            out[-1] = (ps, e, pt + t)
        else:
            out.append((s, e, t))
    return out


def _segment_cues(seg: Segment, max_chars: int) -> list[tuple[float, float, str]]:
    marks = seg.words
    if not marks and seg.text.strip() and seg.audio_dur > 0:
        marks = [WordTiming(text=seg.text.strip(), start=0.0, end=seg.audio_dur)]
    if not marks:
        return []
    return _group_chars(_expand_chars(marks), max_chars)


def _style_line(name: str, font: str, fontsize: int, primary: str, outline_color: str,
                back_color: str, border_style: int, outline: int, shadow: int,
                alignment: int, margin_v: int, bold: int = 1) -> str:
    # Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,
    # BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,
    # BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
    return (f"Style: {name},{font},{fontsize},{primary},&H000000FF,{outline_color},"
            f"{back_color},{bold},0,0,0,100,100,0,0,{border_style},{outline},{shadow},"
            f"{alignment},40,40,{margin_v},1")


def build_ass(cfg: Config, script: Script, total_duration: float, out_path: Path) -> Path:
    width = cfg.get("ffmpeg.width", 1080)
    height = cfg.get("ffmpeg.height", 1920)
    font = cfg.get("captions.font", "PingFang SC")

    sub = cfg.get("captions.subtitle", {})
    title = cfg.get("captions.title", {})
    max_chars = sub.get("max_chars_per_cue", 16)

    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        ("Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
         "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
         "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
         "MarginL, MarginR, MarginV, Encoding"),
        _style_line(
            "Sub", font, sub.get("fontsize", 60),
            sub.get("primary_color", "&H00FFFFFF"),
            sub.get("outline_color", "&H00000000"), "&H00000000",
            border_style=1, outline=sub.get("outline", 3), shadow=sub.get("shadow", 1),
            alignment=2, margin_v=sub.get("margin_v", 260),
        ),
    ]

    # With BorderStyle=3 (opaque box) libass paints the box in OutlineColour, so
    # the box colour goes in that slot; with BorderStyle=1 it's the text stroke.
    title_box = title.get("box", True)
    title_outline = title.get("box_color", "&H64000000") if title_box else "&H00000000"
    lines.append(_style_line(
        "Title", font, title.get("fontsize", 78),
        title.get("primary_color", "&H00FFFFFF"), title_outline, "&H00000000",
        border_style=3 if title_box else 1,
        outline=title.get("outline", 4), shadow=0,
        alignment=8, margin_v=title.get("margin_v", 200),
    ))

    lines += [
        "",
        "[Events]",
        ("Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
         "Effect, Text"),
    ]

    # Persistent hook title across the whole video.
    if title.get("enabled", True) and script.hook_title.strip():
        lines.append(
            f"Dialogue: 0,{_fmt_time(0)},{_fmt_time(total_duration)},Title,,0,0,0,,"
            f"{_escape(script.hook_title.strip())}"
        )

    # Timed subtitles, offset onto the global timeline.
    offset = 0.0
    for seg in script.segments:
        for (cs, ce, text) in _segment_cues(seg, max_chars):
            lines.append(
                f"Dialogue: 0,{_fmt_time(offset + cs)},{_fmt_time(offset + ce)},"
                f"Sub,,0,0,0,,{_escape(text)}"
            )
        offset += seg.duration

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path
