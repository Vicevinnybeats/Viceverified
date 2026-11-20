"""Twitch Helix API: top clips (already highlights picked by viewers) and VODs.

Free: needs a Twitch developer app (TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET)."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import requests

HELIX = "https://api.twitch.tv/helix"
GTA6 = "Grand Theft Auto VI"


class Twitch:
    def __init__(self, client_id: str | None = None, client_secret: str | None = None):
        self.client_id = client_id or os.environ.get("TWITCH_CLIENT_ID", "")
        secret = client_secret or os.environ.get("TWITCH_CLIENT_SECRET", "")
        if not (self.client_id and secret):
            raise RuntimeError("TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET are missing")
        tok = requests.post("https://id.twitch.tv/oauth2/token", timeout=30, data={
            "client_id": self.client_id, "client_secret": secret, "grant_type": "client_credentials"})
        tok.raise_for_status()
        self.h = {"Client-Id": self.client_id, "Authorization": f"Bearer {tok.json()['access_token']}"}

    def _get(self, path: str, **params) -> list[dict]:
        r = requests.get(f"{HELIX}/{path}", headers=self.h, params=params, timeout=30)
        r.raise_for_status()
        return r.json().get("data", [])

    def user(self, login: str) -> dict | None:
        users = self._get("users", login=login.lower())
        return users[0] if users else None

    def game_id(self, name: str = GTA6) -> str | None:
        games = self._get("games", name=name)
        return games[0]["id"] if games else None

    def top_clips(self, broadcaster_id: str | None = None, game_id: str | None = None,
                  hours: int = 48, first: int = 20) -> list[dict]:
        """Most-viewed clips first (Twitch sorts by views)."""
        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
        params = {"started_at": since, "first": first}
        if broadcaster_id:
            params["broadcaster_id"] = broadcaster_id
        elif game_id:
            params["game_id"] = game_id
        return self._get("clips", **params)

    def vods(self, user_id: str, first: int = 5) -> list[dict]:
        return self._get("videos", user_id=user_id, type="archive", first=first)


def parse_duration(text: str) -> int:
    """Twitch VOD duration like '3h12m5s' -> seconds."""
    total, num = 0, ""
    for ch in text or "":
        if ch.isdigit():
            num += ch
        elif ch in "hms" and num:
            total += int(num) * {"h": 3600, "m": 60, "s": 1}[ch]
            num = ""
    return total
