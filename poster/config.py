"""All settings come from environment variables (GitHub Secrets in the cloud,
or a local .env file on your PC). Nothing secret is ever stored in the code."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

ALL_PLATFORMS = ("youtube", "instagram", "tiktok")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def load_dotenv(path: str = ".env") -> None:
    """Tiny .env loader so you don't need extra packages on your PC."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass
class Config:
    # Google (one login covers YouTube + Google Drive)
    google_client_id: str = ""
    google_client_secret: str = ""
    google_refresh_token: str = ""
    youtube_privacy: str = "public"  # public | unlisted | private
    youtube_category: str = "20"  # 20 = Gaming
    drive_root_folder: str = "Viceverified"

    # Instagram
    ig_user_id: str = ""
    ig_access_token: str = ""
    ig_graph_host: str = "graph.instagram.com"
    ig_api_version: str = "v21.0"

    # Cloudflare R2 (Instagram needs the video at a public link for a moment)
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket: str = ""
    r2_public_base_url: str = ""

    # TikTok
    tiktok_client_key: str = ""
    tiktok_client_secret: str = ""
    tiktok_refresh_token: str = ""
    tiktok_mode: str = "direct"  # direct = post it, inbox = send as draft to your TikTok app
    tiktok_privacy: str = "PUBLIC_TO_EVERYONE"

    # Qwen on Cloudflare Workers AI (writes titles/captions/hashtags)
    cf_account_id: str = ""
    cf_api_token: str = ""
    qwen_model: str = "@cf/qwen/qwen3.8-27b"

    # Your Scout Worker keeps the Poster's token memory when Google Drive isn't connected
    scout_url: str = "https://viceverified-scout.vicevinnybeats.workers.dev"
    scout_key: str = ""

    platforms: list[str] = field(default_factory=lambda: list(ALL_PLATFORMS))
    max_per_run: int = 3
    max_attempts: int = 3

    @classmethod
    def from_env(cls) -> "Config":
        platforms = [p.strip().lower() for p in _env("POSTER_PLATFORMS", ",".join(ALL_PLATFORMS)).split(",") if p.strip()]
        return cls(
            google_client_id=_env("GOOGLE_CLIENT_ID"),
            google_client_secret=_env("GOOGLE_CLIENT_SECRET"),
            google_refresh_token=_env("GOOGLE_REFRESH_TOKEN"),
            youtube_privacy=_env("YOUTUBE_PRIVACY", "public"),
            youtube_category=_env("YOUTUBE_CATEGORY", "20"),
            drive_root_folder=_env("DRIVE_ROOT_FOLDER", "Viceverified"),
            ig_user_id=_env("IG_USER_ID"),
            ig_access_token=_env("IG_ACCESS_TOKEN"),
            ig_graph_host=_env("IG_GRAPH_HOST", "graph.instagram.com"),
            ig_api_version=_env("IG_API_VERSION", "v21.0"),
            r2_account_id=_env("R2_ACCOUNT_ID") or _env("CF_ACCOUNT_ID"),
            r2_access_key_id=_env("R2_ACCESS_KEY_ID"),
            r2_secret_access_key=_env("R2_SECRET_ACCESS_KEY"),
            r2_bucket=_env("R2_BUCKET"),
            r2_public_base_url=_env("R2_PUBLIC_BASE_URL").rstrip("/"),
            tiktok_client_key=_env("TIKTOK_CLIENT_KEY"),
            tiktok_client_secret=_env("TIKTOK_CLIENT_SECRET"),
            tiktok_refresh_token=_env("TIKTOK_REFRESH_TOKEN"),
            tiktok_mode=_env("TIKTOK_MODE", "direct").lower(),
            tiktok_privacy=_env("TIKTOK_PRIVACY", "PUBLIC_TO_EVERYONE"),
            cf_account_id=_env("CF_ACCOUNT_ID"),
            cf_api_token=_env("CF_API_TOKEN"),
            qwen_model=_env("QWEN_MODEL", "@cf/qwen/qwen3.8-27b"),
            scout_url=_env("SCOUT_URL", "https://viceverified-scout.vicevinnybeats.workers.dev"),
            scout_key=_env("SCOUT_KEY"),
            platforms=[p for p in platforms if p in ALL_PLATFORMS],
            max_per_run=int(_env("POSTER_MAX_PER_RUN", "3") or 3),
            max_attempts=int(_env("POSTER_MAX_ATTEMPTS", "3") or 3),
        )

    # --- what is set up? -------------------------------------------------
    @property
    def has_google(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret and self.google_refresh_token)

    @property
    def has_instagram(self) -> bool:
        # the video link comes from your Scout (free) or, if set up, Cloudflare R2
        return bool(self.ig_user_id and self.ig_access_token and (self.has_r2 or self.scout_key))

    @property
    def has_r2(self) -> bool:
        return bool(self.r2_account_id and self.r2_access_key_id and self.r2_secret_access_key
                    and self.r2_bucket and self.r2_public_base_url)

    @property
    def has_tiktok(self) -> bool:
        # the refresh token may also come from the Scout's "Log in with TikTok" page (saved memory)
        return bool(self.tiktok_client_key and self.tiktok_client_secret
                    and (self.tiktok_refresh_token or self.scout_key))

    @property
    def has_qwen(self) -> bool:
        return bool(self.cf_account_id and self.cf_api_token)

    def configured(self, platform: str) -> bool:
        return {
            "youtube": self.has_google,
            "instagram": self.has_instagram,
            "tiktok": self.has_tiktok,
        }[platform]
