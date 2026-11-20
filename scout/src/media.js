// Temporary public links for videos (Instagram downloads the video from a link).
// Stored in Workers KV (free, no credit card). KV values max out at 25 MB, so videos
// are split into 20 MB pieces and joined again when served. Links expire after 2 days.
//
//   PUT    /api/media/<name>   upload a video (needs SCOUT_KEY)
//   DELETE /api/media/<name>   remove it      (needs SCOUT_KEY)
//   GET    /media/<name>       public link Instagram downloads from

export const CHUNK = 20 * 1024 * 1024;
export const MAX_BYTES = 95 * 1024 * 1024;
const TTL = 2 * 24 * 3600;
export const NAME_RE = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,120}\.(mp4|mov|jpg|png)$/;

const TYPES = { mp4: "video/mp4", mov: "video/quicktime", jpg: "image/jpeg", png: "image/png" };

export async function putMedia(env, name, body) {
  const bytes = new Uint8Array(body);
  if (!bytes.length) throw new Error("empty upload");
  if (bytes.length > MAX_BYTES) throw new Error("file too big (max 95 MB)");
  const parts = Math.ceil(bytes.length / CHUNK);
  for (let i = 0; i < parts; i++) {
    await env.MEDIA.put(`media:${name}:${i}`, bytes.subarray(i * CHUNK, (i + 1) * CHUNK), { expirationTtl: TTL });
  }
  const ext = name.split(".").pop().toLowerCase();
  const meta = { parts, size: bytes.length, type: TYPES[ext] || "application/octet-stream" };
  await env.MEDIA.put(`media:${name}`, JSON.stringify(meta), { expirationTtl: TTL });
  return meta;
}

export async function deleteMedia(env, name) {
  const meta = await env.MEDIA.get(`media:${name}`, "json");
  if (!meta) return false;
  for (let i = 0; i < meta.parts; i++) await env.MEDIA.delete(`media:${name}:${i}`);
  await env.MEDIA.delete(`media:${name}`);
  return true;
}

export async function serveMedia(env, name, method = "GET") {
  const meta = await env.MEDIA.get(`media:${name}`, "json");
  if (!meta) return new Response("not found", { status: 404 });
  const headers = {
    "Content-Type": meta.type,
    "Content-Length": String(meta.size),
    "Cache-Control": "no-store",
    "Accept-Ranges": "none",
  };
  if (method === "HEAD") return new Response(null, { headers });
  let i = 0;
  const stream = new ReadableStream({
    async pull(controller) {
      if (i >= meta.parts) return controller.close();
      const piece = await env.MEDIA.get(`media:${name}:${i++}`, "arrayBuffer");
      if (!piece) return controller.error(new Error("piece missing"));
      controller.enqueue(new Uint8Array(piece));
    },
  });
  return new Response(stream, { headers });
}
