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

// ---------- Gaming news sites' own feeds (work from Cloudflare, unlike Google News) ----------
export const NEWS_FEEDS = {
  IGN: "https://feeds.feedburner.com/ign/all",
  GameSpot: "https://www.gamespot.com/feeds/game-news/",
  "PC Gamer": "https://www.pcgamer.com/rss/",
  Eurogamer: "https://www.eurogamer.net/feed",
  VGC: "https://www.videogameschronicle.com/feed/",
  Kotaku: "https://kotaku.com/rss",
  Polygon: "https://www.polygon.com/rss/index.xml",
  "Push Square": "https://www.pushsquare.com/feeds/latest",
};

export const GTA_RE = /\bgta\s*(6|vi)\b|grand theft auto\s*(6|vi)\b|\brockstar\b|vice city|leonida|\bgta online\b/i;

function atomLink(block) {
  const alt = block.match(/<link[^>]*rel=["']alternate["'][^>]*href=["']([^"']+)["']/i);
  const any = block.match(/<link[^>]*href=["']([^"']+)["']/i);
  return (alt || any)?.[1] || "";
}

/** Reads RSS or Atom; keeps only GTA 6 stories. */
export function parseFeed(xml, site, filter = GTA_RE) {
  const items = [];
  const blocks = xml.match(/<item[\s>][\s\S]*?<\/item>/gi) || xml.match(/<entry[\s>][\s\S]*?<\/entry>/gi) || [];
  for (const block of blocks) {
    const title = tag(block, "title");
    const summary = (tag(block, "description") || tag(block, "summary")).slice(0, 400);
    if (!title || (filter && !filter.test(`${title} ${summary}`))) continue;
    const url = tag(block, "link") || atomLink(block);
    if (!url.startsWith("http")) continue;
    items.push({
      source: "news-sites",
      kind: "news",
      title,
      url,
      author: site,
      published_at: iso(tag(block, "pubDate") || tag(block, "published") || tag(block, "updated")),
      metric: 0,
      metric_label: "",
    });
    if (items.length >= 10) break;
  }
  return items;
}

/** All sites in parallel. Only fails if every site fails. */
export async function newsSites(feeds = NEWS_FEEDS) {
  const names = Object.keys(feeds);
  const results = await Promise.allSettled(
    names.map(async (name) => {
      const res = await fetch(feeds[name], { headers: { "User-Agent": UA, Accept: "application/rss+xml, application/xml, text/xml" } });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return parseFeed(await res.text(), name);
    }),
  );
  const items = [];
  const failed = [];
  results.forEach((r, i) => (r.status === "fulfilled" ? items.push(...r.value) : failed.push(names[i])));
  if (failed.length === names.length) throw new Error(`all news sites failed (${failed.join(", ")})`);
  items.failedSites = failed;
  return items;
}

export async function bingNews(query) {
  const res = await fetch(`https://www.bing.com/news/search?q=${encodeURIComponent(query)}&format=rss&qft=interval%3d%227%22`, {
    headers: { "User-Agent": UA },
  });
  if (!res.ok) throw new Error(`Bing News HTTP ${res.status}`);
  const items = parseFeed(await res.text(), "Bing News", null);
  for (const it of items) {
    it.source = "bing-news";
    // Bing wraps links: .../apiclick.aspx?...&url=<real link>
    try {
      const real = new URL(it.url).searchParams.get("url");
      if (real) it.url = real;
    } catch {}
  }
  return items;
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

export async function reddit(sub = "GTA6", clientId = "", clientSecret = "") {
  let base = "https://www.reddit.com";
  const headers = { "User-Agent": UA };
  if (clientId && clientSecret) {
    // free Reddit app login - Reddit blocks anonymous requests from cloud servers
    const tok = await fetch("https://www.reddit.com/api/v1/access_token", {
      method: "POST",
      headers: { ...headers, Authorization: `Basic ${btoa(`${clientId}:${clientSecret}`)}` },
      body: new URLSearchParams({ grant_type: "client_credentials" }),
    });
    if (!tok.ok) throw new Error(`Reddit login HTTP ${tok.status}`);
    headers.Authorization = `Bearer ${(await tok.json()).access_token}`;
    base = "https://oauth.reddit.com";
  }
  const res = await fetch(`${base}/r/${sub}/top.json?t=day&limit=30&raw_json=1`, { headers });
  if (!res.ok) {
    const hint = clientId ? "" : " - blocked for cloud servers; add REDDIT_CLIENT_ID/SECRET (see SCOUT.md)";
    throw new Error(`Reddit HTTP ${res.status}${hint}`);
  }
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
    "news-sites": () => newsSites(),
    "bing-news": () => bingNews('"GTA 6" OR "GTA VI"'),
    // useful guides: secrets, money, side missions
    "guides-secrets": () => bingNews('"GTA 6" (secrets OR "easter egg" OR hidden OR "you missed")'),
    "guides-money": () => bingNews('"GTA 6" ("make money" OR "money guide" OR "fast money" OR "best way to earn")'),
    "guides-missions": () => bingNews('"GTA 6" ("side missions" OR "side quests" OR "best missions" OR "tips")'),
    reddit: () => reddit("GTA6", env.REDDIT_CLIENT_ID, env.REDDIT_CLIENT_SECRET),
  };
  // Google News blocks Cloudflare most of the time; only try it if you turn it on.
  if (env.USE_GOOGLE_NEWS === "1") jobs["google-news"] = () => googleNews('"GTA 6" OR "GTA VI" when:1d');
  if (env.YOUTUBE_API_KEY) jobs.youtube = () => youtube(env.YOUTUBE_API_KEY, since);
  if (env.TWITCH_CLIENT_ID && env.TWITCH_CLIENT_SECRET) {
    jobs.twitch = () => twitch(env.TWITCH_CLIENT_ID, env.TWITCH_CLIENT_SECRET, since, env.TWITCH_GAME || undefined);
  }

  const names = Object.keys(jobs);
  const settled = await Promise.allSettled(names.map((n) => jobs[n]()));
  const items = [];
  const errors = {};
  settled.forEach((r, i) => {
    if (r.status === "fulfilled") {
      items.push(...r.value);
      if (r.value.failedSites?.length) errors[`${names[i]} (some)`] = `no answer from ${r.value.failedSites.join(", ")}`;
    } else errors[names[i]] = String(r.reason?.message || r.reason).slice(0, 300);
  });
  const skipped = [];
  if (!env.YOUTUBE_API_KEY) skipped.push("youtube (no YOUTUBE_API_KEY)");
  if (!env.TWITCH_CLIENT_ID) skipped.push("twitch (no TWITCH_CLIENT_ID)");
  return { items, errors, skipped, sources: names, twitch: Boolean(env.TWITCH_CLIENT_ID && env.TWITCH_CLIENT_SECRET) };
}
