"""Gets the raw material: article text + picture for news, the video file for Twitch clips."""

from __future__ import annotations

import glob
import html
import os
import re
import subprocess

import requests

UA = {"User-Agent": "Mozilla/5.0 (compatible; ViceverifiedMaker/1.0)"}


def _meta(page: str, prop: str) -> str:
    for pattern in (
        rf'<meta[^>]+(?:property|name)=["\']{prop}["\'][^>]+content=["\']([^"\']+)["\']',
        rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']{prop}["\']',
    ):
        m = re.search(pattern, page, re.I)
        if m:
            return html.unescape(m.group(1)).strip()
    return ""


def article_facts(page: str, limit: int = 3500) -> tuple[str, str]:
    """(text for Qwen, picture url) from an article's HTML."""
    image = _meta(page, "og:image") or _meta(page, "twitter:image")
    desc = _meta(page, "og:description") or _meta(page, "description")
    body = re.sub(r"(?is)<(script|style|nav|header|footer|aside|figure)[^>]*>.*?</\1>", " ", page)
    paras = []
    for p in re.findall(r"(?is)<p[^>]*>(.*?)</p>", body):
        text = html.unescape(re.sub(r"<[^>]+>", "", p))
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > 60 and "cookie" not in text.lower() and "newsletter" not in text.lower():
            paras.append(text)
    facts = " ".join([desc] + paras).strip()
    return facts[:limit], image


def fetch_article(url: str) -> tuple[str, str]:
    try:
        r = requests.get(url, headers=UA, timeout=30, allow_redirects=True)
        r.raise_for_status()
        return article_facts(r.text)
    except requests.RequestException:
        return "", ""


def download(url: str, dest: str, max_bytes: int = 15_000_000) -> str | None:
    try:
        with requests.get(url, headers=UA, timeout=60, stream=True) as r:
            r.raise_for_status()
            size = 0
            with open(dest, "wb") as f:
                for chunk in r.iter_content(65536):
                    size += len(chunk)
                    if size > max_bytes:
                        return None
                    f.write(chunk)
        return dest
    except requests.RequestException:
        return None


def twitch_clip(url: str, folder: str) -> str:
    """Downloads a Twitch clip with yt-dlp (free, open source)."""
    template = os.path.join(folder, "clip.%(ext)s")
    proc = subprocess.run(["yt-dlp", "-q", "--no-warnings", "-f", "best[ext=mp4]/best", "-o", template, url],
                          capture_output=True, text=True, timeout=300)
    files = glob.glob(os.path.join(folder, "clip.*"))
    if proc.returncode != 0 or not files:
        raise RuntimeError(f"could not download clip: {proc.stderr[-300:]}")
    return files[0]
