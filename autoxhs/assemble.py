"""Video assembly with ffmpeg.

Each segment is normalized to an identical 9:16 silent clip whose length equals
its narration (audio_dur + pad), so the concatenated video lines up sample-for-
sample with the concatenated voiceover. Captions are burned from a prebuilt .ass.
"""

from __future__ import annotations

from pathlib import Path

from .config import Config
from .ffmpeg_utils import probe_duration, run
from .models import Script, Segment


def plan_durations(cfg: Config, script: Script) -> float:
    """Set seg.duration for every segment; return the total timeline length."""
    pad = cfg.get("video.segment_pad_sec", 0.35)
    default_image = cfg.get("video.default_image_dur", 3.0)
    total = 0.0
    for seg in script.segments:
        if seg.audio_dur > 0:
            base = seg.audio_dur
        elif seg.material.kind == "video":
            base = probe_duration(cfg.ffprobe, seg.material.path) or default_image
        else:
            base = default_image
        seg.duration = round(base + pad, 3)
        total += seg.duration
    return round(total, 3)


def _venc(cfg: Config) -> list[str]:
    enc = cfg.get("ffmpeg.encoder", "libx264")
    if enc == "h264_videotoolbox":
        return ["-c:v", "h264_videotoolbox", "-b:v", "8M"]
    return ["-c:v", enc, "-crf", str(cfg.get("ffmpeg.crf", 18)),
            "-preset", cfg.get("ffmpeg.preset", "medium")]


def _normalize_segment(cfg: Config, seg: Segment, idx: int, work_dir: Path) -> Path:
    W = cfg.get("ffmpeg.width", 1080)
    H = cfg.get("ffmpeg.height", 1920)
    fps = cfg.get("ffmpeg.fps", 30)
    dur = seg.duration
    out = work_dir / f"seg_{idx:03d}.mp4"
    fill = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}"

    if seg.material.kind == "image":
        if cfg.get("video.ken_burns", False):
            frames = max(1, round(dur * fps))
            vf = (f"scale={W*3}:{H*3}:force_original_aspect_ratio=increase,"
                  f"crop={W*3}:{H*3},"
                  f"zoompan=z='min(1.0+0.12*on/{frames},1.12)':d=1:"
                  f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                  f"s={W}x{H}:fps={fps},setsar=1,format=yuv420p")
        else:
            vf = f"{fill},setsar=1,fps={fps},format=yuv420p"
        cmd = [cfg.ffmpeg, "-y", "-loop", "1", "-t", f"{dur}",
               "-i", str(seg.material.path), "-vf", vf, "-t", f"{dur}",
               "-r", str(fps), *_venc(cfg), "-pix_fmt", "yuv420p", "-an", str(out)]
    else:
        L = probe_duration(cfg.ffprobe, seg.material.path)
        pad_needed = max(0.0, dur - L + 0.05)
        vf = (f"{fill},setsar=1,fps={fps},"
              f"tpad=stop_mode=clone:stop_duration={pad_needed:.3f},format=yuv420p")
        cmd = [cfg.ffmpeg, "-y", "-i", str(seg.material.path), "-vf", vf,
               "-t", f"{dur}", "-r", str(fps), *_venc(cfg),
               "-pix_fmt", "yuv420p", "-an", str(out)]
    run(cmd)
    return out


def _concat_video(cfg: Config, segs: list[Path], work_dir: Path) -> Path:
    listfile = work_dir / "video_concat.txt"
    listfile.write_text("".join(f"file '{p.resolve()}'\n" for p in segs))
    out = work_dir / "video_concat.mp4"
    run([cfg.ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(listfile),
         "-c", "copy", str(out)])
    return out


def _build_voice(cfg: Config, script: Script, work_dir: Path) -> Path:
    """Concatenate per-segment narration, padding each to its on-screen duration
    (and filling silent segments), into one sample-accurate PCM wav."""
    parts: list[Path] = []
    for i, seg in enumerate(script.segments):
        part = work_dir / f"voice_{i:03d}.wav"
        if seg.audio_path and seg.audio_dur > 0:
            run([cfg.ffmpeg, "-y", "-i", str(seg.audio_path),
                 "-af", f"apad=whole_dur={seg.duration}",
                 "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", str(part)])
        else:
            run([cfg.ffmpeg, "-y", "-f", "lavfi",
                 "-i", "anullsrc=r=44100:cl=stereo", "-t", f"{seg.duration}",
                 "-c:a", "pcm_s16le", str(part)])
        parts.append(part)

    listfile = work_dir / "audio_concat.txt"
    listfile.write_text("".join(f"file '{p.resolve()}'\n" for p in parts))
    out = work_dir / "voice.wav"
    run([cfg.ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(listfile),
         "-c", "copy", str(out)])
    return out


def _ass_arg(ass_path: Path, fonts_dir: Path) -> str:
    # Escape backslashes then single quotes for the filtergraph token.
    def esc(p: str) -> str:
        return p.replace("\\", "\\\\").replace("'", "\\'")
    arg = f"ass=filename='{esc(str(ass_path.resolve()))}'"
    if fonts_dir.exists():
        arg += f":fontsdir='{esc(str(fonts_dir.resolve()))}'"
    return arg


def assemble(cfg: Config, script: Script, ass_path: Path, out_path: Path,
             work_dir: Path, total: float, bgm: Path | None = None) -> Path:
    work_dir.mkdir(parents=True, exist_ok=True)
    seg_clips = [_normalize_segment(cfg, seg, i, work_dir)
                 for i, seg in enumerate(script.segments)]
    video = _concat_video(cfg, seg_clips, work_dir)
    voice = _build_voice(cfg, script, work_dir)
    fps = cfg.get("ffmpeg.fps", 30)

    vchain = f"[0:v]{_ass_arg(ass_path, cfg.fonts_dir)}[v]"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if bgm and Path(bgm).exists():
        bgm_vol = cfg.get("video.bgm_volume", 0.12)
        fc = (f"{vchain};"
              f"[1:a]volume=1.0[a0];[2:a]volume={bgm_vol}[a1];"
              f"[a0][a1]amix=inputs=2:duration=longest:dropout_transition=0[a]")
        cmd = [cfg.ffmpeg, "-y", "-i", str(video), "-i", str(voice),
               "-stream_loop", "-1", "-i", str(bgm),
               "-filter_complex", fc, "-map", "[v]", "-map", "[a]",
               "-t", f"{total}", *_venc(cfg), "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-b:a", "192k", "-r", str(fps),
               "-movflags", "+faststart", str(out_path)]
    else:
        cmd = [cfg.ffmpeg, "-y", "-i", str(video), "-i", str(voice),
               "-filter_complex", vchain, "-map", "[v]", "-map", "1:a",
               "-t", f"{total}", *_venc(cfg), "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-b:a", "192k", "-r", str(fps),
               "-movflags", "+faststart", str(out_path)]
    run(cmd)
    return out_path
