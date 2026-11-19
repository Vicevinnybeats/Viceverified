from __future__ import annotations

import requests

TIMEOUT = 60
UPLOAD_TIMEOUT = 600


class PostError(RuntimeError):
    """A platform refused the request. The message includes the platform's answer."""


def check(resp: requests.Response, what: str) -> requests.Response:
    if resp.status_code >= 400:
        body = resp.text[:800]
        raise PostError(f"{what} failed (HTTP {resp.status_code}): {body}")
    return resp
