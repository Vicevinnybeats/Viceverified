"""Let your Qwen 3 on Cloudflare Workers AI write the hook, description and hashtags.

Uses the free Workers AI REST API. If Qwen is not set up (or fails), the
poster still works with your own title + default GTA hashtags."""

from __future__ import annotations

import json
import re

import requests

from .config import Config
from .http import TIMEOUT, check
from .meta import Meta, normalize_hashtags

DEFAULT_HASHTAGS = ["#gta6", "#gta", "#gtavi", "#gaming", "#shorts"]

SYSTEM = (
    "You write short-form video captions for a GTA 6 news and clips channel. "
    "Be punchy, no clickbait lies, no emojis spam (max 2). Reply with JSON only."
)

PROMPT = """Video title: {title}
Notes: {description}

Return JSON exactly like:
{{"youtube_title": "max 70 chars, hooky", "caption": "1-2 sentence hook for TikTok/Instagram",
"description": "2-3 sentences for YouTube", "hashtags": ["#gta6", "... 8 to 12 total"]}}
/no_think"""


def _extract_text(payload: dict) -> str:
    result = payload.get("result", payload)
    if isinstance(result, dict):
        resp = result.get("response")
        if isinstance(resp, (dict, list)):
            return json.dumps(resp)
        if isinstance(resp, str):
            return resp
        choices = result.get("choices")
        if choices:
            return choices[0].get("message", {}).get("content", "") or ""
    return str(result)


def parse_ai_json(text: str) -> dict:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    match = re.search(r"\{.*\}", text, flags=re.S)
    if not match:
        raise ValueError("no JSON in model answer")
    return json.loads(match.group(0))


def ask_qwen(cfg: Config, meta: Meta) -> dict:
    url = f"https://api.cloudflare.com/client/v4/accounts/{cfg.cf_account_id}/ai/run/{cfg.qwen_model}"
    body = {
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": PROMPT.format(title=meta.title, description=meta.description or "-")},
        ],
        "max_tokens": 700,
    }
    resp = requests.post(url, headers={"Authorization": f"Bearer {cfg.cf_api_token}"}, json=body, timeout=TIMEOUT)
    check(resp, "Qwen (Workers AI)")
    return parse_ai_json(_extract_text(resp.json()))


def enrich(cfg: Config, meta: Meta, log=print) -> Meta:
    """Fill in missing description/hashtags/captions. Never overwrites what you wrote."""
    if meta.needs_ai and cfg.has_qwen:
        try:
            ai = ask_qwen(cfg, meta)
            meta.youtube_title = meta.youtube_title or str(ai.get("youtube_title") or "").strip()
            meta.caption = meta.caption or str(ai.get("caption") or "").strip()
            meta.description = meta.description or str(ai.get("description") or "").strip()
            if not meta.hashtags:
                meta.hashtags = normalize_hashtags(ai.get("hashtags") or [])
            log("  Qwen wrote the captions.")
        except Exception as exc:  # captions are nice-to-have, never block posting
            log(f"  Qwen captions skipped: {exc}")
    if not meta.hashtags:
        meta.hashtags = list(DEFAULT_HASHTAGS)
    elif "#gta6" not in [t.lower() for t in meta.hashtags]:
        meta.hashtags.insert(0, "#gta6")
    return meta
