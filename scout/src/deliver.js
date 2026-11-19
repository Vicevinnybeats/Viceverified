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
  if (env.TELEGRAM_BOT_TOKEN && env.TELEGRAM_CHAT_ID) {
    jobs.push(
      fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ chat_id: env.TELEGRAM_CHAT_ID, text: text.slice(0, 4000), disable_web_page_preview: true }),
      }),
    );
  }
  await Promise.allSettled(jobs);
}
