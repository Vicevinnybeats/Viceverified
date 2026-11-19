"""Scout finds -> finished vertical Shorts (+ caption file) -> Drive Inbox (or out/ folder)."""

from __future__ import annotations

import json
import os
import random
import re
import shutil
import tempfile
from datetime import datetime, timezone

from . import render, sources, subs, voice
from .config import Config
from .scout import Scout

VIDEO_EXT = (".mp4", ".mov", ".m4v", ".webm", ".mkv")


def slug(text: str, n: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:n].rstrip("-") or "short"


def pick(items: list[dict], cfg: Config) -> tuple[list[dict], list[dict]]:
    news = [i for i in items if i.get("kind") != "clip" and i.get("score", 0) >= cfg.min_news_score]
    news.sort(key=lambda i: (i.get("new_info", 0), i.get("score", 0)), reverse=True)
    clips = [i for i in items if i.get("kind") == "clip" and i.get("score", 0) >= cfg.min_clip_score]
    if cfg.clip_streamers:
        clips = [c for c in clips if (c.get("author") or "").lower() in cfg.clip_streamers]
    clips.sort(key=lambda i: (i.get("score", 0), i.get("metric", 0)), reverse=True)
    return news[: cfg.news_per_run], clips[: cfg.clips_per_run]


def sidecar(script: dict, item: dict) -> dict:
    credit = (f"Clip by {item.get('author')} - full credit to the streamer: {item.get('url')}"
              if item.get("kind") == "clip" else f"Source: {item.get('author')} - {item.get('url')}")
    return {
        "title": script.get("title") or item.get("title"),
        "youtube_title": script.get("title") or item.get("title"),
        "caption": script.get("caption", ""),
        "description": f"{script.get('caption', '')}\n\n{credit}".strip(),
        "hashtags": script.get("hashtags") or ["#gta6", "#gta", "#gaming", "#shorts"],
        "scout_id": item.get("id"),
    }


class Outbox:
    """Finished Shorts go to Google Drive Viceverified/Inbox (Poster picks them up) and to out/."""

    def __init__(self, cfg: Config, log=print):
        self.cfg, self.log = cfg, log
        os.makedirs(cfg.out_dir, exist_ok=True)
        self.drive = None
        self.inbox = self.broll_folder = None
        try:
            from poster.config import Config as PosterConfig
            from poster.google import Drive, access_token

            pc = PosterConfig.from_env()
            if pc.has_google:
                self.drive = Drive(access_token(pc))
                root = self.drive.ensure_folder(pc.drive_root_folder)
                self.inbox = self.drive.ensure_folder("Inbox", root)
                self.broll_folder = self.drive.ensure_folder("Broll", root)
        except Exception as exc:
            self.log(f"Google Drive not used ({exc}) - Shorts are saved to the GitHub run only.")
            self.drive = None

    def broll(self, folder: str) -> str | None:
        """A random gameplay video you dropped in Drive Viceverified/Broll (optional)."""
        if not self.drive:
            return None
        vids = [f for f in self.drive.list_children(self.broll_folder) if f["name"].lower().endswith(VIDEO_EXT)]
        if not vids:
            return None
        pick = random.choice(vids)
        return self.drive.download(pick["id"], os.path.join(folder, "broll" + os.path.splitext(pick["name"])[1]))

    def deliver(self, video: str, meta: dict, name: str) -> str:
        local = os.path.join(self.cfg.out_dir, f"{name}.mp4")
        shutil.copy(video, local)
        with open(os.path.join(self.cfg.out_dir, f"{name}.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)
        if self.drive:
            # caption file first, so the Poster never sees the video without it
            self.drive.write_text(f"{name}.json", self.inbox, json.dumps(meta, indent=2, ensure_ascii=False))
            self.drive.upload_file(local, self.inbox)  # same name as the caption file
            return "Drive Inbox"
        return "GitHub run files"


def _words(scout: Scout, audio: str, text: str, length: float, log) -> list[dict]:
    try:
        words = scout.transcribe(audio).get("words") or []
        if len(words) >= 3:
            return words
    except Exception as exc:
        log(f"  captions: Whisper failed ({exc}), using even timing")
    return subs.even_timing(text, length)


def make_news(cfg: Config, scout: Scout, outbox: Outbox, item: dict, log=print) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        facts, image_url = sources.fetch_article(item["url"])
        script = scout.write({"kind": "news", "title": item["title"], "author": item.get("author"),
                              "angle": item.get("angle"), "facts": facts or item["title"]})
        if not script.get("safe", True):
            scout.mark(item["id"], "skip")
            return {"status": "skipped (not safe for Shorts)"}
        text = script.get("voiceover") or item["title"]
        voice_path, used_voice = voice.speak(cfg, scout, text, os.path.join(tmp, "voice.mp3"), log)
        length = render.duration(voice_path)
        words = _words(scout, render.small_audio(voice_path, os.path.join(tmp, "small.mp3")), text, length, log)
        ass = os.path.join(tmp, "subs.ass")
        with open(ass, "w", encoding="utf-8") as f:
            f.write(subs.build_ass(min(length + 0.6, render.MAX_SECONDS), words, hook=script.get("hook", ""),
                                   credit=f"Source: {item.get('author') or 'news'}", banner="GTA 6 NEWS"))
        image = None
        if cfg.use_article_image and image_url:
            image = sources.download(image_url, os.path.join(tmp, "picture"))
        broll = outbox.broll(tmp)
        out = render.news_short(os.path.join(tmp, "short.mp4"), voice_path, ass, image=image, broll=broll,
                                fonts_dir=cfg.fonts_dir)
        name = f"{datetime.now(timezone.utc):%Y%m%d}-news-{slug(script.get('title') or item['title'])}"
        where = outbox.deliver(out, sidecar(script, item), name)
        scout.mark(item["id"], "used")
        return {"status": "made", "file": name, "where": where, "voice": used_voice, "hook": script.get("hook")}


def make_clip(cfg: Config, scout: Scout, outbox: Outbox, item: dict, log=print) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        clip = sources.twitch_clip(item["url"], tmp)
        transcript, words = "", []
        if render.has_audio(clip):
            try:
                t = scout.transcribe(render.small_audio(clip, os.path.join(tmp, "small.mp3")))
                transcript, words = t.get("text", ""), t.get("words") or []
            except Exception as exc:
                log(f"  captions: Whisper failed ({exc}) - clip without captions")
        script = scout.write({"kind": "clip", "title": item["title"], "author": item.get("author"),
                              "metric": item.get("metric"), "transcript": transcript})
        if not script.get("safe", True):
            scout.mark(item["id"], "skip")
            return {"status": "skipped (not safe for Shorts)"}
        ass = os.path.join(tmp, "subs.ass")
        with open(ass, "w", encoding="utf-8") as f:
            f.write(subs.build_ass(min(render.duration(clip), render.MAX_SECONDS), words,
                                   hook=script.get("hook", ""), credit=f"twitch.tv/{item.get('author', '')}"))
        out = render.clip_short(os.path.join(tmp, "short.mp4"), clip, ass, fonts_dir=cfg.fonts_dir)
        name = f"{datetime.now(timezone.utc):%Y%m%d}-clip-{slug(item.get('author', '') + '-' + item['title'])}"
        where = outbox.deliver(out, sidecar(script, item), name)
        scout.mark(item["id"], "used")
        return {"status": "made", "file": name, "where": where, "hook": script.get("hook")}


def run(cfg: Config, log=print, dry_run: bool = False) -> list[dict]:
    scout = Scout(cfg)
    news, clips = pick(scout.items(), cfg)
    log(f"Picked {len(news)} news + {len(clips)} clips from the Scout.")
    if cfg.voicestudio_url:
        log("VoiceStudio: " + ("ready" if voice.voicestudio_ready(cfg, wait_seconds=10) else
                               "NOT reachable - the backup voice will be used"))
    if dry_run:
        for i in news + clips:
            log(f"  would make: [{i['kind']}] {i['score']} {i['title']}")
        return []
    outbox = Outbox(cfg, log)
    results = []
    for kind, items, maker in (("news", news, make_news), ("clip", clips, make_clip)):
        for item in items:
            log(f"\n▶ {kind}: {item['title']}")
            try:
                res = maker(cfg, scout, outbox, item, log)
            except Exception as exc:
                res = {"status": f"failed: {str(exc)[:400]}"}
            res.update({"kind": kind, "title": item["title"], "url": item["url"]})
            log(f"  → {res['status']}" + (f" ({res.get('where')}, voice: {res.get('voice', '-')})" if res.get("where") else ""))
            results.append(res)
    return results
