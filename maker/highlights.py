"""Real highlights, two sources (most reliable first):

1. Twitch top clips per streamer (last 48 h, most viewed) - already highlights picked by viewers.
   Only the clip is downloaded (yt-dlp).
2. VOD segments - never live recordings, never whole VODs. Chat log -> spikes (>= 3x median speed,
   hype words) -> only that segment +/- 30 s is downloaded (yt-dlp --download-sections) ->
   loudness spike (>= +8 dB vs the 2-min average) refines the peak.

Each pick gets a score and a plain-English reason, so you can see why it was chosen."""

from __future__ import annotations

import glob
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile

from . import chat, clipstyle, facecam, loudness, render, sources
from .twitch import parse_duration
from .config import Config

TEMPLATE_HOOKS = ["Wait for it… 👀", "{s} can't believe this", "Chat went crazy for this", "This is why we watch {s}"]


def item_id(url: str) -> str:
    """Same id the Scout uses (sha1 of the link) - so a clip is never made twice."""
    return hashlib.sha1(url.encode()).hexdigest()[:16]


def hook_for(scout, clip: dict, transcript: str, log=print) -> tuple[dict, str]:
    """Qwen writes the hook. Bad answer -> retry once -> template. Never drops the clip."""
    payload = {"kind": "clip", "title": clip["title"], "author": clip["streamer"], "metric": clip.get("views"),
               "transcript": transcript}
    for attempt in (1, 2):
        try:
            s = scout.write(payload)
            if s.get("hook") and isinstance(s.get("hook"), str):
                return s, "qwen" if attempt == 1 else "qwen (retry)"
        except Exception as exc:
            log(f"  hook attempt {attempt} failed: {exc}")
    t = TEMPLATE_HOOKS[int(item_id(clip["url"]), 16) % len(TEMPLATE_HOOKS)].format(s=clip["streamer"])
    return {"hook": t, "title": clip["title"][:90], "caption": f"{clip['title']} - via @{clip['streamer']}",
            "hashtags": ["#twitch", "#clips", "#gaming", "#shorts"], "safe": True}, "template"


_WHISPER = None


def transcribe(scout, audio: str, log=print) -> tuple[dict, str]:
    """English transcript with word timings: faster-whisper on this machine (free), else the Scout's Whisper."""
    global _WHISPER
    try:
        from faster_whisper import WhisperModel

        if _WHISPER is None:
            _WHISPER = WhisperModel(os.environ.get("WHISPER_MODEL", "base.en"), device="cpu", compute_type="int8")
        # decode with ffmpeg ourselves (16 kHz mono float) - avoids PyAV version clashes
        import numpy as np

        pcm = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-i", audio, "-f", "f32le", "-ac", "1",
                              "-ar", "16000", "-"], capture_output=True, check=True).stdout
        samples = np.frombuffer(pcm, dtype=np.float32)
        segments, _info = _WHISPER.transcribe(samples, language="en", word_timestamps=True, vad_filter=True)
        words, text = [], []
        for seg in segments:
            text.append(seg.text)
            for w in seg.words or []:
                if w.word.strip():
                    words.append({"word": w.word.strip(), "start": float(w.start), "end": float(w.end)})
        return {"text": " ".join(text).strip(), "words": words}, "faster-whisper"
    except ImportError:
        pass
    except Exception as exc:
        log(f"  local transcript failed ({exc}) - trying the Scout")
    try:
        return scout.transcribe(audio), "scout-whisper"
    except Exception as exc:
        log(f"  transcript failed ({exc}) - no captions for this one")
        return {"text": "", "words": []}, "none"


def score_clip(views: int, peak: dict, chat_ratio: float) -> float:
    """0-100: viewers (max 40) + loudness jump (max 30) + chat speed-up (max 30)."""
    return round(min(40, 8 * math.log10(max(views, 1) + 1)) + min(30, max(0.0, peak.get("jump") or 0) * 2)
                 + min(30, chat_ratio * 6), 1)


# ---------------------------------------------------------------- picking -----------------
RULES = os.path.join(os.path.dirname(__file__), "clip_rules.json")


def clip_rules() -> dict:
    try:
        with open(RULES, encoding="utf-8") as f:
            return json.load(f).get("streamers") or {}
    except (OSError, ValueError):
        return {}


def clip_rule(streamer: str, rules: dict | None = None) -> str:
    """allowed | ask | unknown | no - may we clip this Twitch streamer? (maker/clip_rules.json)"""
    rules = clip_rules() if rules is None else rules
    key = "twitch:" + re.sub(r"\s+", "", (streamer or "").lower())
    return (rules.get(key) or {}).get("rule") or "unknown"


def clip_candidates(cfg: Config, tw, used: set[str], log=print, hours: int = 48) -> list[dict]:
    """Most-viewed English GTA 6 clips, only from streamers who allow clipping (CLIP_ALLOW).
    Streamers you name yourself in CLIP_STREAMERS are always used, unless their rule is 'no'."""
    out, lists = [], []
    rules = clip_rules()
    named = cfg.clip_streamers or []
    gid = tw.game_id()
    logins = list(named) or [k.split(":", 1)[1] for k, v in rules.items()
                             if k.startswith("twitch:") and v.get("rule") in cfg.clip_allow]
    for login in logins:
        u = tw.user(login)
        if not u:
            log(f"  streamer not found on Twitch: {login}")
            continue
        clips = tw.top_clips(broadcaster_id=u["id"], hours=hours, first=20)
        lists.append([c for c in clips if not gid or not c.get("game_id") or c.get("game_id") == gid])
    if not named and gid:
        lists.append(tw.top_clips(game_id=gid, hours=hours, first=50))
    skipped: dict[str, str] = {}
    seen = set()
    for clips in lists:
        for c in clips:
            if item_id(c["url"]) in used or c.get("duration", 0) < 8 or c["url"] in seen:
                continue
            if cfg.clip_language and (c.get("language") or "").lower()[:2] != cfg.clip_language:
                continue
            rule = clip_rule(c["broadcaster_name"], rules)
            is_named = (c["broadcaster_name"] or "").lower() in named
            if rule == "no" or (not is_named and rule not in cfg.clip_allow):
                skipped[c["broadcaster_name"]] = rule
                continue
            seen.add(c["url"])
            out.append({"url": c["url"], "title": c["title"], "streamer": c["broadcaster_name"], "language": c.get("language"),
                        "views": c.get("view_count", 0), "duration": c.get("duration", 0), "rule": rule,
                        "video_id": c.get("video_id") or "", "vod_offset": c.get("vod_offset")})
    if skipped:
        log(f"  skipped (clipping not known to be allowed): {', '.join(sorted(skipped)[:15])}")
    out.sort(key=lambda c: (c["rule"] != "allowed", -c["views"]))
    return out


def analyze_vod(tw, vod: dict, folder: str, avoid: list[float], window: int = 5400, log=print) -> dict:
    """Chat for up to 90 min of the VOD -> per-10 s speed, spikes, scores."""
    total = parse_duration(vod.get("duration", ""))
    centre = avoid[0] if avoid else total / 2
    start = int(max(0, min(centre - window / 2, total - window)))
    end = int(min(total, start + window))
    try:
        msgs = chat.download_chat(vod["id"], start, end, os.path.join(folder, f"chat-{vod['id']}.json"))
    except Exception as exc:
        log(f"  chat not available ({exc}) - using loudness spikes instead")
        msgs = []
    if len(msgs) >= 50:
        rows = chat.buckets(msgs, start, end)
        found, median = chat.spikes(rows, factor=3.0, top=8)
        found = [s for s in found if all(abs(s["t"] - a) > 90 for a in avoid)][:5]
        return {"vod": vod, "start": start, "end": end, "messages": msgs, "median": median, "source": "chat",
                "per_minute": chat.per_minute(msgs, start, end), "spikes": found}
    # fallback: audio only for the analysed window (never the whole VOD, never video)
    audio = download_section(vod["id"], start, end, folder, audio_only=True)
    levels = loudness.per_second(audio)
    os.remove(audio)
    found = []
    for i in range(len(levels)):
        lo = max(0, i - 120)
        base = [v for v in levels[lo:i] if v > -60]
        if levels[i] <= -60 or len(base) < 30:  # muted part, or right after one
            continue
        jump = levels[i] - sum(base) / len(base)
        if jump >= 8 and all(abs(start + i - f["t"]) > 90 for f in found) and all(abs(start + i - a) > 90 for a in avoid):
            found.append({"t": start + i, "ratio": 0.0, "hype": 0, "chat_score": round(min(100, jump * 4), 1),
                          "db_jump": round(jump, 1)})
    found.sort(key=lambda f: f["chat_score"], reverse=True)
    return {"vod": vod, "start": start, "end": end, "messages": [], "median": 0, "source": "loudness",
            "per_minute": loudness.per_minute(levels), "spikes": found[:5]}


def download_section(vod_id: str, a: int, b: int, folder: str, audio_only: bool = False) -> str:
    """Only seconds a..b of the VOD (yt-dlp --download-sections)."""
    tpl = os.path.join(folder, f"seg-{vod_id}-{a}{'-audio' if audio_only else ''}.%(ext)s")
    fmt = "audio_only/bestaudio/worst" if audio_only else "best[height<=1080]/best"
    proc = subprocess.run(["yt-dlp", "-q", "--no-warnings", "-f", fmt,
                           "--download-sections", f"*{a}-{b}", "--force-keyframes-at-cuts",
                           "-o", tpl, f"https://www.twitch.tv/videos/{vod_id}"],
                          capture_output=True, text=True, timeout=900)
    files = glob.glob(os.path.join(folder, f"seg-{vod_id}-{a}{'-audio' if audio_only else ''}.*"))
    if proc.returncode != 0 or not files:
        raise RuntimeError(f"segment download failed: {proc.stderr[-300:]}")
    return files[0]


# ---------------------------------------------------------------- making ------------------
def make_short(cfg: Config, scout, src: str, clip: dict, out_dir: str, chat_msgs: list[dict] | None = None,
               chat_ratio: float = 0.0, log=print) -> dict:
    """src = downloaded clip or VOD segment. chat_msgs times are relative to src."""
    size = clipstyle.video_size(src)
    dur = render.duration(src)
    levels = loudness.per_second(src)
    pk = loudness.peak(levels)
    start, length = clipstyle.choose_window(dur, pk["t"])
    peak_rel = max(0.0, pk["t"] - start)
    words, transcript = [], ""
    with tempfile.TemporaryDirectory() as tmp:
        small = os.path.join(tmp, "a.mp3")
        render.run(["ffmpeg", "-y", "-hide_banner", "-ss", f"{start:.2f}", "-t", f"{length:.2f}", "-i", src,
                    "-vn", "-ac", "1", "-ar", "16000", "-b:a", "48k", small])
        t, how = transcribe(scout, small, log)
        transcript, words = t.get("text", ""), t.get("words") or []
        script, hook_src = hook_for(scout, clip, transcript, log)
        if script.get("safe") is False:
            return {"status": "skipped (not safe for Shorts)", "hook": script.get("hook")}
        box, how = facecam.facecam_box(src, clip["streamer"], size)
        pops = [{**m, "t": m["t"] - start} for m in (chat_msgs or [])]
        pops = chat.popups(pops, peak_rel) if pops else []
        ass = os.path.join(tmp, "s.ass")
        with open(ass, "w", encoding="utf-8") as f:
            f.write(clipstyle.build_ass(length, words, script["hook"], clip["streamer"], peak_rel, pops, split=bool(box)))
        name = f"{clip.get('kind', 'clip')}-{clip['streamer'].lower()}-{item_id(clip['url'])[:8]}"
        out = os.path.join(out_dir, name + ".mp4")
        clipstyle.render_clip(out, src, ass, start, length, peak_rel, box, size, cfg.fonts_dir)
    score = score_clip(clip.get("views", 0), pk, chat_ratio)
    reasons = []
    if clip.get("views"):
        reasons.append(f"{clip['views']:,} views on Twitch")
    if chat_ratio:
        reasons.append(f"chat {chat_ratio}x faster than normal")
    if pk.get("lufs") is not None:
        reasons.append(f"loudest moment at {pk['t']}s ({pk['jump']:+} dB vs the 2-min average"
                       f"{', spike' if pk['spike'] else ''})")
    meta = {"title": script.get("title") or clip["title"], "youtube_title": script.get("title") or clip["title"],
            "caption": script.get("caption", ""), "hashtags": script.get("hashtags") or ["#twitch", "#shorts"],
            "description": f"{script.get('caption', '')}\n\nClip by {clip['streamer']} - full credit: {clip['url']}".strip(),
            "score": score, "why": reasons, "hook_source": hook_src, "layout": "facecam + gameplay" if box else "full gameplay",
            "facecam": how, "window": [round(start, 1), round(length, 1)], "source": clip["url"]}
    with open(os.path.join(out_dir, name + ".json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    return {"status": "made", "file": name, "score": score, "hook": script["hook"], "why": reasons,
            "hook_source": hook_src, "layout": meta["layout"], "facecam": how, "seconds": round(length, 1)}


def run(cfg: Config, scout, tw, out_dir: str, n_clips: int = 3, n_vods: int = 1, log=print) -> list[dict]:
    os.makedirs(out_dir, exist_ok=True)
    used = set()
    try:
        used = {i["id"] for i in scout.items_with_status("used")} | {i["id"] for i in scout.items_with_status("skip")}
    except Exception:
        pass
    used |= remembered_clips(scout)
    results = []
    cands = clip_candidates(cfg, tw, used, log)
    log(f"Clip candidates: {len(cands)} (most viewed first)")
    made_clips, fails_in_row = 0, 0
    with tempfile.TemporaryDirectory() as tmp:
        for c in cands:
            if made_clips >= n_clips:
                break
            if fails_in_row >= 4:
                log("\n4 failures in a row - stopping clips here (see the errors above)")
                break
            log(f"\n▶ clip {c['streamer']}: {c['title']} ({c['views']:,} views)")
            try:
                src = sources.twitch_clip(c["url"], tmp)
                msgs, ratio = [], 0.0
                if c["video_id"] and c["vod_offset"] is not None and chat.find_cli():
                    try:
                        a = int(c["vod_offset"])
                        msgs = chat.download_chat(c["video_id"], max(0, a - 300), a + int(c["duration"]) + 5,
                                                  os.path.join(tmp, "clipchat.json"))
                        base = [m for m in msgs if m["t"] < a]
                        inside = [m for m in msgs if a <= m["t"] <= a + c["duration"]]
                        normal = len(base) / 300 if base else 0
                        ratio = round((len(inside) / max(c["duration"], 1)) / normal, 2) if normal else 0.0
                        msgs = [{**m, "t": m["t"] - a} for m in inside]
                    except Exception as exc:
                        log(f"  chat not available ({exc})")
                res = make_short(cfg, scout, src, {**c, "kind": "clip"}, out_dir, msgs, ratio, log)
                os.remove(src)
            except Exception as exc:
                res = {"status": f"failed: {str(exc)[:300]}"}
            res.update({"kind": "clip", "title": c["title"], "url": c["url"], "streamer": c["streamer"]})
            log(f"  → {res['status']}" + (f" · score {res['score']} · hook: {res['hook']}" if res.get("score") else ""))
            fails_in_row = fails_in_row + 1 if res["status"].startswith("failed") else 0
            if res["status"] == "made":
                made_clips += 1
                _mark(scout, c["url"], "used")
            elif res["status"].startswith("skipped"):
                _mark(scout, c["url"], "skip")
            results.append(res)

        # ---- VOD segments
        if n_vods and chat.find_cli():
            vods_done = 0
            for c in cands:
                if vods_done >= n_vods:
                    break
                if not c["video_id"]:
                    continue
                vod = next(iter(tw._get("videos", id=c["video_id"])), None)
                if not vod:
                    continue
                log(f"\n▶ VOD {vod['user_name']}: {vod['title'][:70]} ({vod['duration']})")
                try:
                    an = analyze_vod(tw, vod, tmp, [float(c["vod_offset"] or 0)], log=log)
                    log(f"  analysed {an['start']}-{an['end']} s by {an['source']}: {len(an['messages'])} chat messages, "
                        f"median {an['median']} per 10 s, {len(an['spikes'])} candidate moments")
                    label = "chat msgs/min" if an["source"] == "chat" else "loudness LUFS/min"
                    log(f"  {label}: {an['per_minute']}")
                    for s in an["spikes"]:
                        log(f"    candidate t={s['t']}s chat x{s['ratio']} hype {s['hype']} score {s['chat_score']}")
                    if not an["spikes"]:
                        results.append({"status": "no highlight found (no chat or loudness spike)", "kind": "vod",
                                        "title": vod["title"], "url": f"https://www.twitch.tv/videos/{vod['id']}",
                                        "streamer": vod["user_name"], "chat_per_minute": an["per_minute"]})
                        vods_done += 1
                        continue
                    best = an["spikes"][0]
                    a, b = max(0, int(best["t"]) - 30), int(best["t"]) + 40
                    seg = download_section(vod["id"], a, b, tmp)
                    msgs = [{**m, "t": m["t"] - a} for m in an["messages"] if a <= m["t"] <= b]
                    seg_clip = {"url": f"https://www.twitch.tv/videos/{vod['id']}?t={a}s", "title": vod["title"],
                                "streamer": vod["user_name"], "views": 0, "kind": "vod"}
                    res = make_short(cfg, scout, seg, seg_clip, out_dir, msgs, best["ratio"], log)
                    res["candidates"] = [{"t": s["t"], "chat_x": s["ratio"], "hype": s["hype"], "score": s["chat_score"]}
                                         for s in an["spikes"]]
                    res["chat_per_minute"] = an["per_minute"]
                except Exception as exc:
                    res = {"status": f"failed: {str(exc)[:300]}"}
                res.update({"kind": "vod", "title": vod["title"], "url": f"https://www.twitch.tv/videos/{vod['id']}",
                            "streamer": vod["user_name"]})
                log(f"  → {res['status']}" + (f" · score {res['score']} · hook: {res['hook']}" if res.get("score") else ""))
                results.append(res)
                vods_done += 1
    with open(os.path.join(out_dir, "report.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    return results


def remembered_clips(scout) -> set[str]:
    try:
        return set((scout.get_state("clips") or {}).get("used", []))
    except Exception:
        return set()


def _mark(scout, url: str, status: str) -> None:
    """Remember a clip as done - in the Scout's list and in its memory (clips straight from Twitch
    are not always in the Scout's list, which is why the same clip was made twice before)."""
    try:
        scout.mark(item_id(url), status)
    except Exception:
        pass
    try:
        state = scout.get_state("clips") or {}
        used = list(dict.fromkeys((state.get("used") or []) + [item_id(url)]))[-2000:]
        scout.put_state("clips", {"used": used})
    except Exception:
        pass


def install_hint() -> str:
    return "" if shutil.which("yt-dlp") else "yt-dlp is not installed"
