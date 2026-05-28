"""Text-to-speech via edge-tts (free, natural Mandarin) with word-level timings.

edge-tts emits WordBoundary events, so we get accurate per-word timing for free
and never need a separate forced-alignment / Whisper pass. The provider is kept
behind one function so Azure/Volcengine/Fish can be slotted in later.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from .config import Config
from .ffmpeg_utils import probe_duration
from .models import Script, Segment, WordTiming

_HUNDRED_NS = 1e7  # edge-tts reports offsets/durations in 100-nanosecond units


async def _edge_synth(text: str, out_path: Path, *, voice: str, rate: str,
                      volume: str, pitch: str) -> list[WordTiming]:
    import edge_tts

    comm = edge_tts.Communicate(text, voice, rate=rate, volume=volume, pitch=pitch)
    words: list[WordTiming] = []
    with open(out_path, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] in ("WordBoundary", "SentenceBoundary"):
                # zh-CN voices emit SentenceBoundary (not WordBoundary); we treat
                # either as a timed text span and split it into cues downstream.
                start = chunk["offset"] / _HUNDRED_NS
                end = start + chunk["duration"] / _HUNDRED_NS
                words.append(WordTiming(text=chunk["text"], start=start, end=end))
    return words


def synthesize(text: str, out_path: Path, *, voice: str, rate: str = "+0%",
               volume: str = "+0%", pitch: str = "+0Hz", max_retries: int = 4) -> list[WordTiming]:
    """Render `text` to an mp3 at out_path. Returns word timings (seconds, relative
    to the start of this clip). Retries with backoff for edge-tts rate limits."""
    last_err: Exception | None = None
    for attempt in range(max_retries):
        try:
            return asyncio.run(
                _edge_synth(text, out_path, voice=voice, rate=rate,
                            volume=volume, pitch=pitch)
            )
        except Exception as e:  # NoAudioReceived, 403 rate-limit, transient network
            last_err = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"TTS failed after {max_retries} attempts: {last_err}")


def synthesize_script(cfg: Config, script: Script, work_dir: Path,
                      voice: str | None = None) -> None:
    """Fill each segment's audio_path, audio_dur and words in place.
    Segments with empty narration are left silent (audio_dur stays 0)."""
    work_dir.mkdir(parents=True, exist_ok=True)
    voice = voice or cfg.get("tts.voice", "zh-CN-XiaoxiaoNeural")
    rate = cfg.get("tts.rate", "+0%")
    volume = cfg.get("tts.volume", "+0%")
    pitch = cfg.get("tts.pitch", "+0Hz")
    retries = cfg.get("tts.max_retries", 4)

    for i, seg in enumerate(script.segments):
        if not seg.text.strip():
            continue
        out = work_dir / f"seg_{i:03d}.mp3"
        seg.words = synthesize(
            seg.text, out, voice=voice, rate=rate, volume=volume,
            pitch=pitch, max_retries=retries,
        )
        seg.audio_path = out
        seg.audio_dur = probe_duration(cfg.ffprobe, out) or (
            seg.words[-1].end if seg.words else 0.0
        )
        time.sleep(0.3)  # be gentle with edge-tts per-IP rate limiting
