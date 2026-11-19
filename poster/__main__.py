"""Viceverified Poster - post one Short to YouTube, Instagram and TikTok.

  python -m poster inbox                 post everything in Google Drive Viceverified/Inbox
  python -m poster post video.mp4 --title "GTA 6 map leak"   post one file from your PC
  python -m poster check                 test every login without posting
  python -m poster auth google|tiktok    one-time logins (run on your PC)
"""

from __future__ import annotations

import argparse
import json
import sys

from . import captions, google, instagram, tiktok
from .config import ALL_PLATFORMS, Config, load_dotenv
from .meta import Meta, normalize_hashtags
from .runner import Poster, process_inbox
from .state import local_state


def cmd_post(cfg: Config, args) -> int:
    meta = Meta(
        title=args.title,
        description=args.description or "",
        hashtags=normalize_hashtags((args.hashtags or "").split()),
        platforms=[p.strip() for p in args.platforms.split(",")] if args.platforms else None,
    )
    meta = captions.enrich(cfg, meta)
    print(json.dumps(meta.to_dict(), indent=2, ensure_ascii=False))
    results = Poster(cfg, local_state()).post_video(args.video, meta, dry_run=args.dry_run)
    print(json.dumps(results, indent=2))
    return 0 if all(r.get("ok") or r.get("skipped") for r in results.values()) else 1


def cmd_inbox(cfg: Config, args) -> int:
    if not cfg.has_google:
        print("Google Drive is not set up (GOOGLE_CLIENT_ID / SECRET / REFRESH_TOKEN). See SETUP.md.")
        return 1
    summary = process_inbox(cfg, dry_run=args.dry_run, max_videos=args.max)
    failed = [s for s in summary if not s["done"]]
    return 1 if failed else 0


def cmd_check(cfg: Config, _args) -> int:
    ok = True

    def line(name, fn):
        nonlocal ok
        try:
            print(f"✅ {name}: {fn()}")
        except Exception as exc:
            ok = False
            print(f"❌ {name}: {exc}")

    if cfg.has_google:
        def g():
            d = google.Drive(google.access_token(cfg))
            root = d.ensure_folder(cfg.drive_root_folder)
            for sub in ("Inbox", "Posted", "Failed", "_poster"):
                d.ensure_folder(sub, root)
            return f"logged in, Drive folders ready in '{cfg.drive_root_folder}/' (YouTube uses the same login)"
        line("Google / YouTube / Drive", g)
    else:
        print("⚪ Google / YouTube / Drive: not set up")

    if cfg.has_instagram:
        def ig():
            import requests
            r = requests.get(f"https://{cfg.ig_graph_host}/{cfg.ig_api_version}/{cfg.ig_user_id}",
                             params={"fields": "username", "access_token": cfg.ig_access_token}, timeout=30)
            r.raise_for_status()
            return f"@{r.json().get('username')}"
        line("Instagram", ig)
    else:
        print("⚪ Instagram: not set up (needs IG_USER_ID, IG_ACCESS_TOKEN and the R2_* settings)")

    if cfg.has_tiktok:
        def tt():
            access, _ = tiktok.refresh(cfg, cfg.tiktok_refresh_token)
            info = tiktok.creator_info(access)
            return (f"@{info.get('creator_username')} - allowed privacy: {info.get('privacy_level_options')} "
                    f"(mode: {cfg.tiktok_mode})")
        line("TikTok", tt)
    else:
        print("⚪ TikTok: not set up")

    if cfg.has_qwen:
        line("Qwen captions", lambda: captions.ask_qwen(cfg, Meta(title="GTA 6 launch day test")).get("youtube_title"))
    else:
        print("⚪ Qwen captions: not set up (CF_ACCOUNT_ID / CF_API_TOKEN) - default hashtags will be used")
    return 0 if ok else 1


def main(argv=None) -> int:
    load_dotenv()
    p = argparse.ArgumentParser(prog="python -m poster", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("post", help="post one video file")
    sp.add_argument("video")
    sp.add_argument("--title", required=True)
    sp.add_argument("--description")
    sp.add_argument("--hashtags", help='e.g. "#gta6 #gaming"')
    sp.add_argument("--platforms", help=f"comma list from: {','.join(ALL_PLATFORMS)}")
    sp.add_argument("--dry-run", action="store_true")

    si = sub.add_parser("inbox", help="post everything waiting in Google Drive")
    si.add_argument("--dry-run", action="store_true")
    si.add_argument("--max", type=int)

    sub.add_parser("check", help="test all logins")

    sa = sub.add_parser("auth", help="one-time logins (run on your PC)")
    sa.add_argument("service", choices=["google", "tiktok"])
    sa.add_argument("--redirect-uri", help="TikTok only: the redirect URI registered in your TikTok app")

    sub.add_parser("refresh-instagram", help="print a fresh 60-day Instagram token")

    args = p.parse_args(argv)
    cfg = Config.from_env()
    if args.cmd == "post":
        return cmd_post(cfg, args)
    if args.cmd == "inbox":
        return cmd_inbox(cfg, args)
    if args.cmd == "check":
        return cmd_check(cfg, args)
    if args.cmd == "refresh-instagram":
        print(instagram.refresh_token(cfg, cfg.ig_access_token))
        return 0
    from . import auth
    if args.service == "google":
        auth.google_login(cfg)
    else:
        if not args.redirect_uri:
            print("Add --redirect-uri https://... (the same one you entered in your TikTok developer app)")
            return 1
        auth.tiktok_login(cfg, args.redirect_uri)
    return 0


if __name__ == "__main__":
    sys.exit(main())
