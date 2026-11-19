# 🎬 Short maker

Every day at **06:43 and 18:43 UTC** (30 min after the Scout), GitHub Actions takes the Scout's best
new finds and makes finished **1080×1920 Shorts**:

| Type | How it's made |
|---|---|
| **News Short** | Reads the article → **Qwen** writes a hook and a 30–40 s script using only facts from the article → **VoiceStudio** reads it → **Whisper** times the captions → ffmpeg builds the video: "GTA 6 NEWS" banner, hook box, the article picture with a slow zoom (or your own gameplay, see below), word-by-word yellow captions, source credit |
| **Stream-clip Short** | Downloads the Twitch clip → Whisper captions what's said → Qwen writes the hook → vertical layout (clip in the middle, blurred copy behind), captions, `twitch.tv/<streamer>` credit |

Qwen marks stories and clips about nudity, strip clubs, slurs or real violence as **not safe**, and
those are skipped. Every Short gets a caption file (title, description with a source or streamer
credit, hashtags) that the Poster uses.

**Where they go**
- With Google set up (Poster SETUP.md, step 2): straight into **Drive → Viceverified/Inbox**, and the Poster posts them.
- Always: on the run's page, **Actions → Make Shorts → (a run) → Artifacts → `shorts-N`**. Download the zip, which holds the `.mp4` and `.json`.

**How many:** 1 news + 1 clip per run, so 4 Shorts a day. YouTube's free API allows about 6
uploads a day. To change this, add repository **variables** `NEWS_PER_RUN` and `CLIPS_PER_RUN`.

---

## 🎙️ Voice: VoiceStudio

The workflow starts [VoiceStudio](https://github.com/debpalash/VoiceStudio) (Docker, CPU) on the
GitHub machine. Its voice model (~2.4 GB) downloads on the first run and is cached after that.
If VoiceStudio isn't ready, Cloudflare's free **Aura** voice is used for that Short. The run summary
shows which voice each Short got.

Optional settings (repository **Variables**, not secrets):

| Variable | What | Default |
|---|---|---|
| `VOICESTUDIO_VOICE` | voice name or id (`alloy`, `ash`, `coral`… or a voice profile you made) | `alloy` |
| `VOICESTUDIO_MODEL` | engine id (`omnivoice`, or a light CPU engine you installed) | `tts-1` (active engine) |
| `USE_VOICESTUDIO` | `false` = skip VoiceStudio and always use the Cloudflare voice | on |

**Your own or cloned voice:** run VoiceStudio on your PC, make the voice profile there, and expose it
over the internet (for example with a Cloudflare Tunnel). Then add the secrets `VOICESTUDIO_URL`
(e.g. `https://voice.yourdomain.com`) and `VOICESTUDIO_KEY` (its `OMNIVOICE_API_KEY`), and set
`VOICESTUDIO_VOICE` to your profile's name. Only clone voices you have permission to use.

> VoiceStudio is AGPL-3.0. Each voice model has its own licence, shown in VoiceStudio's Model
> Manager. Check it allows monetised videos before you use it.

## 🎮 Your own gameplay as background (optional, recommended)
Make a folder **Viceverified/Broll** in Google Drive and drop some of your own GTA 6 gameplay
recordings in it. News Shorts then use a random one as the moving background instead of the
purple gradient. Your own footage is also the safest choice for copyright.

## 🎯 Only clip certain streamers (recommended)
Repository variable `CLIP_STREAMERS` = `ohnePixel,LIRIK,jasontheween` (comma list). Use this
for streamers who allow clipping, such as those in clipping programs. Empty = any streamer.

## ▶️ Run it now
**Actions → Make Shorts → Run workflow**. Tick *Dry run* to only see what it would pick.

Local test (needs ffmpeg + yt-dlp): `python -m maker run --dry-run` · `python -m maker voice-test`
