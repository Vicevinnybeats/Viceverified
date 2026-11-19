"""Cloudflare R2 (free 10 GB) - a temporary public parking spot for Instagram."""

from __future__ import annotations

import os
import uuid

from .config import Config


def _client(cfg: Config):
    import boto3  # only needed when Instagram is used

    return boto3.client(
        "s3",
        endpoint_url=f"https://{cfg.r2_account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=cfg.r2_access_key_id,
        aws_secret_access_key=cfg.r2_secret_access_key,
        region_name="auto",
    )


def upload(cfg: Config, path: str) -> tuple[str, str]:
    key = f"poster-tmp/{uuid.uuid4().hex}{os.path.splitext(path)[1] or '.mp4'}"
    _client(cfg).upload_file(path, cfg.r2_bucket, key, ExtraArgs={"ContentType": "video/mp4"})
    return key, f"{cfg.r2_public_base_url}/{key}"


def delete(cfg: Config, key: str) -> None:
    try:
        _client(cfg).delete_object(Bucket=cfg.r2_bucket, Key=key)
    except Exception as exc:  # leftover temp file is harmless
        print(f"  (could not delete temp file {key} from R2: {exc})")
