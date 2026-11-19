# Viceverified

GTA 6 news Shorts and stream clips, made and posted automatically.

## Poster ✅

Drop a vertical video into **Google Drive → `Viceverified/Inbox`**. Every 2 hours the poster
uploads it to **YouTube Shorts, Instagram Reels and TikTok**. Your Qwen 3 on Cloudflare writes
the captions. It runs free on GitHub Actions.

👉 **Setup guide: [SETUP.md](SETUP.md)**

```bash
python -m poster check                    # test all logins
python -m poster inbox                    # post what's waiting in Drive
python -m poster post clip.mp4 --title "GTA 6 is out"   # post one file
python -m unittest discover -s tests      # run tests
```

| File | What it does |
|---|---|
| `poster/runner.py` | Drive inbox → post → move to Posted/Failed, with retries |
| `poster/youtube.py` | YouTube Shorts upload |
| `poster/instagram.py` | Instagram Reels upload, using R2 as a temporary link |
| `poster/tiktok.py` | TikTok direct post or inbox draft |
| `poster/captions.py` | Qwen 3 (Workers AI) writes the hook, description and hashtags |
| `poster/google.py` | Google login + Drive |
| `.github/workflows/poster.yml` | The 2-hour schedule |

## Daily Scout ✅

A free Cloudflare Worker running Qwen 3.8. Twice a day it finds new GTA 6 news and the
most-watched stream clips, scores them, and keeps a list in D1. Every morning it saves
`reports/scout/YYYY-MM-DD.md` to this repo.

👉 **Setup guide: [SCOUT.md](SCOUT.md)** · code in `scout/` · tests: `cd scout && node --test`

## Coming next

- **Clipper / news-Short maker:** turns Scout finds into vertical videos and drops them in the Inbox
