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
