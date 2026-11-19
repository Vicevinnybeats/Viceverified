"""Video info: title, description, hashtags - and the caption each platform gets."""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field

HASHTAG_RE = re.compile(r"#[\w\d_]+", re.UNICODE)

YT_TITLE_MAX = 100
IG_CAPTION_MAX = 2200
IG_MAX_HASHTAGS = 30
TIKTOK_CAPTION_MAX = 2200


@dataclass
class Meta:
    title: str
    description: str = ""
    hashtags: list[str] = field(default_factory=list)
    platforms: list[str] | None = None
    # Optional exact captions per platform; filled by Qwen or by you.
    youtube_title: str = ""
    caption: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Meta":
        tags = d.get("hashtags") or []
        if isinstance(tags, str):
            tags = tags.split()
        return cls(
            title=str(d.get("title") or "").strip(),
            description=str(d.get("description") or "").strip(),
            hashtags=normalize_hashtags(tags),
            platforms=[p.lower() for p in d["platforms"]] if d.get("platforms") else None,
            youtube_title=str(d.get("youtube_title") or "").strip(),
            caption=str(d.get("caption") or "").strip(),
        )

    @property
    def needs_ai(self) -> bool:
        return not self.description or not self.hashtags


def normalize_hashtags(tags) -> list[str]:
    out: list[str] = []
    for t in tags:
        t = str(t).strip().replace(" ", "")
        if not t:
            continue
        if not t.startswith("#"):
            t = "#" + t
        if t.lower() not in [x.lower() for x in out]:
            out.append(t)
    return out


def title_from_filename(name: str) -> str:
    stem = os.path.splitext(os.path.basename(name))[0]
    stem = re.sub(r"[_\-]+", " ", stem).strip()
    return stem[:1].upper() + stem[1:] if stem else "GTA 6"


def parse_sidecar(filename: str, text: str, video_name: str) -> Meta:
    """A sidecar is a .json or .txt file with the same name as the video.

    .json: {"title": "...", "description": "...", "hashtags": ["gta6"], "platforms": ["youtube"]}
    .txt:  first line = title, the rest = description (hashtags inside are picked up).
    """
    if filename.lower().endswith(".json"):
        meta = Meta.from_dict(json.loads(text))
    else:
        lines = text.strip().splitlines()
        title = lines[0].strip() if lines else ""
        rest = "\n".join(lines[1:]).strip()
        tags = HASHTAG_RE.findall(rest)
        desc = HASHTAG_RE.sub("", rest).strip()
        meta = Meta(title=title, description=desc, hashtags=normalize_hashtags(tags))
    if not meta.title:
        meta.title = title_from_filename(video_name)
    return meta


def _trim(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def youtube_fields(meta: Meta) -> tuple[str, str, list[str]]:
    title = meta.youtube_title or meta.title
    if "#shorts" not in title.lower() and len(title) + 8 <= YT_TITLE_MAX:
        title = f"{title} #Shorts"
    title = _trim(title, YT_TITLE_MAX)
    tags = meta.hashtags[:15]
    desc_tags = " ".join(tags + ([] if any(t.lower() == "#shorts" for t in tags) else ["#Shorts"]))
    description = _trim(f"{meta.description}\n\n{desc_tags}".strip(), 5000)
    plain_tags = [t.lstrip("#") for t in meta.hashtags][:15]
    return title, description, plain_tags


def instagram_caption(meta: Meta) -> str:
    body = meta.caption or "\n\n".join(x for x in (meta.title, meta.description) if x)
    tags = " ".join(meta.hashtags[:IG_MAX_HASHTAGS])
    return _trim(f"{body}\n\n{tags}".strip(), IG_CAPTION_MAX)


def tiktok_caption(meta: Meta) -> str:
    body = meta.caption or meta.title
    tags = " ".join(meta.hashtags[:10])
    return _trim(f"{body} {tags}".strip(), TIKTOK_CAPTION_MAX)
