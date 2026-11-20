"""Viceverified Short maker.

  python -m maker run              make today's Shorts from the Scout's best finds
  python -m maker run --dry-run    only show what it would make
  python -m maker voice-test       check VoiceStudio and save out/voice-test.mp3

GitHub Actions uses three steps so a VoiceStudio crash never stops the Shorts:
  python -m maker plan plan.json             pick finds + Qwen scripts
  python -m maker voices plan.json voices/   VoiceStudio voiceovers
  python -m maker render plan.json voices/   build the videos (backup voice if one is missing)
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from poster.config import load_dotenv

from . import pipeline, voice
from .config import Config
from .scout import Scout


def phone_text(results: list[dict]) -> str:
    made = [r for r in results if r["status"] == "made"]
    lines = [f"🎬 Viceverified: {len(made)} new Short{'s' if len(made) != 1 else ''}"]
    for r in results:
        icon = "✅" if r["status"] == "made" else ("⏭️" if r["status"].startswith("skipped") else "❌")
        lines.append(f"{icon} {r['kind']}: {r.get('hook') or r['title']}")
    run = os.environ.get("GITHUB_RUN_ID")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if run and repo:
        lines.append(f"\nDownload: https://github.com/{repo}/actions/runs/{run}")
    return "\n".join(lines)


def video_caption(cfg: Config, result: dict) -> str:
    meta = {}
    try:
        with open(os.path.join(cfg.out_dir, result["file"] + ".json"), encoding="utf-8") as f:
            meta = json.load(f)
    except (OSError, KeyError, ValueError):
        pass
    tags = " ".join(meta.get("hashtags") or [])
    parts = [f"🎬 {result.get('hook') or meta.get('title') or result['title']}",
             meta.get("youtube_title") or "", meta.get("description") or "", tags]
    return "\n\n".join(p for p in parts if p)[:1000]


def notify_phone(cfg: Config, results: list[dict]) -> None:
    if not results:
        return
    scout = Scout(cfg)
    try:
        scout.notify(phone_text(results))
    except Exception as exc:  # a missed message never stops the Shorts
        print(f"(phone message not sent: {exc})")
    for r in results:
        if r["status"] != "made":
            continue
        try:
            scout.send_video(os.path.join(cfg.out_dir, r["file"] + ".mp4"), video_caption(cfg, r))
            print(f"Sent to Telegram: {r['file']}")
        except Exception as exc:
            print(f"(video not sent to Telegram: {exc})")


def summary_md(results: list[dict]) -> str:
    lines = ["## 🎬 Short maker", ""]
    if not results:
        lines.append("Nothing new to make this time.")
    for r in results:
        icon = "✅" if r["status"] == "made" else ("⏭️" if r["status"].startswith("skipped") else "❌")
        extra = f" → **{r.get('where')}** · voice: {r.get('voice', 'clip audio')}" if r["status"] == "made" else ""
        lines.append(f"- {icon} **{r['kind']}** [{r['title']}]({r['url']}): {r['status']}{extra}")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    load_dotenv()
    p = argparse.ArgumentParser(prog="python -m maker", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--dry-run", action="store_true")
    r.add_argument("--news", type=int)
    r.add_argument("--clips", type=int)
    sub.add_parser("voice-test")
    sub.add_parser("voice-setup")
    hl = sub.add_parser("highlights", help="real Twitch highlights in the new look (clips + VOD segments)")
    hl.add_argument("--clips", type=int, default=3)
    hl.add_argument("--vods", type=int, default=1)
    hl.add_argument("--out", default="ready")
    hl.add_argument("--telegram", action="store_true", help="also send each finished Short to Telegram")
    pl = sub.add_parser("plan")
    pl.add_argument("plan_file")
    vo = sub.add_parser("voices")
    vo.add_argument("plan_file")
    vo.add_argument("folder")
    re_ = sub.add_parser("render")
    re_.add_argument("plan_file")
    re_.add_argument("folder")
    args = p.parse_args(argv)
    cfg = Config.from_env()

    if args.cmd == "voice-test":
        os.makedirs(cfg.out_dir, exist_ok=True)
        dest = os.path.join(cfg.out_dir, "voice-test.mp3")
        path, used = voice.speak(cfg, Scout(cfg), "GTA 6 is finally here, and the Viceverified voice test works.", dest)
        print(f"Saved {path} using {used}")
        return 0

    if args.cmd == "voice-setup":
        if not voice.voicestudio_ready(cfg, wait_seconds=30):
            print("VoiceStudio is not reachable.")
            return 1
        voice.setup_voicestudio(cfg)
        return 0

    if args.cmd == "highlights":
        from . import highlights
        from .twitch import Twitch

        scout = Scout(cfg)
        results = highlights.run(cfg, scout, Twitch(), args.out, args.clips, args.vods)
        lines = ["## 🎬 Highlights", ""]
        for r in results:
            icon = "✅" if r["status"] == "made" else ("⏭️" if r["status"].startswith("skipped") else "❌")
            lines.append(f"- {icon} **{r['kind']}** · {r.get('streamer')} · [{r['title'][:70]}]({r['url']})")
            if r["status"] == "made":
                lines.append(f"  - score **{r['score']}** · hook: _{r['hook']}_ ({r['hook_source']}) · "
                             f"{r['layout']} (facecam: {r['facecam']}) · {r['seconds']} s")
                lines.append(f"  - why: {'; '.join(r['why'])}")
                if r.get("candidates"):
                    lines.append(f"  - VOD chat spikes: {r['candidates']}")
            else:
                lines.append(f"  - {r['status']}")
            if args.telegram and r["status"] == "made":
                try:
                    cap = f"🎬 {r['hook']}\n\nscore {r['score']} - " + "; ".join(r["why"]) + f"\nvia @{r.get('streamer')}"
                    scout.send_video(os.path.join(args.out, r["file"] + ".mp4"), cap)
                except Exception as exc:
                    lines.append(f"  - (not sent to Telegram: {exc})")
        md = "\n".join(lines) + "\n"
        print("\n" + md)
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
                f.write(md)
        return 0 if any(r["status"] == "made" for r in results) else 1

    if args.cmd == "voices":
        with open(args.plan_file, encoding="utf-8") as f:
            planned = json.load(f)
        if not planned.get("news"):
            print("No news Shorts planned - no voiceovers needed.")
            return 0
        if not voice.voicestudio_ready(cfg, wait_seconds=30):
            print("VoiceStudio is not reachable.")
            return 1
        made = pipeline.record_voices(cfg, planned, args.folder)
        print(f"VoiceStudio made {made}/{len(planned['news'])} voiceovers.")
        return 0 if made else 1

    if not cfg.scout_key:
        print("SCOUT_KEY is missing.")
        return 1
    if args.cmd == "plan":
        planned = pipeline.plan(cfg)
        with open(args.plan_file, "w", encoding="utf-8") as f:
            json.dump(planned, f, indent=2, ensure_ascii=False)
        print(f"Plan saved: {len(planned['news'])} news, {len(planned['clips'])} clips.")
        return 0
    if args.cmd == "render":
        with open(args.plan_file, encoding="utf-8") as f:
            planned = json.load(f)
        results = pipeline.render_plan(cfg, planned, args.folder)
        notify_phone(cfg, results)
        md = summary_md(results)
        print("\n" + md)
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
                f.write(md)
        failed = [r for r in results if r["status"].startswith("failed")]
        return 1 if results and len(failed) == len(results) else 0
    if args.news is not None:
        cfg.news_per_run = args.news
    if args.clips is not None:
        cfg.clips_per_run = args.clips
    results = pipeline.run(cfg, dry_run=args.dry_run)
    md = summary_md(results)
    print("\n" + md)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(md)
    failed = [r for r in results if r["status"].startswith("failed")]
    return 1 if results and len(failed) == len(results) else 0


if __name__ == "__main__":
    sys.exit(main())
