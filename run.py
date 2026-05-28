#!/usr/bin/env python3
"""auto_xhs CLI — generate and publish Xiaohongshu posts from daily materials.

  python run.py init                 # create config.yaml + system_prompt.md
  python run.py new 2026-05-28       # scaffold input/<DATE>/brief.yaml
  python run.py doctor               # check the local environment
  python run.py generate 2026-05-28  # render video/carousel into output/<DATE>/
  python run.py preview 2026-05-28   # open the rendered post + show caption
  python run.py publish 2026-05-28   # publish (review gate; --auto to skip prompt)
  python run.py run-daily            # generate + gate-publish today (for cron use --auto)
  python run.py login                # check login / save a QR to scan
"""

from __future__ import annotations

import argparse
import datetime
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from autoxhs import config as config_mod  # noqa: E402
from autoxhs import ffmpeg_utils, fonts, pipeline, state  # noqa: E402
from autoxhs.publish import PublishError, XhsClient  # noqa: E402

ROOT = Path(__file__).resolve().parent


def _today() -> str:
    return datetime.date.today().isoformat()


def _open(path: Path) -> None:
    if sys.platform == "darwin" and path.exists():
        subprocess.run(["open", str(path)], check=False)


# --------------------------------------------------------------------------
def cmd_init(args, cfg):
    pairs = [
        (ROOT / "config" / "config.example.yaml", ROOT / "config" / "config.yaml"),
        (ROOT / "prompts" / "system_prompt.example.md", ROOT / "prompts" / "system_prompt.md"),
    ]
    for src, dst in pairs:
        if dst.exists():
            print(f"exists, leaving as-is: {dst.relative_to(ROOT)}")
        elif src.exists():
            shutil.copy(src, dst)
            print(f"created: {dst.relative_to(ROOT)}")
    print("\nNext: `python run.py doctor`, then drop materials in input/<DATE>/ and "
          "`python run.py new <DATE>`.")


def cmd_new(args, cfg):
    date = args.date or _today()
    d = cfg.date_input_dir(date)
    d.mkdir(parents=True, exist_ok=True)
    brief = d / "brief.yaml"
    if brief.exists():
        print(f"brief already exists: {brief}")
        return
    template = f"""# Brief for {date}. Put your clips/images in this folder, then:
#   python run.py generate {date}
type: auto                       # auto | video | carousel
persona: 应届月薪30k算法工程师
topic: 记录今天的工作日常          # one line for the LLM (used if ANTHROPIC_API_KEY is set)
hook: 应届月薪30k算法工程师的一天   # big on-screen title / cover card (<=16 chars)
# title: 自定义标题               # optional (<=18 chars); omit to auto-generate
# tags: [程序员日常, 算法工程师, 应届生]
# voice: zh-CN-YunxiNeural        # optional voice override
# bgm: bgm.mp3                    # optional background music file in this folder
# visibility: 公开可见             # 公开可见 | 仅自己可见 | 仅互关好友可见

# --- Option B: hand-write narration (works with NO API key) ---
# script: |
#   早上九点到公司，先看一眼昨天模型的训练结果
#   数据没问题，开始今天的特征工程
#   中午和组里同事去吃了食堂新窗口
#   下午开了个算法评审，被怼了但学到不少
#   晚上八点收工，记录一下今天的成长

# --- Option C: explicit material -> narration mapping ---
# segments:
#   - {{material: clip1.mp4, text: 早上九点到公司}}
#   - {{material: photo1.jpg, text: 先看一眼训练结果}}
"""
    brief.write_text(template, encoding="utf-8")
    print(f"created: {brief}\nNow add your media files there and run: python run.py generate {date}")


def cmd_doctor(args, cfg):
    ok = True

    def line(status, msg):
        nonlocal ok
        if status == "FAIL":
            ok = False
        print(f"  [{status}] {msg}")

    print("environment check:")
    if ffmpeg_utils.supports_captions(cfg.ffmpeg):
        line("PASS", f"ffmpeg (with libass): {cfg.ffmpeg}")
    else:
        line("FAIL", f"ffmpeg lacks the 'ass' filter: {cfg.ffmpeg} "
                     "→ run `brew install ffmpeg-full`")
    line("PASS" if Path(cfg.ffprobe).exists() or shutil.which(cfg.ffprobe) else "WARN",
         f"ffprobe: {cfg.ffprobe}")
    try:
        import edge_tts  # noqa: F401
        line("PASS", "edge-tts importable")
    except ImportError:
        line("FAIL", "edge-tts missing → pip install -r requirements.txt")
    fpath = fonts.resolve_font_file(cfg.fonts_dir)
    line("PASS" if fpath else "WARN", f"CJK font for cards: {fpath or 'none found'}")
    line("PASS" if cfg.anthropic_key() else "WARN",
         "ANTHROPIC_API_KEY set (LLM script gen)" if cfg.anthropic_key()
         else "no ANTHROPIC_API_KEY — will use hand-written brief.script")

    client = XhsClient(cfg.get("publish.mcp_base_url", "http://localhost:18060"))
    if client.health():
        who = client.login_status()
        if who.get("is_logged_in"):
            line("PASS", f"xiaohongshu-mcp up & logged in as {who.get('username','?')}")
        else:
            line("WARN", "xiaohongshu-mcp up but NOT logged in → python run.py login")
    else:
        line("WARN", f"xiaohongshu-mcp not reachable at {client.base} "
                     "→ scripts/start_mcp.sh (only needed to publish)")
    print("\nOK" if ok else "\nThere are FAILs above; fix them before rendering.")


def cmd_generate(args, cfg):
    date = args.date or _today()
    print(f"rendering {date} ...")
    result = pipeline.render(cfg, date)
    print(f"\n✓ {result.kind} ready")
    print(f"  title : {result.title}")
    print(f"  body  : {result.body.splitlines()[0] if result.body else ''} ...")
    print(f"  tags  : {', '.join(result.tags)}")
    if result.video_path:
        print(f"  video : {result.video_path}")
    if result.images:
        print(f"  images: {len(result.images)} -> {result.images[0].parent}")
    print(f"\nPreview: python run.py preview {date}   Publish: python run.py publish {date}")
    if args.preview:
        _open(result.video_path if result.video_path else result.images[0])


def cmd_preview(args, cfg):
    date = args.date or _today()
    result = pipeline.load_manifest(cfg, date)
    print(f"=== {date} [{result.kind}] ===\n{result.title}\n\n{result.body}\n")
    print(f"tags: {', '.join(result.tags)}   visibility: {result.visibility}")
    _open(result.video_path if result.video_path else (result.images[0] if result.images else None))


def _confirm(prompt: str) -> bool:
    if not sys.stdin.isatty():
        return False
    try:
        return input(prompt).strip().lower() in ("y", "yes")
    except EOFError:
        return False


def _do_publish(cfg, date, *, auto: bool, yes: bool, schedule_at: str | None):
    if state.is_posted(cfg, date):
        print(f"{date} already marked posted (state/posted.json). Skipping.")
        return
    result = pipeline.load_manifest(cfg, date)
    mode = cfg.get("publish.mode", "review")
    go = auto or yes or mode == "auto"
    if not go:
        print(f"\n--- review {date} [{result.kind}] ---\n{result.title}\n\n{result.body}\n"
              f"tags: {', '.join(result.tags)} | visibility: {result.visibility}")
        if result.video_path:
            print(f"video: {result.video_path}")
        if result.images:
            print(f"images: {[str(p) for p in result.images]}")
        if not _confirm("\nPublish to Xiaohongshu now? [y/N] "):
            print("Not published. Re-run with --yes (or set publish.mode: auto) when ready.")
            return
    print("publishing ...")
    resp = pipeline.publish_post(cfg, date, schedule_at=schedule_at)
    print(f"✓ published {date}: {resp}")


def cmd_publish(args, cfg):
    _do_publish(cfg, args.date or _today(), auto=args.auto, yes=args.yes,
                schedule_at=args.schedule)


def cmd_run_daily(args, cfg):
    date = args.date or _today()
    if state.is_posted(cfg, date):
        print(f"{date} already posted. Nothing to do.")
        return
    pipeline.render(cfg, date)
    _do_publish(cfg, date, auto=args.auto, yes=args.auto, schedule_at=args.schedule)


def cmd_login(args, cfg):
    client = XhsClient(cfg.get("publish.mcp_base_url", "http://localhost:18060"))
    if not client.health():
        print(f"xiaohongshu-mcp not reachable at {client.base}. Start it: scripts/start_mcp.sh")
        return
    if client.is_logged_in():
        print(f"Already logged in as {client.login_status().get('username','?')}.")
        return
    qr = cfg.state_dir / "login_qr.png"
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    try:
        client.save_qrcode(qr)
        print(f"Saved login QR to {qr} — opening it; scan with the Xiaohongshu app.")
        _open(qr)
    except Exception as e:
        print(f"Could not fetch QR via API ({e}). Use the login binary: scripts/login.sh")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="run.py", description="auto_xhs pipeline")
    p.add_argument("--config", help="path to config.yaml")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init").set_defaults(func=cmd_init)
    sub.add_parser("doctor").set_defaults(func=cmd_doctor)
    sub.add_parser("login").set_defaults(func=cmd_login)

    sp = sub.add_parser("new"); sp.add_argument("date", nargs="?"); sp.set_defaults(func=cmd_new)

    sp = sub.add_parser("generate")
    sp.add_argument("date", nargs="?")
    sp.add_argument("--preview", action="store_true", help="open the result when done")
    sp.set_defaults(func=cmd_generate)

    sp = sub.add_parser("preview"); sp.add_argument("date", nargs="?"); sp.set_defaults(func=cmd_preview)

    for name in ("publish", "run-daily"):
        sp = sub.add_parser(name)
        sp.add_argument("date", nargs="?")
        sp.add_argument("--auto", action="store_true", help="publish without the review prompt")
        sp.add_argument("--yes", action="store_true", help="confirm publish (publish cmd)")
        sp.add_argument("--schedule", help="ISO8601 time for native scheduled publish")
        sp.set_defaults(func=cmd_publish if name == "publish" else cmd_run_daily)
    return p


def main():
    args = build_parser().parse_args()
    cfg = config_mod.load(args.config, root=ROOT)
    try:
        args.func(args, cfg)
    except PublishError as e:
        print(f"\n✗ publish error: {e}")
        sys.exit(1)
    except RuntimeError as e:
        print(f"\n✗ {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
