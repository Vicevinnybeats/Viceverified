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
    # KittenTTS: Apache-2.0 licence, 80 MB, real-time on a normal CPU, 8 English voices
    # (expr-voice-2..5, -m male / -f female)
    voicestudio_model: str = "kittentts"
    voicestudio_voice: str = "expr-voice-3-m"
    voicestudio_install: str = "KittenML/kitten-tts-mini-0.8"
    voicestudio_accept: str = "KittenML/kitten-tts-mini-0.8"
    voice_speed: float = 1.08

    news_per_run: int = 2   # useful guide/secret/money Shorts
    clips_per_run: int = 0  # stream clips off by default (set CLIPS_PER_RUN to turn on)
    min_news_score: int = 65
    min_clip_score: int = 55
    clip_streamers: list[str] = field(default_factory=list)  # empty = any streamer
    clip_language: str = "en"  # only clips in this language ("" = any)
    clip_allow: tuple = ("allowed", "ask")  # clip_rules.json rules we clip (add "unknown" to clip anyone)
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
            voicestudio_model=_env("VOICESTUDIO_MODEL", "kittentts"),
            voicestudio_voice=_env("VOICESTUDIO_VOICE", "expr-voice-3-m"),
            voicestudio_install=_env("VOICESTUDIO_INSTALL", "KittenML/kitten-tts-mini-0.8"),
            voicestudio_accept=_env("VOICESTUDIO_ACCEPT_LICENSE", "KittenML/kitten-tts-mini-0.8"),
            voice_speed=float(_env("VOICE_SPEED", "1.08")),
            news_per_run=int(_env("NEWS_PER_RUN", "2")),
            clips_per_run=int(_env("CLIPS_PER_RUN", "0")),
            min_news_score=int(_env("MIN_NEWS_SCORE", "65")),
            min_clip_score=int(_env("MIN_CLIP_SCORE", "55")),
            clip_streamers=streamers,
            clip_language=_env("CLIP_LANGUAGE", "en").lower()[:2],
            clip_allow=tuple(r.strip().lower() for r in _env("CLIP_ALLOW", "allowed,ask").split(",") if r.strip()),
            use_article_image=_env("USE_ARTICLE_IMAGE", "1") != "0",
            out_dir=_env("OUT_DIR", "out"),
            fonts_dir=_env("FONTS_DIR", "maker/fonts"),
        )
