"""Viceverified Short maker.

  python -m maker run              make today's Shorts from the Scout's best finds
  python -m maker run --dry-run    only show what it would make
  python -m maker voice-test       check VoiceStudio and save out/voice-test.mp3
"""

from __future__ import annotations

import argparse
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
    args = p.parse_args(argv)
    cfg = Config.from_env()

    if args.cmd == "voice-test":
        os.makedirs(cfg.out_dir, exist_ok=True)
        dest = os.path.join(cfg.out_dir, "voice-test.mp3")
        path, used = voice.speak(cfg, Scout(cfg), "GTA 6 is finally here, and the Viceverified voice test works.", dest)
        print(f"Saved {path} using {used}")
        return 0

    if not cfg.scout_key:
        print("SCOUT_KEY is missing.")
        return 1
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
