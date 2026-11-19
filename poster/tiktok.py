"""TikTok upload (free Content Posting API).

mode "direct": posts straight to your profile. Until TikTok approves (audits)
your developer app, TikTok only allows private (SELF_ONLY) posts.
mode "inbox": sends the video as a draft to your TikTok app inbox - you tap
post on your phone. Works publicly without the audit."""

from __future__ import annotations

import os
import time

import requests

from .config import Config
from .http import TIMEOUT, UPLOAD_TIMEOUT, PostError, check
from .meta import Meta, tiktok_caption

API = "https://open.tiktokapis.com/v2"
MiB = 1024 * 1024
MAX_SINGLE = 64 * MiB
CHUNK = 10 * MiB
POLL_SECONDS = 10
POLL_LIMIT = 60


def refresh(cfg: Config, refresh_token: str) -> tuple[str, str]:
    """Returns (access_token, refresh_token). TikTok access tokens last 24h."""
    resp = requests.post(f"{API}/oauth/token/", timeout=TIMEOUT, data={
        "client_key": cfg.tiktok_client_key,
        "client_secret": cfg.tiktok_client_secret,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }, headers={"Content-Type": "application/x-www-form-urlencoded"})
    data = check(resp, "TikTok login").json()
    if "access_token" not in data:
        raise PostError(f"TikTok login failed: {data}")
    return data["access_token"], data.get("refresh_token") or refresh_token


def chunk_plan(size: int) -> tuple[int, int]:
    """(chunk_size, total_chunk_count). Small videos go up in one piece;
    bigger ones in 10 MB pieces, the last piece takes the remainder."""
    if size <= 0:
        raise PostError("video file is empty")
    if size <= MAX_SINGLE:
        return size, 1
    return CHUNK, size // CHUNK


def _json(resp: requests.Response, what: str) -> dict:
    data = check(resp, what).json()
    err = data.get("error") or {}
    if err.get("code") not in (None, "ok"):
        raise PostError(f"{what} failed: {err.get('code')} - {err.get('message')}")
    return data.get("data") or {}


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"}


def creator_info(token: str) -> dict:
    return _json(requests.post(f"{API}/post/publish/creator_info/query/", headers=_h(token), timeout=TIMEOUT),
                 "TikTok creator info")


def pick_privacy(wanted: str, options: list[str]) -> str:
    if wanted in options:
        return wanted
    if "SELF_ONLY" in options:
        return "SELF_ONLY"
    if options:
        return options[0]
    return "SELF_ONLY"


def _upload_chunks(upload_url: str, path: str, size: int, chunk_size: int, count: int) -> None:
    with open(path, "rb") as f:
        for i in range(count):
            start = i * chunk_size
            end = size - 1 if i == count - 1 else start + chunk_size - 1
            f.seek(start)
            data = f.read(end - start + 1)
            resp = requests.put(upload_url, data=data, timeout=UPLOAD_TIMEOUT, headers={
                "Content-Type": "video/mp4",
                "Content-Length": str(len(data)),
                "Content-Range": f"bytes {start}-{end}/{size}",
            })
            check(resp, f"TikTok upload part {i + 1}/{count}")


def post(cfg: Config, token: str, path: str, meta: Meta, sleep=time.sleep) -> dict:
    size = os.path.getsize(path)
    chunk_size, count = chunk_plan(size)
    source = {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk_size, "total_chunk_count": count}

    if cfg.tiktok_mode == "inbox":
        data = _json(requests.post(f"{API}/post/publish/inbox/video/init/", headers=_h(token), timeout=TIMEOUT,
                                   json={"source_info": source}), "TikTok inbox start")
        privacy = "draft"
    else:
        info = creator_info(token)
        privacy = pick_privacy(cfg.tiktok_privacy, info.get("privacy_level_options") or [])
        post_info = {
            "title": tiktok_caption(meta),
            "privacy_level": privacy,
            "disable_duet": False,
            "disable_comment": False,
            "disable_stitch": False,
            "video_cover_timestamp_ms": 1000,
        }
        data = _json(requests.post(f"{API}/post/publish/video/init/", headers=_h(token), timeout=TIMEOUT,
                                   json={"post_info": post_info, "source_info": source}), "TikTok post start")

    publish_id, upload_url = data["publish_id"], data["upload_url"]
    _upload_chunks(upload_url, path, size, chunk_size, count)

    status = "PROCESSING_UPLOAD"
    result: dict = {}
    for _ in range(POLL_LIMIT):
        result = _json(requests.post(f"{API}/post/publish/status/fetch/", headers=_h(token), timeout=TIMEOUT,
                                     json={"publish_id": publish_id}), "TikTok status")
        status = result.get("status", "")
        if status == "FAILED":
            raise PostError(f"TikTok rejected the video: {result.get('fail_reason')}")
        if status in ("PUBLISH_COMPLETE", "SEND_TO_USER_INBOX"):
            break
        sleep(POLL_SECONDS)

    ids = result.get("publicaly_available_post_id") or []
    return {"id": publish_id, "status": status, "privacy": privacy,
            "url": f"https://www.tiktok.com/video/{ids[0]}" if ids else ""}
