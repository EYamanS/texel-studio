"""
Texel Studio — File storage abstraction.

Uses S3-compatible object storage when configured (Railway Object Store, AWS S3, etc.)
Falls back to local filesystem for self-hosted / local dev.

Railway Object Store env vars: ACCESS_KEY_ID, SECRET_ACCESS_KEY, ENDPOINT, BUCKET
"""

import os
import io
from pathlib import Path

_s3 = None
_bucket = None

def _get_s3():
    global _s3, _bucket
    if _s3 is not None:
        return _s3, _bucket

    endpoint = os.getenv("ENDPOINT")
    access_key = os.getenv("ACCESS_KEY_ID")
    secret_key = os.getenv("SECRET_ACCESS_KEY")
    bucket = os.getenv("BUCKET")

    if not all([endpoint, access_key, secret_key, bucket]):
        return None, None

    import boto3
    _s3 = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )
    _bucket = bucket
    return _s3, _bucket


# Local filesystem paths (used as fallback)
BASE_DIR = Path(__file__).parent
LOCAL_OUTPUT = BASE_DIR / "output"
LOCAL_REFS = BASE_DIR / "references"
LOCAL_OUTPUT.mkdir(exist_ok=True)
LOCAL_REFS.mkdir(exist_ok=True)


def save_file(path: str, data: bytes) -> None:
    """Save file to storage. path like 'output/gen_1_16x16.png' or 'references/ref_xxx.png'"""
    s3, bucket = _get_s3()
    if s3:
        s3.put_object(Bucket=bucket, Key=path, Body=data, ContentType="image/png")
    else:
        full = BASE_DIR / path
        full.parent.mkdir(exist_ok=True)
        full.write_bytes(data)


def read_file(path: str) -> bytes | None:
    """Read file from storage. Returns None if not found."""
    s3, bucket = _get_s3()
    if s3:
        try:
            resp = s3.get_object(Bucket=bucket, Key=path)
            return resp["Body"].read()
        except s3.exceptions.NoSuchKey:
            return None
        except Exception:
            return None
    else:
        full = BASE_DIR / path
        if full.exists():
            return full.read_bytes()
        return None


def save_image(img, path: str) -> None:
    """Save a PIL Image to storage."""
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    save_file(path, buf.getvalue())


def file_exists(path: str) -> bool:
    """Check if a file exists in storage."""
    s3, bucket = _get_s3()
    if s3:
        try:
            s3.head_object(Bucket=bucket, Key=path)
            return True
        except Exception:
            return False
    else:
        return (BASE_DIR / path).exists()
