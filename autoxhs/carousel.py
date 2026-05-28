"""Image-text (图文) post path: normalize images to a Xiaohongshu-friendly ratio
and optionally render a title cover card as the first image."""

from __future__ import annotations

import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import fonts
from .config import Config
from .models import Material, Script

try:  # optional: lets us read iPhone .heic photos
    import pillow_heif
    pillow_heif.register_heif_opener()
except Exception:
    pass


def _open_rgb(path: Path) -> Image.Image | None:
    try:
        return Image.open(path).convert("RGB")
    except Exception as e:
        print(f"[carousel] skip unreadable image {path.name}: {e}")
        return None


def _fit_cover(img: Image.Image, w: int, h: int) -> Image.Image:
    src_ratio, dst_ratio = img.width / img.height, w / h
    if src_ratio > dst_ratio:
        new_w = int(img.height * dst_ratio)
        left = (img.width - new_w) // 2
        img = img.crop((left, 0, left + new_w, img.height))
    else:
        new_h = int(img.width / dst_ratio)
        top = (img.height - new_h) // 2
        img = img.crop((0, top, img.width, top + new_h))
    return img.resize((w, h), Image.LANCZOS)


def _fit_contain(img: Image.Image, w: int, h: int, pad_color: str) -> Image.Image:
    canvas = Image.new("RGB", (w, h), pad_color)
    img = img.copy()
    img.thumbnail((w, h), Image.LANCZOS)
    canvas.paste(img, ((w - img.width) // 2, (h - img.height) // 2))
    return canvas


def _process_image(cfg: Config, src: Path, dst: Path) -> Path | None:
    img = _open_rgb(src)
    if img is None:
        return None
    w = cfg.get("carousel.width", 1080)
    h = cfg.get("carousel.height", 1440)
    fit = cfg.get("carousel.fit", "cover")
    out = (_fit_cover(img, w, h) if fit == "cover"
           else _fit_contain(img, w, h, cfg.get("carousel.pad_color", "white")))
    dst.parent.mkdir(parents=True, exist_ok=True)
    out.save(dst, "JPEG", quality=92)
    return dst


def _load_font(fonts_dir: Path, size: int) -> ImageFont.FreeTypeFont:
    fpath = fonts.resolve_font_file(fonts_dir)
    if fpath:
        try:
            return ImageFont.truetype(fpath, size)
        except Exception:
            pass
    return ImageFont.load_default()


def _title_card(cfg: Config, title: str, bg_src: Path | None, dst: Path) -> Path:
    w = cfg.get("carousel.width", 1080)
    h = cfg.get("carousel.height", 1440)
    if bg_src and bg_src.exists():
        bg = _open_rgb(bg_src)
        canvas = _fit_cover(bg, w, h).filter(ImageFilter.GaussianBlur(18)) if bg \
            else Image.new("RGB", (w, h), "#1a1a1a")
        dark = Image.new("RGB", (w, h), "#000000")
        canvas = Image.blend(canvas, dark, 0.45)
    else:
        canvas = Image.new("RGB", (w, h), "#1a1a1a")

    draw = ImageDraw.Draw(canvas)
    font = _load_font(cfg.fonts_dir, size=int(w * 0.11))
    lines = textwrap.wrap(title, width=9) or [title]
    line_h = int(w * 0.11 * 1.3)
    total_h = line_h * len(lines)
    y = (h - total_h) // 2
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        tw = bbox[2] - bbox[0]
        draw.text(((w - tw) // 2, y), line, font=font, fill="white",
                  stroke_width=max(3, w // 240), stroke_fill="#000000")
        y += line_h
    dst.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(dst, "JPEG", quality=92)
    return dst


def build_carousel(cfg: Config, script: Script, materials: list[Material],
                   work_dir: Path) -> list[Path]:
    work_dir.mkdir(parents=True, exist_ok=True)
    images = [m for m in materials if m.kind == "image"]
    max_images = cfg.get("carousel.max_images", 9)

    out_paths: list[Path] = []
    if cfg.get("carousel.add_title_card", True) and script.hook_title.strip():
        first_bg = images[0].path if images else None
        out_paths.append(_title_card(cfg, script.hook_title.strip(), first_bg,
                                     work_dir / "card_00_title.jpg"))

    for i, m in enumerate(images):
        if len(out_paths) >= max_images:
            break
        dst = _process_image(cfg, m.path, work_dir / f"img_{i:02d}.jpg")
        if dst:
            out_paths.append(dst)
    return out_paths
