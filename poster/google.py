"""Google login (refresh token -> access token) and a small Google Drive client."""

from __future__ import annotations

import json
import os

import requests

from .config import Config
from .http import TIMEOUT, UPLOAD_TIMEOUT, PostError, check

TOKEN_URL = "https://oauth2.googleapis.com/token"
DRIVE = "https://www.googleapis.com/drive/v3"
DRIVE_UPLOAD = "https://www.googleapis.com/upload/drive/v3"
FOLDER_MIME = "application/vnd.google-apps.folder"
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/drive",
]


def access_token(cfg: Config) -> str:
    resp = requests.post(TOKEN_URL, data={
        "client_id": cfg.google_client_id,
        "client_secret": cfg.google_client_secret,
        "refresh_token": cfg.google_refresh_token,
        "grant_type": "refresh_token",
    }, timeout=TIMEOUT)
    check(resp, "Google login")
    return resp.json()["access_token"]


def _q(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


class Drive:
    def __init__(self, token: str):
        self.h = {"Authorization": f"Bearer {token}"}

    def list_children(self, folder_id: str, extra_q: str = "") -> list[dict]:
        files, page = [], None
        q = f"'{folder_id}' in parents and trashed = false" + (f" and {extra_q}" if extra_q else "")
        while True:
            params = {"q": q, "fields": "nextPageToken, files(id, name, mimeType, size, modifiedTime)",
                      "pageSize": 200, "orderBy": "modifiedTime"}
            if page:
                params["pageToken"] = page
            resp = check(requests.get(f"{DRIVE}/files", headers=self.h, params=params, timeout=TIMEOUT), "Drive list")
            data = resp.json()
            files += data.get("files", [])
            page = data.get("nextPageToken")
            if not page:
                return files

    def find(self, name: str, parent: str, folder: bool | None = None) -> dict | None:
        q = f"name = '{_q(name)}'"
        if folder is True:
            q += f" and mimeType = '{FOLDER_MIME}'"
        hits = self.list_children(parent, q)
        return hits[0] if hits else None

    def ensure_folder(self, name: str, parent: str = "root") -> str:
        hit = self.find(name, parent, folder=True)
        if hit:
            return hit["id"]
        resp = requests.post(f"{DRIVE}/files", headers=self.h, timeout=TIMEOUT,
                             json={"name": name, "mimeType": FOLDER_MIME, "parents": [parent]})
        return check(resp, "Drive create folder").json()["id"]

    def download(self, file_id: str, dest: str) -> str:
        with requests.get(f"{DRIVE}/files/{file_id}", headers=self.h, params={"alt": "media"},
                          stream=True, timeout=UPLOAD_TIMEOUT) as resp:
            check(resp, "Drive download")
            with open(dest, "wb") as f:
                for chunk in resp.iter_content(1024 * 1024):
                    f.write(chunk)
        return dest

    def read_text(self, file_id: str) -> str:
        resp = requests.get(f"{DRIVE}/files/{file_id}", headers=self.h, params={"alt": "media"}, timeout=TIMEOUT)
        return check(resp, "Drive read").content.decode("utf-8-sig")

    def write_text(self, name: str, parent: str, text: str, file_id: str | None = None,
                   mime: str = "application/json") -> str:
        data = text.encode("utf-8")
        if file_id:
            resp = requests.patch(f"{DRIVE_UPLOAD}/files/{file_id}", params={"uploadType": "media"},
                                  headers={**self.h, "Content-Type": mime}, data=data, timeout=TIMEOUT)
            return check(resp, "Drive update").json()["id"]
        boundary = "viceverified-boundary"
        meta = json.dumps({"name": name, "parents": [parent]})
        body = (
            f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{meta}\r\n"
            f"--{boundary}\r\nContent-Type: {mime}\r\n\r\n"
        ).encode() + data + f"\r\n--{boundary}--".encode()
        resp = requests.post(f"{DRIVE_UPLOAD}/files", params={"uploadType": "multipart"},
                             headers={**self.h, "Content-Type": f"multipart/related; boundary={boundary}"},
                             data=body, timeout=TIMEOUT)
        return check(resp, "Drive upload").json()["id"]

    def upload_file(self, path: str, parent: str, mime: str = "video/mp4") -> str:
        size = os.path.getsize(path)
        init = requests.post(f"{DRIVE_UPLOAD}/files", params={"uploadType": "resumable"},
                             headers={**self.h, "X-Upload-Content-Type": mime, "X-Upload-Content-Length": str(size)},
                             json={"name": os.path.basename(path), "parents": [parent]}, timeout=TIMEOUT)
        loc = check(init, "Drive upload start").headers.get("Location")
        if not loc:
            raise PostError("Drive did not return an upload link")
        with open(path, "rb") as f:
            resp = requests.put(loc, data=f, headers={"Content-Type": mime, "Content-Length": str(size)},
                                timeout=UPLOAD_TIMEOUT)
        return check(resp, "Drive upload").json()["id"]

    def move(self, file_id: str, new_parent: str, old_parent: str) -> None:
        resp = requests.patch(f"{DRIVE}/files/{file_id}", headers=self.h, timeout=TIMEOUT,
                              params={"addParents": new_parent, "removeParents": old_parent, "fields": "id"})
        check(resp, "Drive move")
