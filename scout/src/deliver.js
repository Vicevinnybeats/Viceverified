// Sends the daily list to you: GitHub repo file (+ optional Discord / Telegram ping).

function b64(text) {
  const bytes = new TextEncoder().encode(text);
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(bin);
}

export async function saveToGitHub(env, path, content, message) {
  const repo = env.GITHUB_REPO || "vicevinnybeats/viceverified";
  const url = `https://api.github.com/repos/${repo}/contents/${path}`;
  const headers = {
    Authorization: `Bearer ${env.GITHUB_TOKEN}`,
    Accept: "application/vnd.github+json",
    "User-Agent": "viceverified-scout",
  };
  const branch = env.GITHUB_BRANCH || undefined;
  let sha;
  const existing = await fetch(branch ? `${url}?ref=${encodeURIComponent(branch)}` : url, { headers });
  if (existing.ok) sha = (await existing.json()).sha;
  const res = await fetch(url, {
    method: "PUT",
    headers,
    body: JSON.stringify({ message, content: b64(content), sha, branch }),
  });
  if (!res.ok) throw new Error(`GitHub save HTTP ${res.status}: ${(await res.text()).slice(0, 200)}`);
  return (await res.json()).content?.html_url;
}

export async function telegramChatId(env) {
  if (env.TELEGRAM_CHAT_ID) return env.TELEGRAM_CHAT_ID;
  if (!env.DB) return null;
  const row = await env.DB.prepare("SELECT value FROM kv WHERE key = ?").bind("telegram:chat_id").first();
  return row ? row.value : null;
}

export async function sendTelegram(env, chatId, text) {
  return fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chat_id: chatId, text: text.slice(0, 4000), disable_web_page_preview: true }),
  });
}

/** /telegram/setup?key=SCOUT_KEY - finds your chat with the bot (send the bot any message first). */
export async function telegramSetup(env) {
  if (!env.TELEGRAM_BOT_TOKEN) return { ok: false, message: "Add the GitHub secret TELEGRAM_BOT_TOKEN, then run Actions → Deploy Scout." };
  const res = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/getUpdates`);
  const data = await res.json().catch(() => ({}));
  if (!data.ok) return { ok: false, message: `Telegram did not accept the bot token (${data.description || res.status}).` };
  const msg = [...(data.result || [])].reverse().map((u) => u.message || u.channel_post).find((m) => m?.chat?.id);
  if (!msg) return { ok: false, message: "No message found. Open your bot in Telegram, send it 'hi', then open this link again." };
  const chatId = String(msg.chat.id);
  await env.DB.prepare(
    "INSERT INTO kv (key, value, updated) VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated = excluded.updated",
  ).bind("telegram:chat_id", chatId, new Date().toISOString()).run();
  await sendTelegram(env, chatId, "✅ Viceverified is connected. You'll get the Scout's daily GTA 6 list and new Shorts here.");
  return { ok: true, message: `Connected to ${msg.chat.first_name || msg.chat.title || "your chat"}. Check Telegram for a test message.` };
}

export async function notify(env, text) {
  const jobs = [];
  if (env.DISCORD_WEBHOOK_URL) {
    jobs.push(
      fetch(env.DISCORD_WEBHOOK_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: text.slice(0, 1900) }),
      }),
    );
  }
  const chatId = env.TELEGRAM_BOT_TOKEN ? await telegramChatId(env).catch(() => null) : null;
  if (chatId) jobs.push(sendTelegram(env, chatId, text));
  await Promise.allSettled(jobs);
}

/** Sends a finished Short as a playable video to your Telegram chat (bots can send up to 50 MB). */
export async function sendTelegramVideo(env, bytes, caption, filename = "short.mp4") {
  const chatId = await telegramChatId(env);
  if (!env.TELEGRAM_BOT_TOKEN || !chatId) return { ok: false, error: "Telegram is not connected" };
  const form = new FormData();
  form.append("chat_id", chatId);
  form.append("caption", String(caption || "").slice(0, 1000));
  form.append("supports_streaming", "true");
  form.append("video", new Blob([bytes], { type: "video/mp4" }), filename);
  const res = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendVideo`, { method: "POST", body: form });
  const data = await res.json().catch(() => ({}));
  return data.ok ? { ok: true } : { ok: false, error: data.description || `HTTP ${res.status}` };
}
