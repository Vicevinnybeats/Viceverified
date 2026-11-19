from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


@dataclass
class Config:
    scout_url: str = "https://viceverified-scout.vicevinnybeats.workers.dev"
    scout_key: str = ""

    # VoiceStudio (main voice). Empty URL = use the Cloudflare backup voice only.
    voicestudio_url: str = ""
    voicestudio_key: str = ""
    voicestudio_model: str = "tts-1"
    voicestudio_voice: str = "alloy"
    voice_speed: float = 1.08

    news_per_run: int = 1
    clips_per_run: int = 1
    min_news_score: int = 65
    min_clip_score: int = 55
    clip_streamers: list[str] = field(default_factory=list)  # empty = any streamer
    use_article_image: bool = True

    out_dir: str = "out"
    fonts_dir: str = "maker/fonts"

    @classmethod
    def from_env(cls) -> "Config":
        streamers = [s.strip().lower() for s in _env("CLIP_STREAMERS").split(",") if s.strip()]
        return cls(
            scout_url=_env("SCOUT_URL", cls.scout_url).rstrip("/"),
            scout_key=_env("SCOUT_KEY"),
            voicestudio_url=_env("VOICESTUDIO_URL").rstrip("/"),
            voicestudio_key=_env("VOICESTUDIO_KEY") or _env("OMNIVOICE_API_KEY"),
            voicestudio_model=_env("VOICESTUDIO_MODEL", "tts-1"),
            voicestudio_voice=_env("VOICESTUDIO_VOICE", "alloy"),
            voice_speed=float(_env("VOICE_SPEED", "1.08")),
            news_per_run=int(_env("NEWS_PER_RUN", "1")),
            clips_per_run=int(_env("CLIPS_PER_RUN", "1")),
            min_news_score=int(_env("MIN_NEWS_SCORE", "65")),
            min_clip_score=int(_env("MIN_CLIP_SCORE", "55")),
            clip_streamers=streamers,
            use_article_image=_env("USE_ARTICLE_IMAGE", "1") != "0",
            out_dir=_env("OUT_DIR", "out"),
            fonts_dir=_env("FONTS_DIR", "maker/fonts"),
        )
