"""Client library for AWS S3 rail datasets and archives."""

import json
from typing import Any, Dict, List, Optional, Set, Tuple
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
    def from_settings(cls, settings: Optional[Any] = None) -> "TrainS3Client":
        """Instantiate TrainS3Client with credentials loaded from Setting model or provider."""
        getter = cls.get_setting_getter(settings)
        return cls(
            bucket_name=getter("train_s3_bucket", ""),
            region=getter("train_s3_region", DEFAULT_S3_REGION),
            access_key=getter("train_s3_access_key", ""),
            secret_key=getter("train_s3_secret_key", ""),
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

    def get_latest_timetable_key(self, prefix: str = "PPTimetable/") -> Optional[str]:
        """Find the latest Darwin XML timetable snapshot key in the S3 bucket."""
        if not self.bucket_name:
            raise DataSourceConfigError(
                "S3 bucket name is not configured.", provider=self.provider_name
            )

        try:
            client = self.get_client()
            resp = client.list_objects_v2(Bucket=self.bucket_name, Prefix=prefix)

            matching_keys: List[str] = []
            for obj in resp.get("Contents", []):
                k = obj.get("Key", "")
                if (
                    k.endswith("_v8.xml.gz")
                    or k.endswith(".xml.gz")
                    or k.endswith(".xml")
                ):
                    matching_keys.append(k)

            if not matching_keys:
                return None

            # Sort lexicographically by snapshot filename/timestamp
            matching_keys.sort()
            return matching_keys[-1]

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            if error_code in ("403", "AccessDenied", "InvalidAccessKeyId"):
                raise DataSourceAuthError(
                    f"AWS S3 authentication failed ({error_code}).",
                    provider=self.provider_name,
                ) from e
            raise DataSourceError(
                f"S3 error listing timetable snapshots: {str(e)}",
                provider=self.provider_name,
            ) from e
        except BotoCoreError as e:
            raise DataSourceConnectionError(
                f"AWS connection error: {str(e)}", provider=self.provider_name
            ) from e

    def download_timetable_snapshot(
        self, key: Optional[str] = None, prefix: str = "PPTimetable/"
    ) -> bytes:
        """Download raw Darwin XML timetable snapshot bytes from S3."""
        if not self.bucket_name:
            raise DataSourceConfigError(
                "S3 bucket name is not configured.", provider=self.provider_name
            )

        target_key = key or self.get_latest_timetable_key(prefix=prefix)
        if not target_key:
            raise DataSourceError(
                f"No Darwin XML timetable snapshots found in S3 bucket '{self.bucket_name}' "
                f"with prefix '{prefix}'.",
                provider=self.provider_name,
            )

        try:
            client = self.get_client()
            response = client.get_object(Bucket=self.bucket_name, Key=target_key)
            return response["Body"].read()
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            if error_code in ("403", "AccessDenied", "InvalidAccessKeyId"):
                raise DataSourceAuthError(
                    f"AWS S3 authentication failed ({error_code}).",
                    provider=self.provider_name,
                ) from e
            raise DataSourceError(
                f"Failed to download snapshot '{target_key}' from S3: {str(e)}",
                provider=self.provider_name,
            ) from e
        except BotoCoreError as e:
            raise DataSourceConnectionError(
                f"AWS connection error: {str(e)}", provider=self.provider_name
            ) from e

    @staticmethod
    def parse_darwin_timetables(
        xml_data: Any,
        stop_lookup: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """Parse Darwin XML timetable snapshot into structured route timetable matrices.

        Extracts passenger journeys, groups them by route corridor and day-of-week profile
        (Weekday / Saturday / Sunday), unifies calling point sequences, records TOC per trip,
        and generates structured timetable objects.
        """
        import datetime
        from collections import defaultdict
        import gzip
        import io
        import xml.etree.ElementTree as ET

        lookup = stop_lookup or {}

        # Handle gzip compressed bytes or text string
        if isinstance(xml_data, bytes):
            if xml_data[:2] == b"\x1f\x8b":
                stream: Any = io.TextIOWrapper(
                    gzip.GzipFile(fileobj=io.BytesIO(xml_data)), encoding="utf-8"
                )
            else:
                stream = io.StringIO(xml_data.decode("utf-8", errors="replace"))
        elif isinstance(xml_data, str):
            stream = io.StringIO(xml_data)
        else:
            stream = xml_data

        corridors: Dict[str, Dict[str, Any]] = {}

        def _resolve_station(tpl: str) -> Dict[str, Any]:
            norm_tpl = tpl.strip().upper()
            if norm_tpl in lookup:
                return lookup[norm_tpl]
            # Standard UK NaPTAN rail station ATCO code format: "9100" + TIPLOC
            naptan_atco = f"9100{norm_tpl}"
            if naptan_atco in lookup:
                return lookup[naptan_atco]
            # Fallback title-case formatted station name
            human_name = norm_tpl.title()
            return {
                "id": f"tiploc:{norm_tpl}",
                "name": human_name,
                "type": "rail",
                "indicator": "Station",
                "icon": "train",
            }

        try:
            context = ET.iterparse(stream, events=("end",))
            for _, elem in context:
                tag = elem.tag.split("}")[-1]
                if tag == "Journey":
                    is_pax = elem.attrib.get("isPassengerSvc", "true").lower() == "true"
                    if is_pax:
                        rid = elem.attrib.get("rid", "")
                        train_id = elem.attrib.get("trainId", "")
                        toc = elem.attrib.get("toc", "").strip().upper()
                        ssd = elem.attrib.get("ssd", "")

                        calling_points: List[Dict[str, str]] = []
                        for child in elem:
                            c_tag = child.tag.split("}")[-1]
                            if c_tag in ("OR", "IP", "DT", "OPOR", "OPIP", "OPDT"):
                                tpl = child.attrib.get("tpl", "").strip().upper()
                                pta = child.attrib.get("pta", "").strip()
                                ptd = child.attrib.get("ptd", "").strip()
                                plat = child.attrib.get("plat", "").strip()

                                # Retain passenger calling points or origin/destination
                                if tpl and (pta or ptd or c_tag in ("OR", "DT")):
                                    calling_points.append(
                                        {
                                            "tpl": tpl,
                                            "pta": pta,
                                            "ptd": ptd,
                                            "plat": plat,
                                        }
                                    )

                        if len(calling_points) >= 2 and ssd:
                            try:
                                d = datetime.date.fromisoformat(ssd)
                                weekday = d.weekday()  # 0=Mon..4=Fri, 5=Sat, 6=Sun
                                if weekday <= 4:
                                    day_profile = "weekday"
                                    day_flags = {
                                        "monday": True,
                                        "tuesday": True,
                                        "wednesday": True,
                                        "thursday": True,
                                        "friday": True,
                                        "saturday": False,
                                        "sunday": False,
                                        "bank_holiday": False,
                                    }
                                elif weekday == 5:
                                    day_profile = "saturday"
                                    day_flags = {
                                        "monday": False,
                                        "tuesday": False,
                                        "wednesday": False,
                                        "thursday": False,
                                        "friday": False,
                                        "saturday": True,
                                        "sunday": False,
                                        "bank_holiday": False,
                                    }
                                else:
                                    day_profile = "sunday"
                                    day_flags = {
                                        "monday": False,
                                        "tuesday": False,
                                        "wednesday": False,
                                        "thursday": False,
                                        "friday": False,
                                        "saturday": False,
                                        "sunday": True,
                                        "bank_holiday": True,
                                    }
                            except ValueError:
                                day_profile = "all"
                                day_flags = {
                                    "monday": True,
                                    "tuesday": True,
                                    "wednesday": True,
                                    "thursday": True,
                                    "friday": True,
                                    "saturday": True,
                                    "sunday": True,
                                    "bank_holiday": True,
                                }

                            origin_tpl = calling_points[0]["tpl"]
                            dest_tpl = calling_points[-1]["tpl"]
                            base_corridor_id = f"{origin_tpl}_{dest_tpl}"
                            corridor_key = f"{base_corridor_id}_{day_profile}"

                            if corridor_key not in corridors:
                                origin_meta = _resolve_station(origin_tpl)
                                dest_meta = _resolve_station(dest_tpl)
                                corridors[corridor_key] = {
                                    "base_id": base_corridor_id,
                                    "day_profile": day_profile,
                                    "day_flags": day_flags,
                                    "origin_tpl": origin_tpl,
                                    "dest_tpl": dest_tpl,
                                    "origin_name": origin_meta["name"],
                                    "dest_name": dest_meta["name"],
                                    "start_date": ssd,
                                    "end_date": ssd,
                                    "journeys": [],
                                    "seen_trains": set(),
                                }

                            # Deduplicate journeys by train_id or rid within the same corridor profile
                            dedup_key = train_id if train_id else rid
                            if dedup_key not in corridors[corridor_key]["seen_trains"]:
                                corridors[corridor_key]["seen_trains"].add(dedup_key)
                                corridors[corridor_key]["journeys"].append(
                                    {
                                        "rid": rid,
                                        "train_id": train_id,
                                        "toc": toc,
                                        "ssd": ssd,
                                        "calling_points": calling_points,
                                    }
                                )

                    elem.clear()

        except Exception as exc:
            raise DataSourceError(
                f"Error parsing Darwin XML timetable snapshot: {str(exc)}",
                provider="train_s3",
            ) from exc

        # Identify base corridors that have multiple day profiles
        base_counts: Dict[str, Set[str]] = defaultdict(set)
        for c_info in corridors.values():
            base_counts[c_info["base_id"]].add(c_info["day_profile"])

        timetables: List[Dict[str, Any]] = []

        for corr in corridors.values():
            journeys = corr["journeys"]
            if not journeys:
                continue

            # Merge all calling point stop sequences into a canonical ordered master list
            master_tpls: List[str] = []
            for j in journeys:
                j_tpls = [cp["tpl"] for cp in j["calling_points"]]
                if not master_tpls:
                    master_tpls = list(j_tpls)
                else:
                    curr_idx = 0
                    for s in j_tpls:
                        if s in master_tpls:
                            curr_idx = master_tpls.index(s) + 1
                        else:
                            master_tpls.insert(curr_idx, s)
                            curr_idx += 1

            # Build stops array
            stops = [_resolve_station(tpl) for tpl in master_tpls]

            # Build trips array
            trips: List[Dict[str, Any]] = []
            for idx, j in enumerate(journeys):
                points_by_tpl = {cp["tpl"]: cp for cp in j["calling_points"]}
                trip_times: List[Any] = []

                for tpl in master_tpls:
                    if tpl in points_by_tpl:
                        pt = points_by_tpl[tpl]
                        arr = pt.get("pta") or ""
                        dep = pt.get("ptd") or ""
                        if arr and dep:
                            trip_times.append({"arr": arr, "dep": dep})
                        elif dep:
                            trip_times.append({"arr": "", "dep": dep})
                        elif arr:
                            trip_times.append({"arr": arr, "dep": ""})
                        else:
                            trip_times.append("")
                    else:
                        trip_times.append("")

                # Determine first departure time for sorting
                first_dep = ""
                for tm in trip_times:
                    if isinstance(tm, dict) and tm.get("dep"):
                        first_dep = tm["dep"]
                        break
                    elif isinstance(tm, dict) and tm.get("arr"):
                        first_dep = tm["arr"]
                        break
                    elif isinstance(tm, str) and tm:
                        first_dep = tm
                        break

                trip_id = f"trip-{j['rid']}" if j.get("rid") else f"trip-{idx + 1}"
                headsign = (
                    f"{j['toc']} {j['train_id']}".strip()
                    if j.get("train_id")
                    else corr["dest_name"]
                )

                trips.append(
                    {
                        "id": trip_id,
                        "headsign": headsign,
                        "toc": j["toc"],
                        "operator": TOC_NAMES.get(j["toc"], j["toc"]),
                        "times": trip_times,
                        "_first_dep": first_dep,
                    }
                )

            # Sort trips chronologically
            trips.sort(key=lambda t: t.get("_first_dep") or "99:99")
            for t in trips:
                t.pop("_first_dep", None)

            # Format timetable name with day profile suffix where appropriate
            name = f"{corr['origin_name']} to {corr['dest_name']}"
            day_prof = corr["day_profile"]
            if day_prof == "saturday":
                name = f"{name} (Sat)"
            elif day_prof == "sunday":
                name = f"{name} (Sun)"
            elif len(base_counts[corr["base_id"]]) > 1 and day_prof == "weekday":
                name = f"{name} (Mon-Fri)"

            # Parse start/end dates from ssd if available
            start_d = None
            end_d = None
            if corr.get("start_date"):
                try:
                    start_d = datetime.date.fromisoformat(corr["start_date"])
                    end_d = start_d
                except ValueError:
                    pass

            timetables.append(
                {
                    "name": name,
                    "transport_type": "rail",
                    "start_date": start_d,
                    "end_date": end_d,
                    **corr["day_flags"],
                    "auto_added": True,
                    "content": {
                        "stops": stops,
                        "trips": trips,
                    },
                }
            )

        return timetables

    def fetch_timetables(
        self,
        key: Optional[str] = None,
        prefix: str = "PPTimetable/",
        stop_lookup: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch and parse all train timetables from the Darwin S3 bucket snapshot."""
        snapshot_bytes = self.download_timetable_snapshot(key=key, prefix=prefix)
        return self.parse_darwin_timetables(snapshot_bytes, stop_lookup=stop_lookup)


TOC_NAMES: Dict[str, str] = {
    "TL": "Thameslink",
    "GN": "Great Northern",
    "LE": "Greater Anglia",
    "GA": "Greater Anglia",
    "GR": "LNER",
    "XC": "CrossCountry",
    "GW": "Great Western Railway",
    "EM": "East Midlands Railway",
    "VT": "Avanti West Coast",
    "AW": "Transport for Wales",
    "TP": "TransPennine Express",
    "NT": "Northern",
    "SE": "Southeastern",
    "SN": "Southern",
    "SW": "South Western Railway",
    "CC": "c2c",
    "CH": "Chiltern Railways",
    "ME": "Merseyrail",
    "SR": "ScotRail",
    "XR": "Elizabeth Line",
    "LO": "London Overground",
}
