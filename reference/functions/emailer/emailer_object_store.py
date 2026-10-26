"""Small provider-neutral object storage boundary for the emailer."""

from __future__ import annotations

import os


VALID_PROVIDERS = {"supabase", "r2"}


class ObjectNotFoundError(FileNotFoundError):
    """Raised when an object does not exist in the configured provider."""


def storage_provider() -> str:
    provider = os.environ.get("OBJECT_STORAGE_PROVIDER", "supabase").strip().lower()
    if provider not in VALID_PROVIDERS:
        raise ValueError(f"Unsupported OBJECT_STORAGE_PROVIDER: {provider}")
    return provider


def r2_bucket(role: str) -> str:
    env_name = {
        "newspics": "R2_NEWSPICS_BUCKET",
        "artifacts": "R2_ARTIFACTS_BUCKET",
    }.get(role)
    if not env_name:
        raise ValueError(f"Unsupported storage bucket role: {role}")
    bucket = os.environ.get(env_name)
    if not bucket:
        raise ValueError(f"{env_name} must be set when OBJECT_STORAGE_PROVIDER=r2")
    return bucket


def _r2_client():
    endpoint = os.environ.get("R2_ENDPOINT")
    access_key = os.environ.get("R2_ACCESS_KEY_ID")
    secret_key = os.environ.get("R2_SECRET_ACCESS_KEY")
    if not endpoint or not access_key or not secret_key:
        raise ValueError(
            "R2_ENDPOINT, R2_ACCESS_KEY_ID, and R2_SECRET_ACCESS_KEY must be set "
            "when OBJECT_STORAGE_PROVIDER=r2"
        )

    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name="auto",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(
            connect_timeout=5,
            read_timeout=60,
            retries={"max_attempts": 4, "mode": "standard"},
        ),
    )


def get_bytes(*, bucket_role: str, key: str) -> bytes:
    try:
        response = _r2_client().get_object(Bucket=r2_bucket(bucket_role), Key=key)
    except Exception as exc:
        response_code = getattr(exc, "response", {}).get("Error", {}).get("Code")
        if response_code in {"NoSuchKey", "404", "NotFound"}:
            raise ObjectNotFoundError(f"R2 object not found: {bucket_role}/{key}") from exc
        raise
    return response["Body"].read()
