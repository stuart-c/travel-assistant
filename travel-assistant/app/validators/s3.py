"""Validator for AWS S3 bucket and credentials (delegates to TrainS3Client)."""

from typing import Optional, Tuple

from app.datasources.train_s3 import DEFAULT_S3_REGION, TrainS3Client


def validate_train_s3_bucket(
    bucket: str,
    region: Optional[str] = None,
    access_key: Optional[str] = None,
    secret_key: Optional[str] = None,
    timeout: float = 5.0,
) -> Tuple[bool, str]:
    """Validate AWS S3 bucket configuration and credentials by checking bucket existence.

    Args:
        bucket: The S3 bucket name.
        region: AWS region (e.g. eu-west-2).
        access_key: Optional AWS Access Key ID.
        secret_key: Optional AWS Secret Access Key.
        timeout: Request timeout in seconds.

    Returns:
        Tuple of (is_valid, message).
    """
    client = TrainS3Client(
        bucket_name=bucket,
        region=region or DEFAULT_S3_REGION,
        access_key=access_key,
        secret_key=secret_key,
        timeout=timeout,
    )
    return client.validate_tuple()


__all__ = ["validate_train_s3_bucket"]
