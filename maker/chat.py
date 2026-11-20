"""Twitch chat for a VOD time range (read directly from Twitch, no extra program) and chat-spike scoring.

Spike = a 10-second window where >= 3x the usual number of different chatters wrote (people, not messages).
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
# Twitch's own saved query for VOD chat. Twitch can change this hash; then chat fails and loudness is used instead.
COMMENTS_HASH = "b70a3591ff0f4e0313d126c6a1502d79a1c02baebb288227c582044aa76adf6a"


def find_cli() -> bool:
    """Chat is read with our own code (no extra program needed)."""
    return True


def _page(vod_id: str, offset: int, session=None) -> list[dict]:
    import time

    import requests

    q = [{"operationName": "VideoCommentsByOffsetOrCursor",
          "variables": {"videoID": str(vod_id), "contentOffsetSeconds": int(offset)},
          "extensions": {"persistedQuery": {"version": 1, "sha256Hash": COMMENTS_HASH}}}]
    post = (session or requests).post
    for attempt in range(4):
        try:
            r = post(GQL, json=q, headers={"Client-Id": WEB_CLIENT_ID}, timeout=30)
            r.raise_for_status()
            body = r.json()
            body = body[0] if isinstance(body, list) else body
            if body.get("errors"):
                raise RuntimeError(f"Twitch chat: {body['errors'][0].get('message', body['errors'])}")
            comments = ((body.get("data") or {}).get("video") or {}).get("comments") or {}
            return comments.get("edges") or []
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)
    return []


def download_chat(vod_id: str, start: int, end: int, dest: str | None = None, max_pages: int = 4000,
                  page=None) -> list[dict]:
    """[{t: seconds into the VOD, user, text}] for start..end, straight from Twitch.
    Paged by time offset (each reply is ~30 s of chat), not by cursor: the cursor path needs an
    'integrity' token Twitch refuses to scripts. Idea from gta6-clipper (MIT)."""
    import time

    page = page or _page
    out, seen, off, pages = [], set(), int(start), 0
    while off < end and pages < max_pages:
        edges = page(vod_id, off)
        pages += 1
        new, last = 0, off
        for e in edges:
            n = e.get("node") or {}
            t = float(n.get("contentOffsetSeconds") or 0)
            last = max(last, int(t))
            key = n.get("id") or (t, (n.get("commenter") or {}).get("displayName"), str(n.get("message")))
            if key in seen or not start <= t <= end:
                continue
            seen.add(key)
            new += 1
            text = "".join(f.get("text") or "" for f in (n.get("message") or {}).get("fragments") or [])
            c = n.get("commenter") or {}
            out.append({"t": t, "user": c.get("login") or c.get("displayName") or "", "text": text.strip()})
        if not edges:
            break
        off = last if new and last > off else off + 1  # a page all in one second repeats: step 1 s on
        if page is _page:
            time.sleep(0.15)
    if dest:
        with open(dest, "w", encoding="utf-8") as f:
            json.dump(out, f)
    return sorted(out, key=lambda m: m["t"])


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
    rows = [{"t": start + i * BUCKET, "msgs": 0, "hype": 0, "people": 0} for i in range(n)]
    users: list[set] = [set() for _ in range(n)]
    for m in messages:
        i = int((m["t"] - start) // BUCKET)
        if 0 <= i < n:
            rows[i]["msgs"] += 1
            rows[i]["hype"] += hype_count(m["text"])
            users[i].add((m.get("user") or "").lower() or f"anon{rows[i]['msgs']}")
    for r, u in zip(rows, users):
        r["people"] = len(u)
    return rows


def spikes(rows: list[dict], factor: float = 3.0, top: int = 5, gap: int = 90,
           min_people: int = 5) -> tuple[list[dict], float]:
    """Windows where >= factor x the median number of DIFFERENT chatters spoke, best first, `gap` s apart.
    Counting people, not messages: one spammer or bot cannot fake a hype moment."""
    who = lambda r: r.get("people", r["msgs"])  # noqa: E731
    counts = [who(r) for r in rows if who(r) > 0]
    median = statistics.median(counts) if counts else 0.0
    found = []
    for r in rows:
        ratio = who(r) / median if median else 0.0
        if median and ratio >= factor and who(r) >= min_people:
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
