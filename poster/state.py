"""Remembers tokens that platforms rotate (TikTok refresh token, Instagram token).

GitHub Secrets can't update themselves, so the newest token is kept in
Google Drive (Viceverified/_poster/state.json) or in a local file. If you
paste a NEW token into your secrets, that one wins automatically."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Callable


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:16]


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class State:
    def __init__(self, load: Callable[[], str | None], save: Callable[[str], None]):
        self._save = save
        raw = load()
        self.data: dict = json.loads(raw) if raw else {}
        self.dirty = False

    def token(self, name: str, env_value: str) -> str:
        entry = self.data.get(name) or {}
        if entry.get("env_hash") == _hash(env_value or "") and entry.get("value"):
            return entry["value"]
        return env_value

    def updated_at(self, name: str, env_value: str) -> str:
        entry = self.data.get(name) or {}
        return entry.get("updated", "") if entry.get("env_hash") == _hash(env_value) else ""

    def set_token(self, name: str, env_value: str, value: str) -> None:
        self.data[name] = {"env_hash": _hash(env_value), "value": value, "updated": now_iso()}
        self.dirty = True

    def save(self) -> None:
        if self.dirty:
            self._save(json.dumps(self.data, indent=2))
            self.dirty = False


def local_state(path: str = ".poster-state.json") -> State:
    def load():
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return f.read()
        return None

    def save(text: str):
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    return State(load, save)


def drive_state(drive, folder_id: str, name: str = "state.json") -> State:
    holder: dict = {}

    def load():
        hit = drive.find(name, folder_id)
        if hit:
            holder["id"] = hit["id"]
            return drive.read_text(hit["id"])
        return None

    def save(text: str):
        holder["id"] = drive.write_text(name, folder_id, text, holder.get("id"))

    return State(load, save)


def scout_state(url: str, key: str, name: str = "poster") -> State:
    """Memory kept in your Scout Worker (Cloudflare D1) - works without Google Drive."""
    import requests

    endpoint = f"{url.rstrip('/')}/api/state/{name}"
    headers = {"Authorization": f"Bearer {key}"}

    def load():
        r = requests.get(endpoint, headers=headers, timeout=30)
        r.raise_for_status()
        return r.text if r.text.strip() not in ("", "{}") else None

    def save(text: str):
        requests.put(endpoint, data=text.encode(), headers={**headers, "Content-Type": "application/json"},
                     timeout=30).raise_for_status()

    return State(load, save)
