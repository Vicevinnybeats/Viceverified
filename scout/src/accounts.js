// Account helpers on the Scout Worker:
//   /tiktok/login?key=SCOUT_KEY  -> "Log in with TikTok" (no Python on your PC needed)
//   /tiktok/callback             -> TikTok sends you back here; the login is saved for the Poster
//   /terms, /privacy             -> pages TikTok/Meta developer apps ask for
//   GET/PUT /api/state/<name>    -> small memory for tokens that platforms rotate

const TIKTOK_AUTH = "https://www.tiktok.com/v2/auth/authorize/";
const TIKTOK_TOKEN = "https://open.tiktokapis.com/v2/oauth/token/";
// Drafts to your TikTok inbox only need video.upload. Set the Worker variable TIKTOK_DIRECT_POST=1
// (after turning on Direct Post in the TikTok portal) to also ask for video.publish.
const scopesFor = (env) => (env.TIKTOK_DIRECT_POST === "1" ? "user.info.basic,video.upload,video.publish" : "user.info.basic,video.upload");

export async function kvGet(env, key) {
  const row = await env.DB.prepare("SELECT value FROM kv WHERE key = ?").bind(key).first();
  return row ? row.value : null;
}

export async function kvPut(env, key, value) {
  await env.DB.prepare(
    "INSERT INTO kv (key, value, updated) VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated = excluded.updated",
  ).bind(key, value, new Date().toISOString()).run();
}

async function sha256Short(text) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("").slice(0, 16);
}

/** Stores a token in the Poster's memory format (poster/state.py). */
export async function saveForPoster(env, name, value) {
  const doc = JSON.parse((await kvGet(env, "state:poster")) || "{}");
  // env_hash of "" = "no GitHub secret set": the Poster then uses this saved value
  doc[name] = { env_hash: await sha256Short(""), value, updated: new Date().toISOString().replace(/\.\d+Z$/, "+00:00") };
  await kvPut(env, "state:poster", JSON.stringify(doc));
}

const page = (title, body) =>
  new Response(
    `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">` +
      `<title>${title}</title><style>body{font-family:system-ui,sans-serif;max-width:680px;margin:40px auto;padding:0 16px;line-height:1.55;color:#111;background:#fff}` +
      `h1{font-size:1.6rem}code{background:#f2f2f2;padding:2px 6px;border-radius:4px}.ok{color:#0a7d33}.bad{color:#b00020}</style></head>` +
      `<body>${body}</body></html>`,
    { headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" } },
  );

export function termsPage() {
  return page(
    "Viceverified - Terms of Service",
    `<h1>Viceverified - Terms of Service</h1><p>Last updated: 2026-11-19</p>
<p>Viceverified is a personal tool run by the owner of the Viceverified channels. It makes short GTA 6 news and
stream-clip videos and publishes them to the owner's own YouTube, Instagram and TikTok accounts.</p>
<p>The tool is only used by its owner. No other users can sign up or connect accounts. Content is published only to
accounts the owner has connected and authorised. Stream clips credit the original streamer; news videos credit the
original source.</p>
<p>The tool is provided as-is, without warranties. Contact: through the Viceverified channels.</p>`,
  );
}

export function privacyPage() {
  return page(
    "Viceverified - Privacy Policy",
    `<h1>Viceverified - Privacy Policy</h1><p>Last updated: 2026-11-19</p>
<p>Viceverified only connects to the owner's own social media accounts. It stores the login tokens those platforms
issue (to publish videos on the owner's behalf) and the ids/links of the videos it published. It does not collect,
sell or share personal data of anyone else, and it does not use cookies or tracking.</p>
<p>Data is stored in the owner's Cloudflare and GitHub accounts and can be deleted at any time by revoking the app's
access in the platform's settings. Contact: through the Viceverified channels.</p>`,
  );
}

export async function tiktokLogin(request, env) {
  const url = new URL(request.url);
  if (!env.SCOUT_KEY || url.searchParams.get("key") !== env.SCOUT_KEY) {
    return page("Not allowed", `<h1 class="bad">Wrong or missing key</h1><p>Open <code>/tiktok/login?key=YOUR_SCOUT_KEY</code>.</p>`);
  }
  if (!env.TIKTOK_CLIENT_KEY || !env.TIKTOK_CLIENT_SECRET) {
    return page("TikTok not set up", `<h1 class="bad">TikTok keys missing</h1><p>Add the GitHub secrets <code>TIKTOK_CLIENT_KEY</code> and
      <code>TIKTOK_CLIENT_SECRET</code>, then run <b>Actions → Deploy Scout</b> again.</p>`);
  }
  const state = crypto.randomUUID();
  await kvPut(env, `oauth:${state}`, String(Date.now()));
  const auth = new URL(TIKTOK_AUTH);
  auth.search = new URLSearchParams({
    client_key: env.TIKTOK_CLIENT_KEY,
    scope: scopesFor(env),
    response_type: "code",
    redirect_uri: `${url.origin}/tiktok/callback`,
    state,
  }).toString();
  return Response.redirect(auth.toString(), 302);
}

export async function tiktokCallback(request, env) {
  const url = new URL(request.url);
  const state = url.searchParams.get("state") || "";
  const started = await kvGet(env, `oauth:${state}`);
  if (!started || Date.now() - Number(started) > 15 * 60_000) {
    return page("Login expired", `<h1 class="bad">Login expired or unknown</h1><p>Start again at <code>/tiktok/login?key=…</code>.</p>`);
  }
  await env.DB.prepare("DELETE FROM kv WHERE key = ?").bind(`oauth:${state}`).run();
  if (url.searchParams.get("error")) {
    return page("TikTok said no", `<h1 class="bad">TikTok login cancelled</h1><p>${url.searchParams.get("error_description") || url.searchParams.get("error")}</p>`);
  }
  const res = await fetch(TIKTOK_TOKEN, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      client_key: env.TIKTOK_CLIENT_KEY,
      client_secret: env.TIKTOK_CLIENT_SECRET,
      code: url.searchParams.get("code") || "",
      grant_type: "authorization_code",
      redirect_uri: `${url.origin}/tiktok/callback`,
    }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || !data.refresh_token) {
    return page("TikTok error", `<h1 class="bad">TikTok login failed</h1><p><code>${JSON.stringify(data).slice(0, 300)}</code></p>`);
  }
  await saveForPoster(env, "tiktok_refresh", data.refresh_token);
  return page(
    "TikTok connected",
    `<h1 class="ok">✅ TikTok is connected</h1><p>The Poster can now post to your TikTok. You can close this page.</p>
     <p>Scopes: <code>${data.scope || scopesFor(env)}</code></p>`,
  );
}
