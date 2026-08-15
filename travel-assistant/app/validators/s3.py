"""AWS S3 bucket credentials and connectivity validator."""

from typing import Optional, Tuple
import boto3
from botocore.config import Config
from botocore.exceptions import (
    ClientError,
    ConnectTimeoutError,
    EndpointConnectionError,
    BotoCoreError,
)


def validate_train_s3_bucket(
    bucket: str,
    region: Optional[str] = None,
    access_key: Optional[str] = None,
    secret_key: Optional[str] = None,
    timeout: float = 5.0,
) -> Tuple[bool, str]:
    """Validate AWS S3 bucket connectivity, existence, and permissions.

    Args:
        bucket: The name of the S3 bucket.
        region: AWS region name (e.g. eu-west-2).
        access_key: AWS access key ID.
        secret_key: AWS secret access key.
        timeout: Network timeout in seconds.

    Returns:
        A tuple of (is_valid, message).
    """
    cleaned_bucket = (bucket or "").strip()
    if not cleaned_bucket:
        return False, "S3 bucket name is required."

    cleaned_region = (region or "").strip() or "eu-west-2"
    cleaned_access = (access_key or "").strip() or None
    cleaned_secret = (secret_key or "").strip() or None

    try:
        session = boto3.Session(
            aws_access_key_id=cleaned_access,
            aws_secret_access_key=cleaned_secret,
            region_name=cleaned_region,
        )
        s3 = session.client(
            "s3",
            config=Config(
                connect_timeout=timeout,
                read_timeout=timeout,
                retries={"max_attempts": 1},
            ),
        )
        s3.head_bucket(Bucket=cleaned_bucket)
        return True, f"S3 bucket '{cleaned_bucket}' is valid and accessible."
    except ClientError as exc:
        error_code = str(exc.response.get("Error", {}).get("Code", ""))
        if error_code in ("404", "NoSuchBucket", "NotFound"):
            return False, f"S3 bucket '{cleaned_bucket}' does not exist (404)."
        if error_code in ("403", "AccessDenied"):
            return (
                False,
                f"Access denied for S3 bucket '{cleaned_bucket}' (403). Check credentials.",
            )
        if error_code in ("301", "PermanentRedirect"):
            return (
                False,
                f"S3 bucket '{cleaned_bucket}' exists in a different region.",
            )
        error_msg = exc.response.get("Error", {}).get("Message", str(exc))
        return False, f"S3 bucket error ({error_code}): {error_msg}"
    except ConnectTimeoutError:
        return False, "Connection timed out connecting to AWS S3."
    except EndpointConnectionError:
        return False, "Unable to connect to AWS S3 endpoint."
    except BotoCoreError as exc:
        return False, f"AWS S3 error: {str(exc)}"
    except Exception as exc:
        return False, f"S3 validation error: {str(exc)}"
