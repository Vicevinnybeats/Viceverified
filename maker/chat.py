"""Twitch chat for a VOD time range (read directly from Twitch, no extra program) and chat-spike scoring.

Spike = a 10-second window with >= 3x the stream's median messages per 10 s.
Hype words (KEKW, LUL, W, NO WAY, CLIP IT, 💀 ...) add to the score."""

from __future__ import annotations

import json
import re
import statistics

HYPE = ["KEKW", "LUL", "LULW", "OMEGALUL", "LMAO", "LMFAO", "NO WAY", "NOWAY", "CLIP IT", "CLIP THAT", "CLIPPED",
        "💀", "😂", "POGGERS", "POG", "PogU", "WTF", "HOLY", "INSANE", "W", "L", "AINTNOWAY", "ICANT", "OMEGADANCE"]
_HYPE_RE = re.compile(r"(?<![A-Za-z])(" + "|".join(re.escape(h) for h in sorted(HYPE, key=len, reverse=True)) + r")(?![A-Za-z])",
                      re.IGNORECASE)
BUCKET = 10


GQL = "https://gql.twitch.tv/gql"
WEB_CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"  # Twitch's public web-player id (what twitch.tv itself uses)
COMMENTS_QUERY = """query($videoID: ID!, $offset: Int, $cursor: Cursor) {
  video(id: $videoID) { comments(contentOffsetSeconds: $offset, after: $cursor) {
    edges { cursor node { contentOffsetSeconds commenter { displayName } message { fragments { text } } } }
    pageInfo { hasNextPage } } } }"""


def find_cli() -> bool:
    """Chat is read with our own code (no extra program needed)."""
    return True


def download_chat(vod_id: str, start: int, end: int, dest: str | None = None, max_pages: int = 4000) -> list[dict]:
    """[{t: seconds into the VOD, user, text}] for start..end (seconds), straight from Twitch."""
    import requests

    out, cursor, pages = [], None, 0
    while pages < max_pages:
        variables = {"videoID": str(vod_id)}
        if cursor:
            variables["cursor"] = cursor
        else:
            variables["offset"] = int(start)
        r = requests.post(GQL, json={"query": COMMENTS_QUERY, "variables": variables},
                          headers={"Client-Id": WEB_CLIENT_ID}, timeout=30)
        r.raise_for_status()
        body = r.json()
        if body.get("errors"):
            raise RuntimeError(f"Twitch chat: {body['errors'][0].get('message', body['errors'])}")
        comments = ((body.get("data") or {}).get("video") or {}).get("comments")
        if not comments:
            break
        edges = comments.get("edges") or []
        for e in edges:
            n = e["node"]
            t = float(n.get("contentOffsetSeconds") or 0)
            if t > end:
                pages = max_pages
                break
            text = "".join(f.get("text") or "" for f in (n.get("message") or {}).get("fragments") or [])
            out.append({"t": t, "user": (n.get("commenter") or {}).get("displayName") or "", "text": text.strip()})
        pages += 1
        if not edges or not comments.get("pageInfo", {}).get("hasNextPage"):
            break
        cursor = edges[-1].get("cursor")
        if not cursor:
            break
    if dest:
        with open(dest, "w", encoding="utf-8") as f:
            json.dump(out, f)
    return sorted((m for m in out if start <= m["t"] <= end), key=lambda m: m["t"])


def parse_chat(data: dict) -> list[dict]:
    out = []
    for c in data.get("comments", []):
        msg = c.get("message") or {}
        text = msg.get("body") or "".join(f.get("text", "") for f in msg.get("fragments") or [])
        user = (c.get("commenter") or {}).get("display_name") or ""
        out.append({"t": float(c.get("content_offset_seconds", 0)), "user": user, "text": text.strip()})
    return sorted(out, key=lambda m: m["t"])


def hype_count(text: str) -> int:
    return len(_HYPE_RE.findall(text or ""))


def buckets(messages: list[dict], start: int, end: int) -> list[dict]:
    """Per 10 s: messages, hype words."""
    n = max(1, (end - start + BUCKET - 1) // BUCKET)
    rows = [{"t": start + i * BUCKET, "msgs": 0, "hype": 0} for i in range(n)]
    for m in messages:
        i = int((m["t"] - start) // BUCKET)
        if 0 <= i < n:
            rows[i]["msgs"] += 1
            rows[i]["hype"] += hype_count(m["text"])
    return rows


def spikes(rows: list[dict], factor: float = 3.0, top: int = 5, gap: int = 90) -> tuple[list[dict], float]:
    """Windows with >= factor x median chat speed, best first, at least `gap` s apart."""
    counts = [r["msgs"] for r in rows if r["msgs"] > 0]
    median = statistics.median(counts) if counts else 0.0
    found = []
    for r in rows:
        ratio = r["msgs"] / median if median else 0.0
        if median and ratio >= factor:
            score = ratio + 0.5 * (r["hype"] / max(1, r["msgs"])) * 10
            found.append({**r, "ratio": round(ratio, 2), "chat_score": round(score, 2)})
    found.sort(key=lambda r: r["chat_score"], reverse=True)
    picked: list[dict] = []
    for r in found:
        if all(abs(r["t"] - p["t"]) >= gap for p in picked):
            picked.append(r)
        if len(picked) >= top:
            break
    return picked, median


def per_minute(messages: list[dict], start: int, end: int) -> list[int]:
    n = max(1, (end - start + 59) // 60)
    out = [0] * n
    for m in messages:
        i = int((m["t"] - start) // 60)
        if 0 <= i < n:
            out[i] += 1
    return out


def popups(messages: list[dict], peak: float, before: float = 1.0, after: float = 6.0, limit: int = 5) -> list[dict]:
    """Short, readable chat messages right at the peak - for the on-screen chat pop-ups."""
    near = [m for m in messages if peak - before <= m["t"] <= peak + after and 1 <= len(m["text"]) <= 40]
    near.sort(key=lambda m: (-hype_count(m["text"]), m["t"]))
    chosen = sorted(near[:limit], key=lambda m: m["t"])
    return chosen
