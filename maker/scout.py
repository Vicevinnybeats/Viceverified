"""Talks to your Scout Worker: what to make, scripts, backup voice, captions, mark as used."""

from __future__ import annotations

import requests

from .config import Config

TIMEOUT = 120


class ScoutError(RuntimeError):
    pass


class Scout:
    def __init__(self, cfg: Config):
        self.url = cfg.scout_url
        self.h = {"Authorization": f"Bearer {cfg.scout_key}"}

    def _check(self, r: requests.Response, what: str) -> requests.Response:
        if r.status_code >= 400:
            raise ScoutError(f"Scout {what} failed (HTTP {r.status_code}): {r.text[:300]}")
        return r

    def items(self, hours: int = 36) -> list[dict]:
        r = requests.get(f"{self.url}/api/items", params={"hours": hours, "status": "new"}, timeout=TIMEOUT)
        return self._check(r, "items").json().get("items", [])

    def write(self, payload: dict) -> dict:
        r = requests.post(f"{self.url}/api/write", json=payload, headers=self.h, timeout=TIMEOUT)
        return self._check(r, "script").json()

    def tts(self, text: str) -> bytes:
        r = requests.post(f"{self.url}/api/tts", json={"text": text}, headers=self.h, timeout=TIMEOUT)
        self._check(r, "voice")
        if not r.content:
            raise ScoutError("Scout voice returned no audio")
        return r.content

    def transcribe(self, audio_path: str) -> dict:
        with open(audio_path, "rb") as f:
            r = requests.post(f"{self.url}/api/transcribe", data=f.read(),
                              headers={**self.h, "Content-Type": "audio/mpeg"}, timeout=TIMEOUT)
        return self._check(r, "captions").json()

    def mark(self, item_id: str, status: str) -> None:
        r = requests.post(f"{self.url}/api/items/{item_id}", json={"status": status}, headers=self.h, timeout=TIMEOUT)
        self._check(r, "mark")

    def notify(self, text: str) -> None:
        """Sends a message to your Telegram/Discord through the Scout."""
        r = requests.post(f"{self.url}/api/notify", json={"text": text}, headers=self.h, timeout=TIMEOUT)
        self._check(r, "notify")
