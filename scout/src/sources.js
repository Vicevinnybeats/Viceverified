// Where the Scout looks. Every source is free. A source that fails is
// skipped and noted in the report - it never stops the others.
import { decode, iso, tag } from "./util.js";

const UA = "ViceverifiedScout/1.0 (GTA 6 news digest)";
const MAX_PER_SOURCE = 25;

// ---------- Google News (covers Rockstar Newswire, IGN, Kotaku, etc.) ----------
export function parseRss(xml, source = "google-news") {
  const items = [];
  for (const block of xml.match(/<item[\s>][\s\S]*?<\/item>/gi) || []) {
    const title = tag(block, "title");
    const url = tag(block, "link");
    if (!title || !url) continue;
    items.push({
      source,
      kind: "news",
      title,
      url,
      author: tag(block, "source") || "",
      published_at: iso(tag(block, "pubDate")),
      metric: 0,
      metric_label: "",
    });
    if (items.length >= MAX_PER_SOURCE) break;
  }
  return items;
}

export async function googleNews(query) {
  const url = `https://news.google.com/rss/search?q=${encodeURIComponent(query)}&hl=en-US&gl=US&ceid=US:en`;
  const res = await fetch(url, { headers: { "User-Agent": UA } });
  if (!res.ok) throw new Error(`Google News HTTP ${res.status}`);
  return parseRss(await res.text());
}

// ---------- Reddit r/GTA6 top posts of the day ----------
export function parseReddit(json) {
  return (json?.data?.children || [])
    .map((c) => c.data)
    .filter((p) => p && !p.stickied && !p.over_18)
    .slice(0, MAX_PER_SOURCE)
    .map((p) => ({
      source: "reddit",
      kind: "post",
      title: decode(p.title),
      url: `https://www.reddit.com${p.permalink}`,
      author: `r/${p.subreddit}`,
      published_at: iso(p.created_utc * 1000),
      metric: p.score || 0,
      metric_label: "upvotes",
      thumbnail: p.thumbnail?.startsWith("http") ? p.thumbnail : "",
    }));
}

export async function reddit(sub = "GTA6") {
  const res = await fetch(`https://www.reddit.com/r/${sub}/top.json?t=day&limit=30&raw_json=1`, {
    headers: { "User-Agent": UA },
  });
  if (!res.ok) throw new Error(`Reddit HTTP ${res.status} (Reddit sometimes blocks cloud servers)`);
  return parseReddit(await res.json());
}

// ---------- YouTube: most viewed GTA 6 uploads of the last day (optional free API key) ----------
export function parseYouTube(json) {
  return (json?.items || []).slice(0, MAX_PER_SOURCE).map((v) => ({
    source: "youtube",
    kind: "video",
    title: decode(v.snippet?.title || ""),
    url: `https://www.youtube.com/watch?v=${v.id?.videoId}`,
    author: decode(v.snippet?.channelTitle || ""),
    published_at: iso(v.snippet?.publishedAt),
    metric: 0,
    metric_label: "",
    thumbnail: v.snippet?.thumbnails?.medium?.url || "",
  }));
}

export async function youtube(apiKey, since) {
  const params = new URLSearchParams({
    part: "snippet",
    q: "GTA 6",
    type: "video",
    order: "viewCount",
    publishedAfter: since,
    maxResults: "20",
    relevanceLanguage: "en",
    key: apiKey,
  });
  const res = await fetch(`https://www.googleapis.com/youtube/v3/search?${params}`);
  if (!res.ok) throw new Error(`YouTube HTTP ${res.status}: ${(await res.text()).slice(0, 200)}`);
  return parseYouTube(await res.json());
}

// ---------- Twitch: most watched GTA 6 clips (perfect for stream clips) ----------
export function parseTwitchClips(json) {
  return (json?.data || []).slice(0, MAX_PER_SOURCE).map((c) => ({
    source: "twitch",
    kind: "clip",
    title: c.title,
    url: c.url,
    author: c.broadcaster_name,
    published_at: iso(c.created_at),
    metric: c.view_count || 0,
    metric_label: "views",
    thumbnail: c.thumbnail_url || "",
  }));
}

export async function twitch(clientId, clientSecret, since, gameName = "Grand Theft Auto VI") {
  const tok = await fetch("https://id.twitch.tv/oauth2/token", {
    method: "POST",
    body: new URLSearchParams({ client_id: clientId, client_secret: clientSecret, grant_type: "client_credentials" }),
  });
  if (!tok.ok) throw new Error(`Twitch login HTTP ${tok.status}`);
  const { access_token } = await tok.json();
  const h = { "Client-Id": clientId, Authorization: `Bearer ${access_token}` };

  const g = await fetch(`https://api.twitch.tv/helix/games?name=${encodeURIComponent(gameName)}`, { headers: h });
  if (!g.ok) throw new Error(`Twitch game lookup HTTP ${g.status}`);
  const game = (await g.json()).data?.[0];
  if (!game) throw new Error(`Twitch has no game called "${gameName}"`);

  const params = new URLSearchParams({ game_id: game.id, started_at: since, first: "30" });
  const c = await fetch(`https://api.twitch.tv/helix/clips?${params}`, { headers: h });
  if (!c.ok) throw new Error(`Twitch clips HTTP ${c.status}`);
  return parseTwitchClips(await c.json());
}

// ---------- run them all ----------
export async function collectAll(env, now = new Date()) {
  const since = new Date(now.getTime() - 26 * 3_600_000).toISOString();
  const jobs = {
    "google-news": () => googleNews('"GTA 6" OR "GTA VI" when:1d'),
    rockstar: () => googleNews("site:rockstargames.com GTA when:3d"),
    reddit: () => reddit("GTA6"),
  };
  if (env.YOUTUBE_API_KEY) jobs.youtube = () => youtube(env.YOUTUBE_API_KEY, since);
  if (env.TWITCH_CLIENT_ID && env.TWITCH_CLIENT_SECRET) {
    jobs.twitch = () => twitch(env.TWITCH_CLIENT_ID, env.TWITCH_CLIENT_SECRET, since, env.TWITCH_GAME || undefined);
  }

  const names = Object.keys(jobs);
  const settled = await Promise.allSettled(names.map((n) => jobs[n]()));
  const items = [];
  const errors = {};
  settled.forEach((r, i) => {
    if (r.status === "fulfilled") items.push(...r.value);
    else errors[names[i]] = String(r.reason?.message || r.reason).slice(0, 300);
  });
  const skipped = [];
  if (!env.YOUTUBE_API_KEY) skipped.push("youtube (no YOUTUBE_API_KEY)");
  if (!env.TWITCH_CLIENT_ID) skipped.push("twitch (no TWITCH_CLIENT_ID)");
  return { items, errors, skipped, sources: names };
}
