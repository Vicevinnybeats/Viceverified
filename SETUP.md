# Viceverified Poster: setup guide

**What it does:** you drop a finished Short into Google Drive, and the poster puts it on
**YouTube Shorts, Instagram Reels and TikTok** by itself. It checks every 2 hours,
for free, on GitHub Actions. Your **Qwen 3 on Cloudflare** writes the hook, the
description and the hashtags.

```
Google Drive (Viceverified.HQ@gmail.com)
  Viceverified/Inbox/   ← drop  gta6-leak.mp4  (+ optional  gta6-leak.txt)
        │   every 2 hours (GitHub Actions, free)
        ▼
  Qwen 3 writes captions  →  YouTube Shorts  +  Instagram Reels  +  TikTok
        ▼
  Viceverified/Posted/  ← video + gta6-leak.result.json (links to every post)
  Viceverified/Failed/  ← only if a platform failed 3 times (the reason is inside)
```

You don't need all three platforms on day one. Anything you haven't set up yet is skipped.
Set up the easiest platform first: **YouTube**.

---

## Optional: video info file

Next to `my-clip.mp4`, put `my-clip.txt`:

```
GTA 6 map is BIGGER than we thought
Vice City + Leonida keys compared side by side #gta6 #vicecity
```

The first line is the title. The rest is the description, and any hashtags in it are used.
With no file, the title comes from the filename and Qwen writes the rest.
You can also use `my-clip.json` with `title`, `description`, `hashtags` and
`platforms` (for example `["youtube","tiktok"]` to skip Instagram for that one video).

**Video format:** vertical 9:16 (1080×1920), MP4, under 60–90 s works on every platform.

---

## Step 1: Put the code on GitHub (already done)

This repo is `vicevinnybeats/viceverified`. The schedule lives in `.github/workflows/poster.yml`.
You add your keys under **GitHub → repo → Settings → Secrets and variables → Actions →
New repository secret**. Every name in **CAPS** below is a secret.

## Step 2: Google (YouTube + Drive), about 15 minutes

1. Go to <https://console.cloud.google.com> and log in with **Viceverified.HQ@gmail.com**.
   Create a project named `viceverified`.
2. Under **APIs & Services → Library**, enable **YouTube Data API v3** and **Google Drive API**.
3. Under **OAuth consent screen**, choose External, use app name `Viceverified Poster`, and add
   your email as a test user. Then press **Publish app** ("In production").
   ⚠️ If you skip publishing, Google expires your login every 7 days. You'll see an
   "unverified app" warning when you log in. That's fine for your own account:
   click *Advanced → Go to Viceverified Poster*.
4. Under **Credentials → Create credentials → OAuth client ID**, pick **Desktop app**.
   Copy the ID and secret into the secrets `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`.
5. On your PC (with Python installed), run:
   ```bash
   git clone https://github.com/vicevinnybeats/viceverified && cd viceverified
   pip install -r requirements.txt
   cp .env.example .env      # fill in GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET
   python -m poster auth google
   ```
   Log in, and it prints `GOOGLE_REFRESH_TOKEN`. Save that as a secret.
6. The YouTube channel must belong to that same Google account.

> YouTube note: until you send Google's free **API audit form**
> (<https://support.google.com/youtube/contact/yt_api_form>), videos uploaded through the API
> are locked to **private**. Submit the form early. The free quota allows about **6 uploads a day**.

## Step 3: Instagram, about 20 minutes

1. Switch your Instagram to a **Creator** or **Business** account (in the Instagram app → Settings → Account type).
2. Go to <https://developers.facebook.com>, then **My Apps → Create app → Business**, and add the
   **Instagram** product with *"API setup with Instagram login"*.
3. Add your Instagram account as a tester and accept the invite in the Instagram app
   (Settings → Apps and websites).
4. Press **Generate token** next to your account. Save it as `IG_ACCESS_TOKEN` and the
   number shown as `IG_USER_ID`.
   The token lasts 60 days. The poster renews it by itself every week and keeps the new one
   in `Drive/Viceverified/_poster/state.json`.

**Video link:** Instagram downloads each video from a public link. Your Scout parks the video in
Cloudflare **Workers KV** for a few minutes and deletes it right after posting. That's free and needs
no credit card, and it's already set up. Cloudflare R2 (`R2_*` settings) is optional and only used
if you add it.

## Step 4: Your Qwen 3 (captions), about 3 minutes

1. Your Cloudflare **Account ID** is on the right side of the dashboard home. Save it as `CF_ACCOUNT_ID`.
   This is also used for R2.
2. Go to **My Profile → API Tokens → Create Token → "Workers AI" template**. Save the token as `CF_API_TOKEN`.
3. The default model is `@cf/qwen/qwen3.8-27b`. To use a different Qwen model, add a
   repository **variable** (not a secret) named `QWEN_MODEL`.

## Step 5: TikTok, about 20 minutes plus waiting for approval

1. At <https://developers.tiktok.com>, go to **Manage apps → Connect an app**.
2. Add the products **Login Kit** and **Content Posting API**. Under Content Posting,
   turn on **Direct Post**. Scopes: `user.info.basic`, `video.upload`, `video.publish`.
3. Add a **Redirect URI**. It must be `https://`. Any page you own works, for example
   `https://vicevinnybeats.github.io/viceverified/` (GitHub Pages).
4. Submit the app for review. Save the Client key and secret as `TIKTOK_CLIENT_KEY` and
   `TIKTOK_CLIENT_SECRET`.
5. On your PC, run:
   ```bash
   python -m poster auth tiktok --redirect-uri https://your-redirect-page/
   ```
   Allow access and paste the address you land on. Save the result as `TIKTOK_REFRESH_TOKEN`.

> **Private-only until audited.** Until TikTok audits your app, it only allows
> **private** direct posts. To post publicly now, add a repository **variable**
> `TIKTOK_MODE` = `inbox`. Each video then lands in your TikTok app as a draft, and one tap posts it.
> Switch back to `direct` once TikTok approves the app.

## Step 6: Test it

- On your PC, run `python -m poster check`. It tests every login and shows ✅ or ❌ for each.
- On GitHub, go to **Actions → Poster → Run workflow** and tick **Dry run**. It shows the
  captions Qwen wrote without posting anything.
- Drop a video in `Drive/Viceverified/Inbox`, then run the workflow without dry run (or
  wait up to 2 hours). Links to every post end up in the `.result.json` file in `Posted/`.

You can also post one file straight from your PC:

```bash
python -m poster post my-clip.mp4 --title "GTA 6 is finally here" --platforms youtube,tiktok
```

---

## Everything is free, with these limits

| Thing | Free limit |
|---|---|
| GitHub Actions | Public repo: unlimited. Private repo: 2,000 min/month (≈ 1–3 min per run) |
| YouTube API | About 6 uploads per day |
| Instagram API | 50 posts per 24 h |
| TikTok API | A few posts per day per account (TikTok sets the limit) |
| Cloudflare Workers KV | 1 GB, 1,000 uploads/day (videos are deleted right after posting) |
| Workers AI (Qwen) | 10,000 neurons per day. Captions use very little |

## Safety

- Keys live only in GitHub Secrets or in your own `.env`. `.env` is in `.gitignore`, so it is never uploaded.
- Only post clips you have permission to use (streamer clipping programs) or your own news edits.
  Raw Rockstar trailer reuploads get taken down.
