"""Company-isolated document storage with a production S3 adapter."""
from __future__ import annotations

import os
from typing import Optional


def _bucket() -> str:
    return os.environ.get("OBJECT_STORAGE_BUCKET", "")


def _object_key(company_id: str, stored_name: str) -> str:
    return f"companies/{company_id}/documents/{stored_name}"


def _s3_client():
    try:
        import boto3
    except ImportError as exc:
        raise RuntimeError("S3 document storage requires boto3") from exc
    endpoint = os.environ.get("OBJECT_STORAGE_ENDPOINT_URL") or None
    return boto3.client("s3", endpoint_url=endpoint)


def validate_production_config() -> None:
    if os.environ.get("APP_ENV", "development").lower() == "production" and not _bucket():
        raise RuntimeError("OBJECT_STORAGE_BUCKET is required for production document storage")


def put(root: str, company_id: str, stored_name: str, content: bytes, content_type: str) -> None:
    validate_production_config()
    if _bucket():
        _s3_client().put_object(Bucket=_bucket(), Key=_object_key(company_id, stored_name), Body=content,
                                ContentType=content_type, ServerSideEncryption="AES256")
        return
    os.makedirs(root, exist_ok=True)
    path = os.path.join(root, stored_name)
    with open(path, "wb") as handle:
        handle.write(content)
    os.chmod(path, 0o600)


def get(root: str, company_id: str, stored_name: str) -> bytes:
    validate_production_config()
    if _bucket():
        return _s3_client().get_object(Bucket=_bucket(), Key=_object_key(company_id, stored_name))["Body"].read()
    with open(os.path.join(root, stored_name), "rb") as handle:
        return handle.read()


def local_path(root: str, stored_name: str) -> Optional[str]:
    if _bucket(): return None
    return os.path.join(root, stored_name)
