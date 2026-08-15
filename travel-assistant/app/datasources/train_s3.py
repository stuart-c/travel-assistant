"""Client library for AWS S3 rail datasets and archives."""

import json
from typing import Any, Dict, List, Optional, Tuple
import boto3
from botocore.config import Config
from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    ConnectTimeoutError,
    EndpointConnectionError,
)

from app.datasources.base import BaseDataSource
from app.datasources.exceptions import (
    DataSourceAuthError,
    DataSourceConfigError,
    DataSourceConnectionError,
    DataSourceError,
)
from app.db.settings import SettingsRepository

DEFAULT_S3_REGION = "eu-west-2"


class TrainS3Client(BaseDataSource):
    """Datasource client for AWS S3 rail schedule and station datasets."""

    provider_name: str = "train_s3"

    def __init__(
        self,
        bucket_name: Optional[str] = None,
        region: Optional[str] = None,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        timeout: float = 5.0,
        s3_client: Optional[Any] = None,
    ) -> None:
        self.bucket_name = (bucket_name or "").strip()
        self.region = (
            (region or DEFAULT_S3_REGION).strip() if region else DEFAULT_S3_REGION
        )
        self.access_key = (access_key or "").strip() if access_key else None
        self.secret_key = (secret_key or "").strip() if secret_key else None
        self.timeout = float(timeout)
        self._s3_client = s3_client

    @classmethod
    def from_settings(
        cls, settings_repo: Optional[SettingsRepository] = None
    ) -> "TrainS3Client":
        """Instantiate TrainS3Client with credentials loaded from SettingsRepository."""
        repo = settings_repo or SettingsRepository()
        return cls(
            bucket_name=repo.get("train_s3_bucket", ""),
            region=repo.get("train_s3_region", DEFAULT_S3_REGION),
            access_key=repo.get("train_s3_access_key", ""),
            secret_key=repo.get("train_s3_secret_key", ""),
        )

    def get_client(self) -> Any:
        """Create or return the configured boto3 S3 client."""
        if self._s3_client is not None:
            return self._s3_client

        boto_config = Config(
            region_name=self.region,
            connect_timeout=self.timeout,
            read_timeout=10,
            retries={"max_attempts": 2},
        )

        session_kwargs: Dict[str, Any] = {}
        if self.access_key and self.secret_key:
            session_kwargs["aws_access_key_id"] = self.access_key
            session_kwargs["aws_secret_access_key"] = self.secret_key
        if self.region:
            session_kwargs["region_name"] = self.region

        session = boto3.Session(**session_kwargs)
        return session.client("s3", config=boto_config)

    def validate_credentials(self) -> Dict[str, Any]:
        """Validate AWS S3 bucket access and credentials."""
        valid, message = self.validate_tuple()
        return {"valid": valid, "message": message}

    def validate_tuple(self) -> Tuple[bool, str]:
        """Validate S3 bucket returning a (valid, message) tuple."""
        if not self.bucket_name:
            return False, "Train S3 bucket name is required and cannot be empty."

        try:
            client = self.get_client()
            client.head_bucket(Bucket=self.bucket_name)
            return True, f"S3 bucket '{self.bucket_name}' is valid and accessible."
        except ClientError as e:
            error_code = str(e.response.get("Error", {}).get("Code", "Unknown"))
            if error_code in ("404", "NoSuchBucket"):
                return False, f"S3 bucket '{self.bucket_name}' does not exist (404)."
            elif error_code in ("403", "AccessDenied"):
                return (
                    False,
                    f"Access denied (403) for S3 bucket '{self.bucket_name}'. "
                    "Check your credentials and permissions.",
                )
            elif error_code in ("301", "PermanentRedirect"):
                return (
                    False,
                    f"S3 bucket '{self.bucket_name}' exists in a different region. "
                    "Please specify the correct region.",
                )
            else:
                error_msg = e.response.get("Error", {}).get("Message", str(e))
                return False, f"S3 bucket error ({error_code}): {error_msg}"
        except ConnectTimeoutError:
            return False, f"Connection timed out after {self.timeout}s."
        except EndpointConnectionError:
            return (
                False,
                f"Unable to connect to AWS S3 endpoint for region '{self.region}'.",
            )
        except BotoCoreError as e:
            return False, f"AWS S3 error: {str(e)}"
        except Exception as e:
            return False, f"S3 validation error: {str(e)}"

    def fetch_stations(self, key: str = "data/stations.json") -> List[Dict[str, Any]]:
        """Fetch rail stations dataset from S3 bucket."""
        if not self.bucket_name:
            raise DataSourceConfigError(
                "S3 bucket name is not configured.", provider=self.provider_name
            )

        try:
            client = self.get_client()
            response = client.get_object(Bucket=self.bucket_name, Key=key)
            raw_content = response["Body"].read().decode("utf-8")
            stations_data = json.loads(raw_content)

            if isinstance(stations_data, dict) and "stations" in stations_data:
                stations_list = stations_data["stations"]
            elif isinstance(stations_data, list):
                stations_list = stations_data
            else:
                stations_list = []

            stations: List[Dict[str, Any]] = []
            for item in stations_list:
                crs = str(item.get("crs_code") or item.get("crs") or "").strip().upper()
                name = str(item.get("name") or item.get("station_name") or "").strip()
                if not crs or not name:
                    continue

                stations.append(
                    {
                        "crs_code": crs,
                        "name": name,
                        "tiploc_code": item.get("tiploc_code") or item.get("tiploc"),
                        "latitude": item.get("latitude"),
                        "longitude": item.get("longitude"),
                        "operator": item.get("operator") or item.get("toc"),
                    }
                )
            return stations

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            if error_code in (
                "403",
                "AccessDenied",
                "InvalidAccessKeyId",
                "SignatureDoesNotMatch",
            ):
                raise DataSourceAuthError(
                    f"AWS S3 authentication failed ({error_code}).",
                    provider=self.provider_name,
                ) from e
            raise DataSourceError(
                f"S3 ClientError ({error_code}): {str(e)}", provider=self.provider_name
            ) from e
        except BotoCoreError as e:
            raise DataSourceConnectionError(
                f"AWS connection error: {str(e)}", provider=self.provider_name
            ) from e
        except json.JSONDecodeError as e:
            raise DataSourceError(
                f"Failed to parse stations JSON from S3: {str(e)}",
                provider=self.provider_name,
            ) from e
        except Exception as e:
            raise DataSourceError(
                f"Unexpected error fetching stations from S3: {str(e)}",
                provider=self.provider_name,
            ) from e
