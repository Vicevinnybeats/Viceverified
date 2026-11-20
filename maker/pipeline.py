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
    guide = lambda i: 1 if (i.get("category") or "") in ("guide", "secret", "tips") else 0  # noqa: E731
    # useful guides may score a bit lower than headline news and still be picked
    news = [i for i in items if i.get("kind") != "clip"
            and i.get("score", 0) >= (cfg.min_news_score - 20 if guide(i) else cfg.min_news_score)]
    news.sort(key=lambda i: (guide(i), i.get("score", 0), i.get("new_info", 0)), reverse=True)
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
    """Finished Shorts go to out/ (the Poster posts them right after rendering) and, if Google is
    connected, a copy goes to Drive Viceverified/Made as an archive."""

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
                self.inbox = self.drive.ensure_folder("Made", root)
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
            return "out/ + Drive Made"
        return "GitHub run files"


def _words(scout: Scout, audio: str, text: str, length: float, log) -> list[dict]:
    """Word timings: faster-whisper on this machine first (free), then the Scout's Whisper."""
    from . import highlights

    words = highlights.transcribe(scout, audio, log)[0].get("words") or []
    if len(words) >= 3:
        return words
    log("  captions: no word timings, using even timing")
    return subs.even_timing(text, length)


TIP_WORDS = ("where", "how", "find", "head", "go to", "drive", "unlock", "earn", "money", "cash", "reward",
             "secret", "hidden", "mission", "location", "map", "near", "north", "south", "east", "west", "spawn",
             "you can", "you'll", "make sure", "best", "tip")


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", text or ""))
    return [p.strip() for p in parts if 40 <= len(p.strip()) <= 220]


def extract_script(item: dict, facts: str) -> dict:
    """No AI needed: the most useful sentences from the article, as a numbered tip script."""
    sents = _sentences(facts)
    scored = sorted(sents, key=lambda s_: -sum(w in s_.lower() for w in TIP_WORDS))
    best = [s_ for s_ in scored if sum(w in s_.lower() for w in TIP_WORDS) > 0][:3] or sents[:3]
    best = sorted(best, key=sents.index)  # keep the article's order
    title = re.sub(r"\s+[-|].*$", "", item["title"]).strip()
    words = {1: "One", 2: "Two", 3: "Three"}
    body = " ".join(f"{words[n]}. {s_}" for n, s_ in enumerate(best, 1))
    source = item.get("author") or "the article"
    voice = f"{title}. Here is what you need to know, from {source}. {body} Follow for more GTA 6 secrets."
    hook = title
    if len(hook) > 48:  # short hook, cut at a word
        hook = hook[:48].rsplit(" ", 1)[0].rstrip(",:;-")
    return {"hook": hook, "voiceover": voice[:1100], "title": title[:95],
            "caption": f"{title} - the key tips in 40 seconds.",
            "hashtags": ["#gta6", "#gta6tips", "#gta6secrets", "#gaming", "#shorts"], "safe": True,
            "written_by": "article (no AI)"}


def news_script(scout: Scout, item: dict, log=print) -> dict:
    """Reads the article; Qwen writes the script (retry once), else the no-AI tip script."""
    facts, image_url = sources.fetch_article(item["url"])
    script = None
    for attempt in (1, 2):
        try:
            script = scout.write({"kind": "news", "title": item["title"], "author": item.get("author"),
                                  "angle": item.get("angle"), "facts": facts or item["title"]})
            if script.get("voiceover") or script.get("safe") is False:
                script["written_by"] = "qwen"
                break
        except Exception as exc:
            log(f"  script attempt {attempt} failed: {str(exc)[:160]}")
        script = None
    if script is None:
        if len(_sentences(facts)) < 2:
            raise RuntimeError("no AI script and the article has too little text for a tip script")
        script = extract_script(item, facts)
        log("  script written from the article (no AI)")
    script["image_url"] = image_url
    return script


def make_news(cfg: Config, scout: Scout, outbox: Outbox, item: dict, log=print,
              script: dict | None = None, voice_file: str | None = None) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        script = script or news_script(scout, item)
        image_url = script.get("image_url", "")
        if not script.get("safe", True):
            scout.mark(item["id"], "skip")
            return {"status": "skipped (not safe for Shorts)"}
        text = script.get("voiceover") or item["title"]
        if voice_file and os.path.exists(voice_file):
            voice_path, used_voice = voice_file, "VoiceStudio"
        else:
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
    """Stream clip in the ViceVerified look: facecam top, gameplay bottom, no blur (see clipstyle.py)."""
    from . import highlights

    with tempfile.TemporaryDirectory() as tmp:
        src = sources.twitch_clip(item["url"], tmp)
        clip = {"url": item["url"], "title": item["title"], "streamer": item.get("author") or "streamer",
                "views": item.get("metric") or 0, "kind": "clip"}
        made = os.path.join(tmp, "made")
        os.makedirs(made)
        res = highlights.make_short(cfg, scout, src, clip, made, log=log)
        if res["status"] != "made":
            scout.mark(item["id"], "skip")
            return res
        with open(os.path.join(made, res["file"] + ".json"), encoding="utf-8") as f:
            meta = json.load(f)
        name = f"{datetime.now(timezone.utc):%Y%m%d}-clip-{slug(clip['streamer'] + '-' + item['title'])}"
        where = outbox.deliver(os.path.join(made, res["file"] + ".mp4"), meta, name)
        scout.mark(item["id"], "used")
        return {**res, "file": name, "where": where}


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


# ---- split mode for GitHub Actions: plan -> voice -> render ---------------------------------
# If the VoiceStudio job crashes, the render job still runs and uses the backup voice.

def plan(cfg: Config, log=print) -> dict:
    scout = Scout(cfg)
    items = scout.items()
    news, _ = pick(items, cfg)
    # extra clip candidates: if one is skipped as not safe, the next one is used
    wide = Config(**{**cfg.__dict__, "clips_per_run": cfg.clips_per_run * 3})
    _, clips = pick(items, wide)
    log(f"Picked {len(news)} news + {len(clips)} clip candidates from the Scout.")
    planned = {"news": [], "clips": [{"item": c} for c in clips], "clips_wanted": cfg.clips_per_run}
    for item in news:
        try:
            script = news_script(scout, item, log)
        except Exception as exc:
            log(f"  script failed for {item['title']}: {exc}")
            continue
        if not script.get("safe", True):
            scout.mark(item["id"], "skip")
            log(f"  skipped (not safe): {item['title']}")
            continue
        log(f"  script ready: {script.get('hook')}")
        planned["news"].append({"item": item, "script": script})
    return planned


def record_voices(cfg: Config, planned: dict, folder: str, log=print) -> int:
    """VoiceStudio reads every news script. Returns how many it made."""
    os.makedirs(folder, exist_ok=True)
    made = 0
    for entry in planned.get("news", []):
        dest = os.path.join(folder, f"{entry['item']['id']}.mp3")
        try:
            voice.voicestudio(cfg, entry["script"].get("voiceover") or entry["item"]["title"], dest)
            made += 1
            log(f"  VoiceStudio recorded: {entry['script'].get('hook')}")
        except Exception as exc:
            log(f"  VoiceStudio failed for {entry['item']['title']}: {exc}")
    return made


def render_plan(cfg: Config, planned: dict, voices_dir: str, log=print) -> list[dict]:
    scout = Scout(cfg)
    outbox = Outbox(cfg, log)
    results = []
    jobs = [("news", e["item"], e) for e in planned.get("news", [])] + \
           [("clip", e["item"], e) for e in planned.get("clips", [])]
    clips_wanted = planned.get("clips_wanted", len(planned.get("clips", [])))
    clips_made = 0
    for kind, item, entry in jobs:
        if kind == "clip" and clips_made >= clips_wanted:
            break
        log(f"\n▶ {kind}: {item['title']}")
        try:
            if kind == "news":
                res = make_news(cfg, scout, outbox, item, log, script=entry["script"],
                                voice_file=os.path.join(voices_dir, f"{item['id']}.mp3"))
            else:
                res = make_clip(cfg, scout, outbox, item, log)
        except Exception as exc:
            res = {"status": f"failed: {str(exc)[:400]}"}
        res.update({"kind": kind, "title": item["title"], "url": item["url"]})
        log(f"  → {res['status']}")
        if kind == "clip" and res["status"] == "made":
            clips_made += 1
        results.append(res)
    return results
