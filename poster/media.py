"""A temporary public link to a video, for Instagram to download.

Uses your Scout Worker (Cloudflare Workers KV - free, no credit card). If you ever set up
Cloudflare R2 instead (R2_* settings), that is used."""

from __future__ import annotations

import os
import uuid

import requests

from . import r2
from .config import Config
from .http import UPLOAD_TIMEOUT, check


def upload(cfg: Config, path: str) -> tuple[str, str]:
    """Returns (handle for delete(), public url)."""
    if cfg.has_r2:
        key, url = r2.upload(cfg, path)
        return f"r2:{key}", url
    name = f"{uuid.uuid4().hex}{os.path.splitext(path)[1].lower() or '.mp4'}"
    with open(path, "rb") as f:
        resp = requests.put(f"{cfg.scout_url}/api/media/{name}", data=f.read(), timeout=UPLOAD_TIMEOUT,
                            headers={"Authorization": f"Bearer {cfg.scout_key}", "Content-Type": "video/mp4"})
    return f"scout:{name}", check(resp, "Scout media upload").json()["url"]


def delete(cfg: Config, handle: str) -> None:
    try:
        kind, ref = handle.split(":", 1)
        if kind == "r2":
            r2.delete(cfg, ref)
        else:
            requests.delete(f"{cfg.scout_url}/api/media/{ref}", timeout=30,
                            headers={"Authorization": f"Bearer {cfg.scout_key}"})
    except Exception as exc:  # the link expires by itself after 2 days anyway
        print(f"  (could not remove temporary video link: {exc})")
