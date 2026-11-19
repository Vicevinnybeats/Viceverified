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

## 🎙️ Voice: VoiceStudio with KittenTTS

The workflow starts [VoiceStudio](https://github.com/debpalash/VoiceStudio) (Docker, CPU) on the
GitHub machine and installs the **KittenTTS** voice model. It's an 80 MB model that runs in real
time on a normal CPU, and its licence is **Apache-2.0**, which allows commercial use.

- VoiceStudio asks for a one-time licence acknowledgement before any model is used. The workflow
  gives it **for KittenTTS only** (`VOICESTUDIO_ACCEPT_LICENSE`). It never accepts other models.
- **Not used:** VoiceStudio's default model, OmniVoice. Its weights are **non-commercial
  (CC-BY-NC)**, so they're not OK for monetised channels.
- If VoiceStudio fails, Cloudflare's **Aura** voice is used for that Short. The run summary shows
  which voice each Short got.

Optional settings (repository **Variables**, not secrets):

| Variable | What | Default |
|---|---|---|
| `VOICESTUDIO_VOICE` | KittenTTS voice: `expr-voice-2-m`, `-2-f`, `-3-m`, `-3-f`, `-4-m`, `-4-f`, `-5-m`, `-5-f` (m = male, f = female) | `expr-voice-3-m` |
| `USE_VOICESTUDIO` | `false` = skip VoiceStudio and always use the Cloudflare voice | on |

**Your own or cloned voice:** run VoiceStudio on your PC, make the voice profile there (accept the
licences yourself in its app), and expose it over the internet (for example with a Cloudflare
Tunnel). Then add the secrets `VOICESTUDIO_URL` and `VOICESTUDIO_KEY` (its `OMNIVOICE_API_KEY`),
and set the variables `VOICESTUDIO_MODEL` (engine) and `VOICESTUDIO_VOICE` (your profile name).
Only clone voices you have permission to use, and check that the engine's licence allows
monetised videos.

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
