"""Unit tests for configuration views and credentials management."""

import json
from unittest.mock import MagicMock
from pytest import MonkeyPatch
from flask import Flask
from flask.testing import FlaskClient

from app.models import Setting, Timetable, Walking


def test_config_index_redirect(client: FlaskClient) -> None:
    """Test that /config redirects to /config/credentials."""
    response = client.get("/config")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/config/credentials")

    response_slash = client.get("/config/")
    assert response_slash.status_code == 302
    assert response_slash.headers["Location"].endswith("/config/credentials")


def test_get_credentials_page_initial_empty(client: FlaskClient) -> None:
    """Test GET /config/credentials renders empty form fields with default model and region."""

    response = client.get("/config/credentials")
    assert response.status_code == 200
    assert b"Bus API Key" in response.data
    assert b"Train S3 Bucket Details" in response.data
    assert b"Train Live Credentials" in response.data
    assert b"OpenAI &amp; LLM Credentials" in response.data
    assert b"Google Maps API" in response.data
    assert b"1. Bus API Key" not in response.data
    assert b'name="bus_api_key"' in response.data
    assert b'name="train_s3_bucket"' in response.data
    assert b'name="train_s3_access_key"' in response.data
    assert b'name="train_s3_secret_key"' in response.data
    assert b'name="train_s3_region"' in response.data
    assert b'name="train_live_api_key"' in response.data
    assert b'name="train_live_endpoint"' in response.data
    assert b'name="open_api_key"' in response.data
    assert b'name="open_api_base_url"' in response.data
    assert b'name="open_api_model"' in response.data
    assert b'name="google_maps_api_key"' in response.data
    assert b'name="google_maps_region"' in response.data
    assert b'href="https://developers.openai.com/api/docs/pricing"' in response.data
    assert b'value="gpt-4o-mini"' in response.data
    assert b'value="uk"' in response.data


def test_post_credentials_saves_and_redirects(client: FlaskClient) -> None:
    """Test POST /config/credentials saves settings and performs PRG redirect."""
    post_data = {
        "bus_api_key": "test_bus_key_123",
        "train_s3_bucket": "my-train-bucket",
        "train_s3_access_key": "AKIA1234567890",
        "train_s3_secret_key": "supersecretkey999",
        "train_s3_region": "eu-west-2",
        "train_live_api_key": "train_live_token_abc",
        "train_live_endpoint": "https://darwin.live.trains.api",
        "open_api_key": "sk-openai-key-test",
        "open_api_base_url": "https://api.openai.com/v1",
        "open_api_model": "gpt-4o",
        "google_maps_api_key": "AIzaSyTest123",
        "google_maps_region": "gb",
    }

    response = client.post(
        "/config/credentials",
        data=post_data,
    )
    assert response.status_code == 303
    assert response.headers["Location"].endswith("/config/credentials")

    saved = Setting.get_by_category("credentials")
    assert saved["bus_api_key"] == "test_bus_key_123"
    assert saved["train_s3_bucket"] == "my-train-bucket"
    assert saved["train_s3_region"] == "eu-west-2"
    assert saved["open_api_model"] == "gpt-4o"
    assert saved["google_maps_api_key"] == "AIzaSyTest123"
    assert saved["google_maps_region"] == "gb"

    # Follow redirect
    follow = client.get("/config/credentials")
    assert follow.status_code == 200
    assert b"API credentials saved successfully." in follow.data
    assert b'value="test_bus_key_123"' in follow.data
    assert b'value="my-train-bucket"' in follow.data
    assert b'value="AIzaSyTest123"' in follow.data
    assert b'value="gb"' in follow.data


def test_credentials_ingress_header(client: FlaskClient) -> None:
    """Test that Ingress base path is prepended to form action and links."""
    response = client.get(
        "/config/credentials",
        headers={"X-Ingress-Path": "/api/hassio_ingress/xyz123"},
    )
    assert response.status_code == 200
    assert b'action="/api/hassio_ingress/xyz123/config/credentials"' in response.data
    assert b'href="/api/hassio_ingress/xyz123/config/credentials"' in response.data


def test_validate_credentials_missing_service(client: FlaskClient) -> None:
    """Test POST /config/credentials/validate without service returns 400."""
    response = client.post(
        "/config/credentials/validate",
        json={"bus_api_key": "token123"},
    )
    assert response.status_code == 400
    data = response.get_json()
    assert data["valid"] is False
    assert "Service name is required" in data["message"]


def test_validate_credentials_unknown_service(client: FlaskClient) -> None:
    """Test POST /config/credentials/validate with unknown service returns 400."""
    response = client.post(
        "/config/credentials/validate",
        json={"service": "unknown_transit_svc"},
    )
    assert response.status_code == 400
    data = response.get_json()
    assert data["valid"] is False
    assert "Unknown service" in data["message"]


def test_validate_credentials_form_post_compatibility(
    client: FlaskClient, monkeypatch: MonkeyPatch
) -> None:
    """Test POST /config/credentials/validate accepts form-encoded data."""
    from app import views

    mock_validate = MagicMock(return_value=(True, "Bus credentials valid.", {}))
    monkeypatch.setattr(
        views.config.credentials, "validate_service_credentials", mock_validate
    )

    response = client.post(
        "/config/credentials/validate",
        data={"service": "bus", "bus_api_key": "my_bus_token"},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["valid"] is True
    assert data["message"] == "Bus credentials valid."
    assert data["service"] == "bus"


def test_validate_credentials_fallback_to_repo(
    client: FlaskClient, monkeypatch: MonkeyPatch
) -> None:
    """Test POST /config/credentials/validate merges saved DB credentials."""
    from app import views

    Setting.set_val("train_s3_bucket", "saved-bucket-name", category="credentials")
    Setting.set_val("train_s3_region", "eu-west-1", category="credentials")

    mock_validate = MagicMock(return_value=(True, "S3 bucket is valid.", {}))
    monkeypatch.setattr(
        views.config.credentials, "validate_service_credentials", mock_validate
    )

    response = client.post(
        "/config/credentials/validate",
        json={"service": "train_s3"},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["valid"] is True


def test_get_timetables_page_initial_empty(client: FlaskClient) -> None:
    """Test GET /config/timetables renders empty list."""
    response = client.get("/config/timetables")
    assert response.status_code == 200
    assert b"Timetables" in response.data
    assert b"No timetables configured" in response.data
    assert b"Add Timetable" in response.data


def test_post_timetables_saves_and_redirects(client: FlaskClient) -> None:
    """Test POST /config/timetables stores valid entries with transport_type and grid content."""
    items = [
        {
            "name": "Standard Commute Schedule",
            "transport_type": "bus",
            "start_date": "2026-09-01",
            "end_date": "2026-12-31",
            "monday": True,
            "tuesday": True,
            "wednesday": True,
            "thursday": True,
            "friday": True,
            "saturday": False,
            "sunday": False,
            "bank_holiday": False,
            "content": {
                "stops": [
                    {"id": "atco:340000001", "name": "Stop 1", "type": "bus"},
                    {"id": "atco:340000002", "name": "Stop 2", "type": "bus"},
                ],
                "trips": [
                    {"id": "trip_1", "times": ["08:00", "08:20"]},
                    {"id": "trip_2", "times": ["09:00", "09:20"]},
                ],
            },
        },
        {
            "name": "Weekend Rail Service",
            "transport_type": "rail",
            "start_date": None,
            "end_date": None,
            "monday": False,
            "tuesday": False,
            "wednesday": False,
            "thursday": False,
            "friday": False,
            "saturday": True,
            "sunday": True,
            "bank_holiday": True,
            "content": json.dumps(
                {
                    "stops": [
                        {
                            "id": "naptan:PAD",
                            "name": "Paddington",
                            "type": "rail",
                        }
                    ],
                    "trips": [{"id": "trip_3", "times": ["10:00"]}],
                }
            ),
        },
    ]

    response = client.post(
        "/config/timetables",
        data={
            "timetables_json": json.dumps(
                {"added": items, "updated": [], "deleted": []}
            )
        },
    )
    assert response.status_code == 303
    assert response.headers["Location"].endswith("/config/timetables")

    # Verify model has items
    saved = [t.to_dict() for t in Timetable.select()]
    assert len(saved) == 2
    assert saved[0]["name"] == "Standard Commute Schedule"
    assert saved[0]["transport_type"] == "bus"
    assert saved[0]["start_date"] == "2026-09-01"
    assert saved[0]["end_date"] == "2026-12-31"
    assert saved[0]["monday"] is True
    assert saved[0]["saturday"] is False
    assert len(saved[0]["content"]["stops"]) == 2
    assert len(saved[0]["content"]["trips"]) == 2
    assert saved[0]["content"]["trips"][0]["times"] == ["08:00", "08:20"]

    assert saved[1]["name"] == "Weekend Rail Service"
    assert saved[1]["transport_type"] == "rail"
    assert saved[1]["start_date"] is None
    assert saved[1]["saturday"] is True
    assert len(saved[1]["content"]["stops"]) == 1

    # Follow redirect
    follow = client.get("/config/timetables")
    assert follow.status_code == 200
    assert b"Timetables saved successfully." in follow.data


def test_post_timetables_with_dual_arrival_departure_timings(
    client: FlaskClient,
) -> None:
    """Test POST /config/timetables correctly preserves dual arrival and departure entries."""
    items = [
        {
            "name": "Intercity Express Schedule",
            "transport_type": "rail",
            "start_date": "2026-09-01",
            "end_date": "2026-12-31",
            "monday": True,
            "tuesday": True,
            "wednesday": True,
            "thursday": True,
            "friday": True,
            "saturday": False,
            "sunday": False,
            "bank_holiday": False,
            "content": {
                "stops": [
                    {"id": "naptan:KGX", "name": "Kings Cross", "type": "rail"},
                    {"id": "naptan:SVG", "name": "Stevenage", "type": "rail"},
                    {"id": "naptan:PBO", "name": "Peterborough", "type": "rail"},
                ],
                "trips": [
                    {
                        "id": "trip_1",
                        "headsign": "Edinburgh",
                        "times": [
                            "08:00",
                            {"arr": "08:22", "dep": "08:25"},
                            {"arr": "08:50", "dep": "08:52"},
                        ],
                    },
                    {
                        "id": "trip_2",
                        "headsign": "Leeds",
                        "times": [
                            "09:00",
                            {"arrival": "09:20", "departure": "09:24"},
                            "",
                        ],
                    },
                ],
            },
        }
    ]

    response = client.post(
        "/config/timetables",
        data={
            "timetables_json": json.dumps(
                {"added": items, "updated": [], "deleted": []}
            )
        },
    )
    assert response.status_code == 303
    assert response.headers["Location"].endswith("/config/timetables")

    saved = [t.to_dict() for t in Timetable.select()]
    assert len(saved) == 1
    tt = saved[0]
    assert tt["name"] == "Intercity Express Schedule"
    assert tt["transport_type"] == "rail"
    assert len(tt["content"]["stops"]) == 3
    assert len(tt["content"]["trips"]) == 2

    trip1 = tt["content"]["trips"][0]
    assert trip1["times"][0] == "08:00"
    assert trip1["times"][1] == {"arr": "08:22", "dep": "08:25"}
    assert trip1["times"][2] == {"arr": "08:50", "dep": "08:52"}

    trip2 = tt["content"]["trips"][1]
    assert trip2["times"][0] == "09:00"
    assert trip2["times"][1] == {"arr": "09:20", "dep": "09:24"}
    assert trip2["times"][2] == ""


def test_clean_timetable_item_polymorphic_times() -> None:
    """Test clean_timetable_item helper directly with various timing formats."""
    from app.views.config.timetables import clean_timetable_item

    raw_item = {
        "name": "Bus Route 100",
        "transport_type": "bus",
        "content": {
            "stops": ["Stop A", {"id": "stop_b", "name": "Stop B"}],
            "trips": [
                {
                    "id": "trip_1",
                    "times": [
                        "07:30",
                        {"arr": "07:45", "dep": "07:48"},
                        {"arr": "", "dep": ""},
                        "invalid-time",
                        None,
                    ],
                }
            ],
        },
    }

    cleaned = clean_timetable_item(raw_item)
    assert cleaned is not None
    assert cleaned["name"] == "Bus Route 100"
    assert len(cleaned["content"]["stops"]) == 2
    assert cleaned["content"]["stops"][0]["name"] == "Stop A"
    assert cleaned["content"]["stops"][1]["name"] == "Stop B"

    trip = cleaned["content"]["trips"][0]
    assert trip["times"][0] == "07:30"
    assert trip["times"][1] == {"arr": "07:45", "dep": "07:48"}
    assert trip["times"][2] == ""
    assert trip["times"][3] == "invalid-time"
    assert trip["times"][4] == ""


def test_clean_timetable_item_with_toc_and_auto_added() -> None:
    """Test clean_timetable_item preserves TOC codes and auto_added attributes."""
    from app.views.config.timetables import clean_timetable_item

    raw_item = {
        "name": "London to Cambridge",
        "transport_type": "rail",
        "auto_added": True,
        "content": {
            "stops": ["London King's Cross", "Cambridge"],
            "trips": [
                {
                    "id": "trip_1",
                    "headsign": "TL 1T44",
                    "toc": "tl",
                    "operator": "Thameslink",
                    "times": ["07:00", "07:50"],
                }
            ],
        },
    }

    cleaned = clean_timetable_item(raw_item)
    assert cleaned is not None
    assert cleaned["name"] == "London to Cambridge"
    assert cleaned["auto_added"] is True
    trip = cleaned["content"]["trips"][0]
    assert trip["toc"] == "TL"
    assert trip["operator"] == "Thameslink"


def test_post_timetables_preserves_auto_added_records(client: FlaskClient) -> None:
    """Test saving timetables via POST /config/timetables preserves
    existing auto_added=True records."""
    # Pre-populate an auto_added timetable and an old custom timetable
    auto_tt = Timetable.create(
        name="Auto Darwin Timetable",
        transport_type="rail",
        auto_added=True,
    )
    auto_tt.set_content(
        {
            "stops": [{"id": "SVG", "name": "Stevenage", "type": "rail"}],
            "trips": [{"id": "trip_auto", "toc": "TL", "times": ["08:00"]}],
        }
    )
    auto_tt.save()

    old_custom_tt = Timetable.create(
        name="Old Custom Bus",
        transport_type="bus",
        auto_added=False,
    )
    old_custom_tt.set_content({"stops": [], "trips": []})
    old_custom_tt.save()

    # User submits only new custom timetables
    new_custom_items = [
        {
            "name": "New Custom Express",
            "transport_type": "bus",
            "start_date": None,
            "end_date": None,
            "monday": True,
            "tuesday": True,
            "wednesday": True,
            "thursday": True,
            "friday": True,
            "saturday": True,
            "sunday": True,
            "bank_holiday": True,
            "content": {
                "stops": [{"id": "bus1", "name": "High Street", "type": "bus"}],
                "trips": [{"id": "t1", "times": ["09:00"]}],
            },
        }
    ]

    response = client.post(
        "/config/timetables",
        data={
            "timetables_json": json.dumps(
                {
                    "added": new_custom_items,
                    "updated": [],
                    "deleted": [old_custom_tt.id, auto_tt.id],
                }
            )
        },
    )
    assert response.status_code == 303

    saved = list(Timetable.select())
    assert len(saved) == 2
    auto_recs = [t for t in saved if t.auto_added]
    custom_recs = [t for t in saved if not t.auto_added]

    assert len(auto_recs) == 1
    assert auto_recs[0].name == "Auto Darwin Timetable"
    assert auto_recs[0].get_content()["trips"][0]["toc"] == "TL"

    assert len(custom_recs) == 1
    assert custom_recs[0].name == "New Custom Express"


def test_post_timetables_invalid_date_order(client: FlaskClient) -> None:
    """Test POST /config/timetables validates end_date is after start_date."""
    items = [
        {
            "name": "Invalid Date Schedule",
            "start_date": "2026-12-31",
            "end_date": "2026-01-01",
        }
    ]
    response = client.post(
        "/config/timetables",
        data={
            "timetables_json": json.dumps(
                {"added": items, "updated": [], "deleted": []}
            )
        },
    )
    assert response.status_code == 303
    follow = client.get("/config/timetables")
    assert follow.status_code == 200
    assert b"End date" in follow.data
    assert b"cannot be before start date" in follow.data


def test_post_timetables_invalid_date_format(client: FlaskClient) -> None:
    """Test POST /config/timetables rejects malformed date format."""
    items = [
        {
            "name": "Malformed Start Date Schedule",
            "start_date": "01-09-2026",
            "end_date": "2026-12-31",
        }
    ]
    response = client.post(
        "/config/timetables",
        data={
            "timetables_json": json.dumps(
                {"added": items, "updated": [], "deleted": []}
            )
        },
    )
    assert response.status_code == 303
    follow = client.get("/config/timetables")
    assert follow.status_code == 200
    assert b"Invalid start date format" in follow.data

    items_end = [
        {
            "name": "Malformed End Date Schedule",
            "start_date": "2026-09-01",
            "end_date": "31-12-2026",
        }
    ]
    response_end = client.post(
        "/config/timetables",
        data={
            "timetables_json": json.dumps(
                {"added": items_end, "updated": [], "deleted": []}
            )
        },
    )
    assert response_end.status_code == 303
    follow_end = client.get("/config/timetables")
    assert follow_end.status_code == 200
    assert b"Invalid end date format" in follow_end.data


def test_post_timetables_malformed_json(client: FlaskClient) -> None:
    """Test POST /config/timetables handles invalid JSON gracefully."""
    response = client.post(
        "/config/timetables",
        data={"timetables_json": "invalid-json-string{"},
    )
    assert response.status_code == 303
    follow = client.get("/config/timetables")
    assert follow.status_code == 200
    assert b"Failed to save timetables" in follow.data


def test_post_timetables_non_list_json(client: FlaskClient) -> None:
    """Test POST /config/timetables handles JSON that is not a valid changeset."""
    response = client.post(
        "/config/timetables",
        data={"timetables_json": '{"key": "not-a-changeset"}'},
    )
    assert response.status_code == 303
    follow = client.get("/config/timetables")
    assert follow.status_code == 200
    assert b"Failed to save timetables" in follow.data


def test_post_timetables_sanitises_entries(client: FlaskClient) -> None:
    """Test POST /config/timetables sanitises input and skips empty names."""
    items = [
        "not-a-dict",
        {
            "name": "Valid Route Schedule",
            "monday": True,
        },
        {
            "name": "",  # Empty name should be skipped
            "start_date": "2026-01-01",
        },
    ]

    response = client.post(
        "/config/timetables",
        data={
            "timetables_json": json.dumps(
                {"added": items, "updated": [], "deleted": []}
            )
        },
    )
    assert response.status_code == 303
    saved = [t.to_dict() for t in Timetable.select()]
    assert len(saved) == 1
    assert saved[0]["name"] == "Valid Route Schedule"
    assert saved[0]["monday"] is True


def test_search_places_endpoint(client: FlaskClient) -> None:
    """Test GET /config/search/places across rail, bus, HA, and custom location datasets."""
    from app.models import Location, Stop

    # 1. Test empty response when nothing cached
    res_all = client.get("/config/search/places")
    assert res_all.status_code == 200
    data_all = res_all.get_json()
    assert data_all["total"] == 0
    assert data_all["results"] == []

    # 2. Populate stops and locations
    Stop.bulk_upsert(
        [
            {
                "atco_code": "9100OXF",
                "naptan_code": "OXF",
                "stop_type": "rail",
                "name": "Oxford",
            },
            {
                "atco_code": "9100PAD",
                "naptan_code": None,
                "stop_type": "rail",
                "name": "London Paddington",
            },
            {
                "atco_code": "340000001",
                "naptan_code": None,
                "stop_type": "bus",
                "name": "High Street Stop T1",
                "locality": "Oxford",
                "indicator": "Stop T1",
            },
            {
                "atco_code": "340000002",
                "naptan_code": "oxf002",
                "stop_type": "bus",
                "name": "Blackbird Leys Leisure Centre",
                "locality": "Oxford",
                "indicator": "opp",
            },
        ]
    )

    Location.insert_many(
        [
            {
                "id": "ha:home",
                "name": "Home",
                "latitude": 51.7520,
                "longitude": -1.2577,
                "ha": True,
            },
            {
                "id": "custom:office",
                "name": "Office HQ",
                "latitude": 51.7500,
                "longitude": -1.2600,
                "ha": False,
            },
        ]
    ).execute()

    # 3. Test rail search (with naptan prefix vs atco prefix)
    res_st = client.get("/config/search/places?type=rail&q=Oxford")
    assert res_st.status_code == 200
    data_st = res_st.get_json()
    assert len(data_st["results"]) == 1
    assert data_st["results"][0]["id"] == "naptan:OXF"
    assert data_st["results"][0]["type"] == "rail"
    assert data_st["results"][0]["icon"] == "train"

    res_pad = client.get("/config/search/places?type=rail&q=Paddington")
    assert res_pad.status_code == 200
    data_pad = res_pad.get_json()
    assert len(data_pad["results"]) == 1
    assert data_pad["results"][0]["id"] == "atco:9100PAD"

    # 4. Test bus stop search
    res_bus = client.get("/config/search/places?type=bus&q=High Street")
    assert res_bus.status_code == 200
    data_bus = res_bus.get_json()
    assert len(data_bus["results"]) == 1
    assert data_bus["results"][0]["id"] == "atco:340000001"
    assert data_bus["results"][0]["type"] == "bus"
    assert data_bus["results"][0]["icon"] == "directions_bus"

    res_bus_naptan = client.get("/config/search/places?type=bus&q=Blackbird")
    assert res_bus_naptan.status_code == 200
    data_bus_naptan = res_bus_naptan.get_json()
    assert len(data_bus_naptan["results"]) == 1
    assert data_bus_naptan["results"][0]["id"] == "naptan:oxf002"

    # 5. Test HA and custom location search
    res_ha = client.get("/config/search/places?type=ha&q=Home")
    assert res_ha.status_code == 200
    data_ha = res_ha.get_json()
    assert len(data_ha["results"]) == 1
    assert data_ha["results"][0]["id"] == "ha:home"
    assert data_ha["results"][0]["type"] == "ha"
    assert data_ha["results"][0]["icon"] == "home"

    res_custom = client.get("/config/search/places?type=custom&q=Office")
    assert res_custom.status_code == 200
    data_custom = res_custom.get_json()
    assert len(data_custom["results"]) == 1
    assert data_custom["results"][0]["id"] == "custom:office"
    assert data_custom["results"][0]["type"] == "custom"
    assert data_custom["results"][0]["icon"] == "pin_drop"

    # 6. Test tram, metro, ferry, air stops
    Stop.bulk_upsert(
        [
            {
                "atco_code": "9400ZZTRAM",
                "stop_type": "tram",
                "name": "St Peter's Square",
            },
            {
                "atco_code": "9400ZZMETRO",
                "stop_type": "metro",
                "name": "Piccadilly Circus Underground",
            },
            {
                "atco_code": "9300ZZFERRY",
                "stop_type": "ferry",
                "name": "Wightlink Ferry Port",
            },
            {
                "atco_code": "9200ZZAIR",
                "stop_type": "air",
                "name": "Heathrow Terminal 5",
            },
        ]
    )

    res_tram = client.get("/config/search/places?type=tram&q=Square")
    assert res_tram.status_code == 200
    assert len(res_tram.get_json()["results"]) == 1
    assert res_tram.get_json()["results"][0]["icon"] == "tram"

    res_metro = client.get("/config/search/places?type=metro&q=Piccadilly")
    assert res_metro.status_code == 200
    assert len(res_metro.get_json()["results"]) == 1
    assert res_metro.get_json()["results"][0]["icon"] == "subway"

    res_ferry = client.get("/config/search/places?type=ferry&q=Wightlink")
    assert res_ferry.status_code == 200
    assert len(res_ferry.get_json()["results"]) == 1
    assert res_ferry.get_json()["results"][0]["icon"] == "directions_boat"

    res_air = client.get("/config/search/places?type=air&q=Heathrow")
    assert res_air.status_code == 200
    assert len(res_air.get_json()["results"]) == 1
    assert res_air.get_json()["results"][0]["icon"] == "flight"

    # 7. Test strict transport type filtering (transit search does not return HA locations)
    res_bus_home = client.get("/config/search/places?type=bus&q=Home")
    assert res_bus_home.status_code == 200
    assert len(res_bus_home.get_json()["results"]) == 0

    res_all_home = client.get("/config/search/places?type=all&q=Home")
    assert res_all_home.status_code == 200
    assert len(res_all_home.get_json()["results"]) == 1
    assert res_all_home.get_json()["results"][0]["id"] == "ha:home"

    # 8. Test rail transport type search
    res_rail = client.get("/config/search/places?type=rail&q=Oxford")
    assert res_rail.status_code == 200
    data_rail = res_rail.get_json()
    assert len(data_rail["results"]) == 1
    assert data_rail["results"][0]["id"] == "naptan:OXF"
    assert data_rail["results"][0]["type"] == "rail"

    # 9. Test all locations search without type filter
    res_all_q = client.get("/config/search/places?limit=invalid")
    assert res_all_q.status_code == 200
    data_all_q = res_all_q.get_json()
    assert data_all_q["total"] >= 4


def test_timetables_ingress_header(client: FlaskClient) -> None:
    """Test that Ingress header is respected in timetables template."""
    response = client.get(
        "/config/timetables",
        headers={"X-Ingress-Path": "/api/hassio_ingress/token123"},
    )
    assert response.status_code == 200
    assert b'action="/api/hassio_ingress/token123/config/timetables"' in response.data
    assert b'href="/api/hassio_ingress/token123/config/credentials"' in response.data


def test_get_db_page_initial_render(client: FlaskClient) -> None:
    """Test GET /config/db renders database size card, download button, and tables grid."""
    response = client.get("/config/db")
    assert response.status_code == 200
    assert b"Database Size" in response.data
    assert b"stat-db-size" in response.data
    assert b"download-db-btn" in response.data
    assert b"Download Database" in response.data
    assert b"Database Tables" in response.data
    assert b"db-grid-wrapper" in response.data
    assert b"db-grid-wrapper" in response.data
    assert b"/static/js/db.js" in response.data
    assert b"nav-link-db" in response.data
    assert b"standard-action-bar" not in response.data
    assert b"refresh-stats-btn" not in response.data


def test_get_db_page_with_populated_tables(client: FlaskClient) -> None:
    """Test GET /config/db accurately displays database size metrics."""
    Setting.set_val("bus_key", "secret123", category="credentials")
    Setting.set_val("train_key", "secret456", category="credentials")

    Timetable.create(transport_type="bus", name="Route 1")
    Timetable.create(transport_type="rail", name="Paddington")

    response = client.get("/config/db")
    assert response.status_code == 200
    assert b"Database Size" in response.data
    assert b"stat-db-size" in response.data
    assert b"download-db-btn" in response.data
    assert b"Database Tables" in response.data
    assert b"db-grid-wrapper" in response.data


def test_db_page_ingress_header(client: FlaskClient) -> None:
    """Test that Ingress header is respected in db stats template."""
    response = client.get(
        "/config/db",
        headers={"X-Ingress-Path": "/api/hassio_ingress/test_token"},
    )
    assert response.status_code == 200
    assert b'href="/api/hassio_ingress/test_token/config/db"' in response.data
    assert b'href="/api/hassio_ingress/test_token/config/db/download"' in response.data
    assert b'href="/api/hassio_ingress/test_token/config/credentials"' in response.data
    assert b'href="/api/hassio_ingress/test_token/config/timetables"' in response.data
    assert b'href="/api/hassio_ingress/test_token/config/sync"' in response.data


def test_download_db_endpoint(client: FlaskClient) -> None:
    """Test GET /config/db/download returns a valid SQLite database attachment."""
    import sqlite3
    import tempfile

    # Seed data
    Setting.set_val("test_api_key", "secret_download_123", category="credentials")
    Timetable.create(
        transport_type="bus",
        name="Download Route Test",
        monday=True,
    )

    response = client.get("/config/db/download")
    assert response.status_code == 200
    assert "application/vnd.sqlite3" in response.headers.get("Content-Type", "")
    assert 'attachment; filename="travel_assistant.db"' in response.headers.get(
        "Content-Disposition", ""
    ) or "attachment; filename=travel_assistant.db" in response.headers.get(
        "Content-Disposition", ""
    )
    assert response.data.startswith(b"SQLite format 3\x00")

    # Validate that downloaded file contains the seeded data
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        tmp.write(response.data)
        tmp.flush()

        conn = sqlite3.connect(tmp.name)
        cursor = conn.cursor()

        cursor.execute(
            "SELECT value FROM settings WHERE category='credentials' AND key='test_api_key'"
        )
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "secret_download_123"

        cursor.execute("SELECT name FROM timetables WHERE transport_type='bus'")
        tt_row = cursor.fetchone()
        assert tt_row is not None
        assert tt_row[0] == "Download Route Test"

        conn.close()


def test_download_db_in_memory_or_uri(
    client: FlaskClient, monkeypatch: MonkeyPatch
) -> None:
    """Test GET /config/db/download fallback for in-memory or URI SQLite instances."""
    from app.views.config import sync

    Setting.set_val("mem_key", "mem_val", category="credentials")

    # Simulate get_db_path returning an in-memory URI
    monkeypatch.setattr(sync, "get_db_path", lambda _app: ":memory:")

    response = client.get("/config/db/download")
    assert response.status_code == 200
    assert response.data.startswith(b"SQLite format 3\x00")


def test_download_db_missing_file(
    client: FlaskClient, monkeypatch: MonkeyPatch
) -> None:
    """Test GET /config/db/download returns 404 when database cannot be found."""
    from app.views.config import sync
    from app.db import db

    monkeypatch.setattr(
        sync, "get_db_path", lambda _app: "/nonexistent/path/travel_assistant.db"
    )
    monkeypatch.setattr(db, "obj", None)

    response = client.get("/config/db/download")
    assert response.status_code == 404


def test_get_sync_page_initial_render(client: FlaskClient) -> None:
    """Test GET /config/sync renders transit datasets sync page with Grid.js."""
    response = client.get("/config/sync")
    assert response.status_code == 200
    assert b"Background Sync" in response.data
    assert b"Transit Datasets" in response.data
    assert b"sync-all-btn" not in response.data
    assert b"sync-grid-wrapper" in response.data
    assert b"sync-grid-wrapper" in response.data
    assert b"/static/js/sync.js" in response.data
    assert b"standard-action-bar" not in response.data

    # Verify locations table is marked as syncable via the data endpoint
    data_resp = client.get("/config/sync/data")
    assert data_resp.status_code == 200
    payload = data_resp.get_json()
    tables = payload.get("data", [])
    loc_entry = next((t for t in tables if t["name"] == "locations"), None)
    assert loc_entry is not None
    assert loc_entry["syncable"] is True


def test_sync_db_table_endpoint_all_rejected(client: FlaskClient) -> None:
    """Test POST /config/db/sync/all returns 400 as bulk synchronisation is removed."""
    response = client.post("/config/db/sync/all")
    assert response.status_code == 400
    data = response.get_json()
    assert data["success"] is False
    assert data["status"] == "error"
    assert "Bulk dataset synchronisation is not supported" in data["message"]


def test_sync_db_table_endpoint_specific_success(
    client: FlaskClient, monkeypatch: MonkeyPatch
) -> None:
    """Test POST /config/db/sync/<table_name> triggers specific table sync."""
    from app.views import config

    mock_sync_table = MagicMock(
        return_value={
            "status": "success",
            "records": 25,
            "message": "Sync successful",
            "duration_seconds": 1.5,
        }
    )
    monkeypatch.setattr(config.sync, "sync_table", mock_sync_table)

    response = client.post("/config/db/sync/bus_routes")
    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is True
    assert data["records"] == 25
    assert data["table"] == "bus_routes"
    mock_sync_table.assert_called_once_with("bus_routes", force=True)


def test_sync_db_table_endpoint_specific_error(
    client: FlaskClient, monkeypatch: MonkeyPatch
) -> None:
    """Test POST /config/db/sync/<table_name> with failed sync returns 400."""
    from app.views import config

    mock_sync_table = MagicMock(
        return_value={
            "status": "error",
            "records": 0,
            "message": "Invalid API key",
            "duration_seconds": 0.5,
        }
    )
    monkeypatch.setattr(config.sync, "sync_table", mock_sync_table)

    response = client.post("/config/db/sync/stops")
    assert response.status_code == 400
    data = response.get_json()
    assert data["success"] is False
    assert data["status"] == "error"


def test_config_routes_disable_browser_caching(client: FlaskClient) -> None:
    """Test that all configuration endpoints return HTTP headers disabling browser caching."""
    endpoints = [
        "/config",
        "/config/",
        "/config/credentials",
        "/config/timetables",
        "/config/transfers",
        "/config/locations",
        "/config/journeys",
        "/config/walking",
        "/config/sync",
        "/config/db",
        "/config/search/places?q=test",
    ]

    for endpoint in endpoints:
        response = client.get(endpoint)
        assert (
            response.headers.get("Cache-Control")
            == "no-cache, no-store, must-revalidate, max-age=0"
        ), f"Missing or incorrect Cache-Control header on {endpoint}"
        assert (
            response.headers.get("Pragma") == "no-cache"
        ), f"Missing Pragma header on {endpoint}"
        assert (
            response.headers.get("Expires") == "0"
        ), f"Missing Expires header on {endpoint}"


def test_config_pages_include_no_cache_meta_tags(client: FlaskClient) -> None:
    """Test that HTML configuration pages contain no-cache meta tags in head."""
    pages = [
        "/config/credentials",
        "/config/timetables",
        "/config/transfers",
        "/config/locations",
        "/config/journeys",
        "/config/walking",
        "/config/sync",
        "/config/db",
    ]

    for page in pages:
        response = client.get(page)
        assert response.status_code == 200
        html = response.data.decode("utf-8")
        assert (
            '<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">'
            in html
        ), f"Missing Cache-Control meta tag in {page}"
        assert (
            '<meta http-equiv="Pragma" content="no-cache">' in html
        ), f"Missing Pragma meta tag in {page}"
        assert (
            '<meta http-equiv="Expires" content="0">' in html
        ), f"Missing Expires meta tag in {page}"


def test_parse_json_form_changeset_invalid(app: FlaskClient) -> None:
    """Test parse_json_form_changeset error on invalid JSON and invalid changeset shapes."""
    import pytest
    from flask import Flask
    from app.views.config.common import parse_json_form_changeset

    test_app = Flask(__name__)
    with test_app.test_request_context("/", data={"test_key": "not-valid-json{"}):
        with pytest.raises(Exception):
            parse_json_form_changeset("test_key")

    with test_app.test_request_context(
        "/", data={"test_key": '{"is": "not-changeset"}'}
    ):
        with pytest.raises(
            ValueError, match="must contain 'added', 'updated', or 'deleted' lists"
        ):
            parse_json_form_changeset("test_key")


def test_timetables_save_leave_and_return_persistence(client: FlaskClient) -> None:
    """Verify creating/updating a timetable persists when leaving the page and returning."""
    payload = {
        "added": [
            {
                "name": "Night Bus Service",
                "transport_type": "bus",
                "start_date": "2026-09-01",
                "end_date": "2026-12-31",
                "monday": False,
                "tuesday": False,
                "wednesday": False,
                "thursday": False,
                "friday": True,
                "saturday": True,
                "sunday": True,
                "bank_holiday": True,
                "content": {"stops": ["490000077E"], "trips": [{"time": "23:45"}]},
            }
        ],
        "updated": [],
        "deleted": [],
    }

    post_resp = client.post(
        "/config/timetables",
        data={"timetables_json": json.dumps(payload)},
        follow_redirects=True,
    )
    assert post_resp.status_code == 200
    assert b"Timetables saved successfully." in post_resp.data

    # Leave page
    assert client.get("/").status_code == 200
    assert client.get("/config/locations").status_code == 200
    assert client.get("/config/journeys").status_code == 200

    # Return to Timetables
    return_resp = client.get("/config/timetables")
    assert return_resp.status_code == 200
    data_resp = client.get("/config/timetables/data")
    assert data_resp.status_code == 200
    persisted = data_resp.get_json()["data"]

    assert len(persisted) == 1
    tt = persisted[0]
    assert tt["name"] == "Night Bus Service"
    assert tt["transport_type"] == "bus"
    assert tt["start_date"] == "2026-09-01"
    assert tt["end_date"] == "2026-12-31"
    assert tt["friday"] is True
    assert tt["monday"] is False


def test_credentials_save_leave_and_return_persistence(client: FlaskClient) -> None:
    """Verify credentials save, leave page, and return persists securely."""
    post_data = {
        "bus_api_key": "bods_prod_key_777",
        "open_api_key": "sk-test-live-key",
        "open_api_model": "gpt-4o",
        "google_maps_region": "uk",
    }
    save_resp = client.post(
        "/config/credentials",
        data=post_data,
        follow_redirects=True,
    )
    assert save_resp.status_code == 200

    # Leave page
    assert client.get("/config/locations").status_code == 200
    assert client.get("/config/journeys").status_code == 200

    # Return to Credentials
    return_resp = client.get("/config/credentials")
    assert return_resp.status_code == 200
    html = return_resp.get_data(as_text=True)
    assert 'value="bods_prod_key_777"' in html
    assert 'value="sk-test-live-key"' in html
    assert 'value="gpt-4o"' in html
    assert 'value="uk"' in html


def test_config_db_data_endpoint(client: FlaskClient) -> None:
    """Test GET /config/db/data returns all database table statistics as JSON."""
    response = client.get("/config/db/data")
    assert response.status_code == 200
    assert response.content_type.startswith("application/json")
    payload = response.get_json()
    assert "data" in payload
    assert "total" in payload
    assert isinstance(payload["data"], list)
    assert payload["total"] == len(payload["data"])


def test_config_sync_data_endpoint(client: FlaskClient) -> None:
    """Test GET /config/sync/data returns all transit dataset statistics as JSON."""
    response = client.get("/config/sync/data")
    assert response.status_code == 200
    assert response.content_type.startswith("application/json")
    payload = response.get_json()
    assert "data" in payload
    assert "total" in payload
    assert isinstance(payload["data"], list)


def test_config_timetables_data_endpoint(app: Flask, client: FlaskClient) -> None:
    """Test GET /config/timetables/data returns all timetables as JSON."""
    with app.app_context():
        Timetable.delete().execute()
        Timetable.insert_many([
            {
                "name": "Express Morning Service",
                "transport_type": "rail",
                "start_date": None,
                "end_date": None,
                "monday": True, "tuesday": True, "wednesday": True,
                "thursday": True, "friday": True, "saturday": False, "sunday": False,
                "bank_holiday": False, "auto_added": False,
                "content": {"stops": [], "trips": []},
            }
        ]).execute()

    response = client.get("/config/timetables/data")
    assert response.status_code == 200
    assert response.content_type.startswith("application/json")
    payload = response.get_json()
    assert "data" in payload
    assert "total" in payload
    assert payload["total"] == 1
    assert payload["data"][0]["name"] == "Express Morning Service"
    assert payload["data"][0]["transport_type"] == "rail"


def test_config_walking_data_endpoint(app: Flask, client: FlaskClient) -> None:
    """Test GET /config/walking/data returns all walking routes as JSON."""
    with app.app_context():
        Walking.delete().execute()
        Walking.insert_many([
            {
                "start_type": "custom",
                "start_id": "custom:home",
                "start_name": "Home",
                "finish_type": "rail",
                "finish_id": "WAT",
                "finish_name": "London Waterloo",
                "time_needed_minutes": 12,
                "bidirectional": True,
                "auto_generated": False,
            }
        ]).execute()

    response = client.get("/config/walking/data")
    assert response.status_code == 200
    assert response.content_type.startswith("application/json")
    payload = response.get_json()
    assert "data" in payload
    assert "total" in payload
    assert payload["total"] == 1
    assert payload["data"][0]["start_name"] == "Home"
    assert payload["data"][0]["finish_name"] == "London Waterloo"
    assert payload["data"][0]["time_needed_minutes"] == 12
