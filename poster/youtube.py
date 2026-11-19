"""YouTube Shorts upload (free YouTube Data API, ~6 uploads/day on the free quota)."""

from __future__ import annotations

import os

import requests

from .config import Config
from .http import TIMEOUT, UPLOAD_TIMEOUT, PostError, check
from .meta import Meta, youtube_fields

UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"


def post(cfg: Config, google_token: str, path: str, meta: Meta) -> dict:
    title, description, tags = youtube_fields(meta)
    size = os.path.getsize(path)
    body = {
        "snippet": {"title": title, "description": description, "tags": tags,
                    "categoryId": cfg.youtube_category},
        "status": {"privacyStatus": cfg.youtube_privacy, "selfDeclaredMadeForKids": False},
    }
    init = requests.post(
        UPLOAD_URL,
        params={"uploadType": "resumable", "part": "snippet,status"},
        headers={
            "Authorization": f"Bearer {google_token}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Type": "video/mp4",
            "X-Upload-Content-Length": str(size),
        },
        json=body,
        timeout=TIMEOUT,
    )
    location = check(init, "YouTube upload start").headers.get("Location")
    if not location:
        raise PostError("YouTube did not return an upload link")
    with open(path, "rb") as f:
        resp = requests.put(location, data=f, timeout=UPLOAD_TIMEOUT,
                            headers={"Content-Type": "video/mp4", "Content-Length": str(size)})
    video_id = check(resp, "YouTube upload").json()["id"]
    return {"id": video_id, "url": f"https://youtube.com/shorts/{video_id}"}
