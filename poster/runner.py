"""Posts one video to every platform, and processes the Google Drive inbox.

Google Drive layout (created automatically in Viceverified.HQ@gmail.com's Drive):

    Viceverified/
      Inbox/    <- drop finished Shorts here (+ optional same-name .txt or .json)
      Posted/   <- moved here when every platform worked (with a .result.json)
      Failed/   <- moved here after 3 failed tries (the .result.json says why)
      _poster/  <- poster memory (tokens)
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone

from . import captions, google, instagram, tiktok, youtube
from .config import ALL_PLATFORMS, Config
from .meta import Meta, parse_sidecar, title_from_filename
from .state import State, now_iso

VIDEO_EXT = (".mp4", ".mov", ".m4v", ".webm")
IG_REFRESH_EVERY = timedelta(days=7)


class Poster:
    def __init__(self, cfg: Config, state: State, log=print, google_token: str | None = None):
        self.cfg, self.state, self.log = cfg, state, log
        self._google = google_token
        self._tiktok: str | None = None
        self._ig: str | None = None

    # --- logins -------------------------------------------------------------
    def google_token(self) -> str:
        if not self._google:
            self._google = google.access_token(self.cfg)
        return self._google

    def tiktok_token(self) -> str:
        if not self._tiktok:
            env = self.cfg.tiktok_refresh_token
            access, new_refresh = tiktok.refresh(self.cfg, self.state.token("tiktok_refresh", env))
            if new_refresh != self.state.token("tiktok_refresh", env):
                self.state.set_token("tiktok_refresh", env, new_refresh)
            self._tiktok = access
        return self._tiktok

    def ig_token(self) -> str:
        if not self._ig:
            env = self.cfg.ig_access_token
            token = self.state.token("instagram", env)
            last = self.state.updated_at("instagram", env)
            due = not last or datetime.now(timezone.utc) - datetime.fromisoformat(last) > IG_REFRESH_EVERY
            if due:
                try:
                    fresh = instagram.refresh_token(self.cfg, token)
                    self.state.set_token("instagram", env, fresh)
                    token = fresh
                except Exception as exc:
                    self.log(f"  Instagram token refresh skipped: {exc}")
            self._ig = token
        return self._ig

    # --- posting ------------------------------------------------------------
    def wanted_platforms(self, meta: Meta) -> list[str]:
        wanted = meta.platforms or self.cfg.platforms
        return [p for p in ALL_PLATFORMS if p in wanted]

    def post_video(self, path: str, meta: Meta, results: dict | None = None, dry_run: bool = False) -> dict:
        """Posts to each wanted platform that hasn't succeeded yet. Returns per-platform results."""
        results = results if results is not None else {}
        for platform in self.wanted_platforms(meta):
            if (results.get(platform) or {}).get("ok"):
                continue
            if not self.cfg.configured(platform):
                results[platform] = {"ok": False, "skipped": True, "error": f"{platform} is not set up yet"}
                self.log(f"  {platform}: not set up yet - skipped")
                continue
            if dry_run:
                self.log(f"  {platform}: would post (dry run)")
                continue
            try:
                if platform == "youtube":
                    out = youtube.post(self.cfg, self.google_token(), path, meta)
                elif platform == "instagram":
                    out = instagram.post(self.cfg, self.ig_token(), path, meta)
                else:
                    out = tiktok.post(self.cfg, self.tiktok_token(), path, meta)
                results[platform] = {"ok": True, "at": now_iso(), **out}
                self.log(f"  {platform}: posted {out.get('url') or out.get('id')}")
            except Exception as exc:
                results[platform] = {"ok": False, "at": now_iso(), "error": str(exc)[:1000]}
                self.log(f"  {platform}: FAILED - {exc}")
        self.state.save()
        return results


def all_done(poster: Poster, meta: Meta, results: dict) -> bool:
    for p in poster.wanted_platforms(meta):
        r = results.get(p) or {}
        if not r.get("ok") and not r.get("skipped"):
            return False
    return True


def process_inbox(cfg: Config, log=print, dry_run: bool = False, max_videos: int | None = None) -> list[dict]:
    token = google.access_token(cfg)
    drive = google.Drive(token)
    root = drive.ensure_folder(cfg.drive_root_folder)
    inbox = drive.ensure_folder("Inbox", root)
    posted = drive.ensure_folder("Posted", root)
    failed = drive.ensure_folder("Failed", root)
    system = drive.ensure_folder("_poster", root)

    from .state import drive_state

    poster = Poster(cfg, drive_state(drive, system), log, google_token=token)
    files = drive.list_children(inbox)
    by_name = {f["name"]: f for f in files}
    videos = [f for f in files if f["name"].lower().endswith(VIDEO_EXT) or f["mimeType"].startswith("video/")]
    if not videos:
        log("Inbox is empty - nothing to post.")
        return []

    summary = []
    for video in videos[: max_videos or cfg.max_per_run]:
        name = video["name"]
        stem = os.path.splitext(name)[0]
        log(f"\n▶ {name}")
        result_name = f"{stem}.result.json"
        result_file = by_name.get(result_name)
        record = json.loads(drive.read_text(result_file["id"])) if result_file else {"attempts": 0, "results": {}}

        if record.get("meta"):
            meta = Meta.from_dict(record["meta"])
        else:
            sidecar = by_name.get(f"{stem}.json") or by_name.get(f"{stem}.txt")
            meta = (parse_sidecar(sidecar["name"], drive.read_text(sidecar["id"]), name) if sidecar
                    else Meta(title=title_from_filename(name)))
            meta = captions.enrich(cfg, meta, log)
            record["meta"] = meta.to_dict()

        with tempfile.TemporaryDirectory() as tmp:
            local = os.path.join(tmp, "video" + (os.path.splitext(name)[1] or ".mp4"))
            if not dry_run:
                drive.download(video["id"], local)
            poster.post_video(local, meta, record["results"], dry_run=dry_run)

        if dry_run:
            log(json.dumps(record["meta"], indent=2, ensure_ascii=False))
            continue

        record["attempts"] = int(record.get("attempts", 0)) + 1
        record["updated"] = now_iso()
        result_id = drive.write_text(result_name, inbox, json.dumps(record, indent=2, ensure_ascii=False),
                                     result_file["id"] if result_file else None)

        done = all_done(poster, meta, record["results"])
        target = posted if done else (failed if record["attempts"] >= cfg.max_attempts else None)
        if target:
            group = [video["id"], result_id] + [by_name[n]["id"] for n in (f"{stem}.json", f"{stem}.txt") if n in by_name]
            for fid in group:
                drive.move(fid, target, inbox)
            log(f"  → moved to {'Posted' if done else 'Failed'}")
        else:
            log(f"  → stays in Inbox, will retry next run (try {record['attempts']}/{cfg.max_attempts})")
        summary.append({"video": name, "done": done, "results": record["results"]})
    return summary
