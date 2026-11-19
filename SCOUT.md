# 🔍 Daily Scout: setup

The Scout is a free **Cloudflare Worker**. Twice a day (06:13 and 18:13 UTC) it checks:

| Source | What it finds | Needs |
|---|---|---|
| News sites (IGN, GameSpot, PC Gamer, Eurogamer, VGC, Kotaku, Polygon, Push Square) | GTA 6 stories, including Rockstar announcements | nothing ✅ |
| Bing News | GTA 6 news from everywhere else | nothing ✅ |
| Reddit r/GTA6 | top posts of the day | free Reddit app (step 4b). Reddit blocks cloud servers without it |
| Twitch | **most-watched GTA 6 clips**, for stream clips | free Twitch app (step 4) |
| YouTube | most-viewed GTA 6 uploads of the day | free API key (step 5) |

**Qwen 3.8** (on your Cloudflare Workers AI) scores every find 0–100 and writes a Short idea for
each. Everything goes into the D1 database `viceverified-scout`, so nothing is reported twice.
That database is **already created** on your Cloudflare account.

Every morning the list lands in this repo as **`reports/scout/YYYY-MM-DD.md`**. You can open it here in
chat, on GitHub, or on your phone. Optionally you also get a Discord or Telegram message.

> Qwen note: the old `qwen3-30b-a3b-fp8` model is switched off by Cloudflare on **Nov 20, 2026**.
> The Scout and the Poster both use `@cf/qwen/qwen3.8-27b`.
> Free allowance: 10,000 neurons/day. The Scout only sends the best 30 finds per run to Qwen
> and asks for low reasoning to stay inside it. If you go over, it falls back to rule-based scoring.

---

## What you do by hand (one time, about 15 min)

All of these go in **GitHub → viceverified → Settings → Secrets and variables → Actions → New repository secret**.

### 1. Cloudflare deploy token (required)
Cloudflare dashboard → **My Profile → API Tokens → Create Token** → template **"Edit Cloudflare Workers"**.
Under Permissions, also **add: Account → D1 → Edit**, then Create.
- secret `CLOUDFLARE_DEPLOY_TOKEN` = that token
- secret `CF_ACCOUNT_ID` = your Account ID (right side of the Cloudflare dashboard home). The Poster uses this one too.

### 2. GitHub token so the Scout can save its daily list (required)
GitHub → your avatar → **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate**.
- Repository access: **Only select repositories → viceverified**
- Permissions: **Contents → Read and write**
- Expiration: 1 year
- secret `SCOUT_GITHUB_TOKEN` = that token

### 3. Your Scout password (required)
Make up any long random password, for example 30+ random letters and numbers.
- secret `SCOUT_KEY` = that password. It protects the "run now" and "mark as used" buttons.

### 4. Twitch, for stream clips (strongly recommended, free)
<https://dev.twitch.tv/console> → **Register Your Application** → name `viceverified-scout`, OAuth Redirect
`http://localhost`, category *Application Integration*, client type *Confidential* → Create → **Manage** → New Secret.
- secrets `TWITCH_CLIENT_ID` and `TWITCH_CLIENT_SECRET`

### 4b. Reddit (optional, free)
<https://www.reddit.com/prefs/apps> → **create another app…** → name `viceverified-scout`, choose **script**,
redirect uri `http://localhost` → **create app**. The code under the app name is the ID; **secret** is the secret.
- secrets `REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET`, then run the deploy again (step 7)

> Google News blocks Cloudflare's servers, so it's off by default. The news sites and Bing cover the same stories.

### 5. YouTube trending (optional, free)
In the same Google Cloud project as the Poster: **APIs & Services → Credentials → Create credentials → API key**.
Restrict it to *YouTube Data API v3*.
- secret `YOUTUBE_API_KEY`

### 6. Phone ping (optional)
- **Discord:** channel → Edit → Integrations → Webhooks → New → Copy URL → secret `DISCORD_WEBHOOK_URL`
- **Telegram:** message @BotFather `/newbot` → secret `TELEGRAM_BOT_TOKEN`. Send your bot a message,
  then open `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `chat.id` → secret `TELEGRAM_CHAT_ID`

### 7. Deploy
GitHub → **Actions → Deploy Scout → Run workflow**. After that it redeploys by itself whenever `scout/` changes.
The log shows your Worker's address, like `https://viceverified-scout.<your-name>.workers.dev`.

### 8. First run (don't wait until tomorrow)
```bash
curl -X POST "https://viceverified-scout.<your-name>.workers.dev/api/run?report=1" -H "Authorization: Bearer <SCOUT_KEY>"
```
Or ask me in chat: "run the scout". Then open `reports/scout/<today>.md` in the repo.

---

## Using it

| Want | Do |
|---|---|
| Today's list | open `reports/scout/YYYY-MM-DD.md`, or visit the Worker address in a browser |
| Finds as data | `GET /api/items?hours=24&min_score=60&kind=clip` |
| Mark something done | `POST /api/items/<id>` with `{"status":"used"}` (or `"skip"`), using the Bearer SCOUT_KEY |
| Run now | `POST /api/run?report=1` with the Bearer SCOUT_KEY |

Every row in the report has an **ID**. Tell me "mark abc123… as used" and I'll do it, or the
Short maker will once it's built.

## Free limits used

| Thing | Use per day | Free limit |
|---|---|---|
| Worker runs | 2 | 100,000 |
| D1 storage | a few KB | 5 GB |
| Workers AI (Qwen) | ~2 × 2 calls | 10,000 neurons |
| GitHub Actions | only when deploying | 2,000 min/month |
