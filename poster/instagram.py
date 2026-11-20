"""Instagram Reels upload (free Instagram API, Business/Creator account).

Instagram downloads the video from a public link, so the file is parked on your
Scout Worker (Workers KV, free) for a few minutes and deleted right after posting."""

from __future__ import annotations

import time

import requests

from . import media
from .config import Config
from .http import TIMEOUT, PostError, check
from .meta import Meta, instagram_caption

POLL_SECONDS = 10
POLL_LIMIT = 90  # 15 minutes


def _base(cfg: Config) -> str:
    return f"https://{cfg.ig_graph_host}/{cfg.ig_api_version}"


def post(cfg: Config, token: str, path: str, meta: Meta, sleep=time.sleep) -> dict:
    handle, public_url = media.upload(cfg, path)
    try:
        base = _base(cfg)
        resp = requests.post(f"{base}/{cfg.ig_user_id}/media", timeout=TIMEOUT, data={
            "media_type": "REELS",
            "video_url": public_url,
            "caption": instagram_caption(meta),
            "share_to_feed": "true",
            "access_token": token,
        })
        container = check(resp, "Instagram create reel").json()["id"]

        for _ in range(POLL_LIMIT):
            st = requests.get(f"{base}/{container}", timeout=TIMEOUT,
                              params={"fields": "status_code,status", "access_token": token})
            data = check(st, "Instagram status").json()
            code = data.get("status_code")
            if code == "FINISHED":
                break
            if code in ("ERROR", "EXPIRED"):
                raise PostError(f"Instagram could not process the video: {data.get('status')}")
            sleep(POLL_SECONDS)
        else:
            raise PostError("Instagram took too long to process the video")

        pub = requests.post(f"{base}/{cfg.ig_user_id}/media_publish", timeout=TIMEOUT,
                            data={"creation_id": container, "access_token": token})
        media_id = check(pub, "Instagram publish").json()["id"]
        url = ""
        try:
            link = requests.get(f"{base}/{media_id}", timeout=TIMEOUT,
                                params={"fields": "permalink", "access_token": token})
            url = link.json().get("permalink", "") if link.ok else ""
        except requests.RequestException:
            pass
        return {"id": media_id, "url": url}
    finally:
        media.delete(cfg, handle)


def refresh_token(cfg: Config, token: str) -> str:
    """Instagram tokens last 60 days; refreshing gives a fresh 60 days."""
    if cfg.ig_graph_host != "graph.instagram.com":
        return token  # Facebook-login page tokens don't use this endpoint
    resp = requests.get("https://graph.instagram.com/refresh_access_token", timeout=TIMEOUT,
                        params={"grant_type": "ig_refresh_token", "access_token": token})
    return check(resp, "Instagram token refresh").json()["access_token"]
