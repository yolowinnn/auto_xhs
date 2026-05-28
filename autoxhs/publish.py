"""Client for the xiaohongshu-mcp REST API (github.com/xpzouying/xiaohongshu-mcp).

Endpoints used (default base http://localhost:18060):
  GET  /health
  GET  /api/v1/login/status      -> {is_logged_in, username}
  GET  /api/v1/login/qrcode      -> {timeout, is_logged_in, img}
  POST /api/v1/publish           -> image-text note  {title, content, images[], tags[], visibility, schedule_at}
  POST /api/v1/publish_video     -> video note       {title, content, video, tags[], visibility, schedule_at}
"""

from __future__ import annotations

import base64
from pathlib import Path

import requests

from .config import Config
from .models import RenderResult


class PublishError(RuntimeError):
    pass


class XhsClient:
    def __init__(self, base_url: str, timeout: int = 600):
        self.base = base_url.rstrip("/")
        self.timeout = timeout

    # --- low level --------------------------------------------------------
    def _get(self, path: str) -> dict:
        r = requests.get(self.base + path, timeout=30)
        return self._unwrap(r)

    def _post(self, path: str, payload: dict) -> dict:
        r = requests.post(self.base + path, json=payload, timeout=self.timeout)
        return self._unwrap(r)

    @staticmethod
    def _unwrap(r: requests.Response) -> dict:
        try:
            body = r.json()
        except ValueError:
            body = {"raw": r.text}
        if r.status_code >= 400 or (isinstance(body, dict) and body.get("success") is False):
            msg = body.get("message") or body.get("error") or r.text
            raise PublishError(f"{r.status_code} {r.request.method} {r.request.path_url}: {msg}")
        # respondSuccess wraps the payload under "data"
        return body.get("data", body) if isinstance(body, dict) else {"data": body}

    # --- health / login ---------------------------------------------------
    def health(self) -> bool:
        try:
            requests.get(self.base + "/health", timeout=5)
            return True
        except requests.RequestException:
            return False

    def login_status(self) -> dict:
        return self._get("/api/v1/login/status")

    def is_logged_in(self) -> bool:
        try:
            return bool(self.login_status().get("is_logged_in"))
        except (requests.RequestException, PublishError):
            return False

    def save_qrcode(self, out_path: Path) -> Path:
        data = self._get("/api/v1/login/qrcode")
        img = data.get("img", "")
        if "," in img and img.strip().startswith("data:"):
            img = img.split(",", 1)[1]
        out_path.write_bytes(base64.b64decode(img))
        return out_path

    # --- publishing -------------------------------------------------------
    def publish_images(self, *, title: str, content: str, images: list[str],
                       tags: list[str] | None = None, visibility: str | None = None,
                       schedule_at: str | None = None, is_original: bool = False) -> dict:
        payload = {"title": title, "content": content, "images": images,
                   "tags": tags or [], "is_original": is_original}
        if visibility:
            payload["visibility"] = visibility
        if schedule_at:
            payload["schedule_at"] = schedule_at
        return self._post("/api/v1/publish", payload)

    def publish_video(self, *, title: str, content: str, video: str,
                      tags: list[str] | None = None, visibility: str | None = None,
                      schedule_at: str | None = None) -> dict:
        payload = {"title": title, "content": content, "video": video,
                   "tags": tags or []}
        if visibility:
            payload["visibility"] = visibility
        if schedule_at:
            payload["schedule_at"] = schedule_at
        return self._post("/api/v1/publish_video", payload)


def _guard(cfg: Config, result: RenderResult) -> tuple[str, str]:
    title_max = cfg.get("publish.title_max", 20)
    content_max = cfg.get("publish.content_max", 1000)
    title = (result.title or "").strip()[:title_max]
    content = (result.body or "").strip()[:content_max]
    if not title:
        raise PublishError("empty title")
    return title, content


def publish(cfg: Config, result: RenderResult, *, schedule_at: str | None = None) -> dict:
    client = XhsClient(cfg.get("publish.mcp_base_url", "http://localhost:18060"),
                       timeout=cfg.get("publish.request_timeout_sec", 600))
    if not client.health():
        raise PublishError(
            "xiaohongshu-mcp server not reachable at "
            f"{client.base} — start it first (see scripts/start_mcp.sh)."
        )
    if not client.is_logged_in():
        raise PublishError("not logged in to Xiaohongshu — run scripts/login.sh and scan the QR.")

    title, content = _guard(cfg, result)
    visibility = result.visibility or cfg.get("publish.default_visibility", "公开可见")

    if result.kind == "video":
        if not result.video_path:
            raise PublishError("video result has no video_path")
        return client.publish_video(
            title=title, content=content, video=str(Path(result.video_path).resolve()),
            tags=result.tags, visibility=visibility, schedule_at=schedule_at,
        )
    images = [str(Path(p).resolve()) for p in result.images]
    if not images:
        raise PublishError("carousel result has no images")
    return client.publish_images(
        title=title, content=content, images=images,
        tags=result.tags, visibility=visibility, schedule_at=schedule_at,
    )
