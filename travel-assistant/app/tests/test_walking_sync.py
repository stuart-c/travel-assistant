"""Unit and integration tests for walking route discovery and Google Directions synchronisation."""

from unittest.mock import call, patch
from flask import Flask

from app.datasources.exceptions import DataSourceAuthError
from app.models import (
    Journey,
    Location,
    Setting,
    Stop,
    SyncMetadata,
    Timetable,
    Walking,
)
from app.sync.walking_sync import (
    calculate_haversine_distance_m,
    extract_walking_minutes,
    find_candidate_stops_for_location,
    resolve_location_coords,
    sync_walking_routes,
    walking_route_exists,
)


def test_haversine_distance_calculation() -> None:
    """Test geodesic distance calculation with known coordinates."""
    # Same point -> 0 metres
    dist_zero = calculate_haversine_distance_m(51.5308, -0.1238, 51.5308, -0.1238)
    assert round(dist_zero, 2) == 0.0

    # London King's Cross (51.5308, -0.1238) to St Pancras International (51.5314, -0.1262)
    # Actual distance is approx ~180 metres
    dist = calculate_haversine_distance_m(51.5308, -0.1238, 51.5314, -0.1262)
    assert 150.0 < dist < 220.0


def test_resolve_location_coords(app: Flask) -> None:
    """Test location coordinate resolution across direct, prefixed, and name lookups."""
    with app.app_context():
        # Non-custom / non-ha returns None
        assert resolve_location_coords("rail", "9100KNGX", "Kings Cross") is None

        # Create locations
        Location.create(
            id="ha:home_zone",
            name="Home Residence",
            latitude=51.5308,
            longitude=-0.1238,
            ha=True,
        )
        Location.create(
            id="custom:work",
            name="Work Office",
            latitude=51.5155,
            longitude=-0.0922,
            ha=False,
        )

        # 1. Direct ID match
        coords1 = resolve_location_coords("ha", "ha:home_zone", "Home Residence")
        assert coords1 == (51.5308, -0.1238)

        # 2. Stripped / raw ID match
        coords2 = resolve_location_coords("ha", "home_zone", "Home")
        assert coords2 == (51.5308, -0.1238)

        # 3. Custom ID match
        coords3 = resolve_location_coords("custom", "custom:work", "Office")
        assert coords3 == (51.5155, -0.0922)

        # 4. Fallback name match
        coords4 = resolve_location_coords("ha", "unknown_id", "Home Residence")
        assert coords4 == (51.5308, -0.1238)

        # 5. Non-existent returns None
        assert resolve_location_coords("custom", "missing", "Missing") is None


def test_find_candidate_stops_for_location(app: Flask) -> None:
    """Test discovering candidate stops from NaPTAN stops and custom timetables within 500m."""
    with app.app_context():
        loc_lat, loc_lon = 51.5308, -0.1238  # London King's Cross origin

        # Stop 1: Within 500m (~180m away)
        Stop.create(
            atco_code="490000077E",
            naptan_code="KGXE",
            stop_type="bus",
            name="King's Cross Bus Stop E",
            latitude=51.5314,
            longitude=-0.1262,
        )

        # Stop 2: Far away (~3km away)
        Stop.create(
            atco_code="490000001A",
            naptan_code="ALDA",
            stop_type="bus",
            name="Far Away Stop",
            latitude=51.5133,
            longitude=-0.0772,
        )

        # Timetable custom stop: Within 500m (~250m away)
        Location.create(
            id="custom:shuttle_stop",
            name="Shuttle Hub",
            latitude=51.5320,
            longitude=-0.1250,
            ha=False,
        )
        Timetable.create(
            name="Campus Shuttle",
            transport_type="bus",
            content={
                "stops": [
                    {
                        "id": "custom:shuttle_stop",
                        "name": "Shuttle Hub",
                        "type": "custom",
                    }
                ],
                "trips": [],
            },
        )

        candidates = find_candidate_stops_for_location(
            loc_lat, loc_lon, max_distance_m=500.0
        )
        candidate_ids = [c["id"] for c in candidates]

        # Stop 1 and Timetable custom stop should be found, Stop 2 excluded
        assert "naptan:KGXE" in candidate_ids or "atco:490000077E" in candidate_ids
        assert "custom:shuttle_stop" in candidate_ids
        assert "naptan:ALDA" not in candidate_ids


def test_walking_route_exists(app: Flask) -> None:
    """Test checking existence of walking routes in direct and reverse directions."""
    with app.app_context():
        Walking.create(
            start_type="ha",
            start_id="ha:home",
            start_name="Home",
            finish_type="bus",
            finish_id="naptan:KGXE",
            finish_name="King's Cross Stop E",
            time_needed_minutes=5,
            bidirectional=True,
        )
        Walking.create(
            start_type="custom",
            start_id="custom:work",
            start_name="Work",
            finish_type="rail",
            finish_id="9100KNGX",
            finish_name="King's Cross Rail",
            time_needed_minutes=12,
            bidirectional=False,
        )

        # Bidirectional route exists both ways
        assert walking_route_exists("ha", "ha:home", "bus", "naptan:KGXE") is True
        assert walking_route_exists("bus", "naptan:KGXE", "ha", "ha:home") is True

        # Unidirectional route exists forward and reverse connection check
        assert walking_route_exists("custom", "custom:work", "rail", "9100KNGX") is True
        assert walking_route_exists("rail", "9100KNGX", "custom", "custom:work") is True

        # Non-existent
        assert walking_route_exists("ha", "ha:home", "rail", "9100EUSTON") is False


def test_extract_walking_minutes() -> None:
    """Test extracting walking duration in minutes from Google Directions responses, rounding up."""
    # Valid 350 seconds (5.83 mins) -> 6 minutes
    valid_resp = [{"legs": [{"duration": {"value": 350, "text": "6 mins"}}]}]
    assert extract_walking_minutes(valid_resp) == 6

    # Minimum 1 minute for short durations
    short_resp = [{"legs": [{"duration": {"value": 20, "text": "1 min"}}]}]
    assert extract_walking_minutes(short_resp) == 1

    # Exact boundary 60s -> 1 minute
    assert (
        extract_walking_minutes(
            [{"legs": [{"duration": {"value": 60, "text": "1 min"}}]}]
        )
        == 1
    )

    # Rounding up: 61s (1.01 mins) -> 2 minutes
    assert (
        extract_walking_minutes(
            [{"legs": [{"duration": {"value": 61, "text": "2 mins"}}]}]
        )
        == 2
    )

    # Rounding up: 185s (3.08 mins) and 205s (3.41 mins) both round up to 4 minutes
    assert (
        extract_walking_minutes(
            [{"legs": [{"duration": {"value": 185, "text": "4 mins"}}]}]
        )
        == 4
    )
    assert (
        extract_walking_minutes(
            [{"legs": [{"duration": {"value": 205, "text": "4 mins"}}]}]
        )
        == 4
    )

    # Empty or malformed responses
    assert extract_walking_minutes([]) is None
    assert extract_walking_minutes([{}]) is None
    assert extract_walking_minutes([{"legs": []}]) is None
    assert extract_walking_minutes(None) is None  # type: ignore


def test_sync_walking_routes_skipped_without_credentials(app: Flask) -> None:
    """Test sync_walking_routes records skipped status when Google Maps API key is missing."""
    with app.app_context():
        Setting.set_val("google_maps_api_key", "")
        res = sync_walking_routes()
        assert res["status"] == "skipped_no_credentials"
        assert res["records"] == 0

        meta = SyncMetadata.get_meta("walking")
        assert meta is not None
        assert meta.status == "skipped"


def test_sync_walking_routes_no_custom_places(app: Flask) -> None:
    """Test sync_walking_routes completes when no custom or HA journey places exist."""
    with app.app_context():
        Setting.set_val("google_maps_api_key", "test-api-key")
        # Create a rail-to-rail journey (no custom/ha origin/destination)
        Journey.create(
            name="Commute",
            from_type="rail",
            from_id="9100KGX",
            from_name="London King's Cross",
            to_type="rail",
            to_id="9100CBG",
            to_name="Cambridge",
        )

        res = sync_walking_routes()
        assert res["status"] == "success"
        assert res["records"] == 0
        assert Walking.select().count() == 0


def test_sync_walking_routes_creates_bidirectional_when_durations_equal(
    app: Flask,
) -> None:
    """Test inserting 1 bidirectional record when forward and reverse walking times match."""
    with app.app_context():
        Setting.set_val("google_maps_api_key", "test-api-key")

        # Create home location
        Location.create(
            id="ha:home",
            name="Home",
            latitude=51.5308,
            longitude=-0.1238,
            ha=True,
        )

        # Create nearby bus stop (~180m away)
        Stop.create(
            atco_code="490000077E",
            naptan_code="KGXE",
            stop_type="bus",
            name="King's Cross Stop E",
            latitude=51.5314,
            longitude=-0.1262,
        )

        # Create journey starting at Home
        Journey.create(
            name="Home to Cambridge",
            from_type="ha",
            from_id="ha:home",
            from_name="Home",
            to_type="rail",
            to_id="9100CBG",
            to_name="Cambridge",
        )

        mock_directions_resp = [
            {"legs": [{"duration": {"value": 300, "text": "5 mins"}}]}
        ]

        with patch("app.sync.walking_sync.GoogleMapsClient.directions") as mock_dir:
            # Both forward and reverse return 5 minutes (300 seconds)
            mock_dir.return_value = mock_directions_resp

            res = sync_walking_routes()
            assert res["status"] == "success"
            assert res["records"] == 1

            routes = list(Walking.select())
            assert len(routes) == 1
            w = routes[0]
            assert w.start_type == "ha"
            assert w.start_id == "ha:home"
            assert w.finish_type == "bus"
            assert w.finish_id == "naptan:KGXE"
            assert w.time_needed_minutes == 5
            assert w.bidirectional is True
            assert w.auto_generated is True

            # Re-running sync should not duplicate or overwrite existing route
            res_repeat = sync_walking_routes()
            assert res_repeat["records"] == 0
            assert Walking.select().count() == 1


def test_sync_walking_routes_creates_two_records_when_durations_differ(
    app: Flask,
) -> None:
    """Test inserting 2 unidirectional records when forward and reverse walking times differ."""
    with app.app_context():
        Setting.set_val("google_maps_api_key", "test-api-key")

        # Create custom place
        Location.create(
            id="custom:office",
            name="Office",
            latitude=51.5308,
            longitude=-0.1238,
            ha=False,
        )

        # Create nearby bus stop (~180m away)
        Stop.create(
            atco_code="490000077E",
            naptan_code="KGXE",
            stop_type="bus",
            name="King's Cross Stop E",
            latitude=51.5314,
            longitude=-0.1262,
        )

        # Create journey ending at Office
        Journey.create(
            name="Morning Commute",
            from_type="rail",
            from_id="9100KGX",
            from_name="London King's Cross",
            to_type="custom",
            to_id="custom:office",
            to_name="Office",
        )

        fwd_resp = [{"legs": [{"duration": {"value": 240, "text": "4 mins"}}]}]
        rev_resp = [{"legs": [{"duration": {"value": 420, "text": "7 mins"}}]}]

        with patch("app.sync.walking_sync.GoogleMapsClient.directions") as mock_dir:
            mock_dir.side_effect = [fwd_resp, rev_resp]

            res = sync_walking_routes()
            assert res["status"] == "success"
            assert res["records"] == 2

            routes = list(Walking.select().order_by(Walking.id))
            assert len(routes) == 2

            # Route 1: Office -> Stop E (4 mins)
            assert routes[0].start_id == "custom:office"
            assert routes[0].finish_id == "naptan:KGXE"
            assert routes[0].time_needed_minutes == 4
            assert routes[0].bidirectional is False
            assert routes[0].auto_generated is True

            # Route 2: Stop E -> Office (7 mins)
            assert routes[1].start_id == "naptan:KGXE"
            assert routes[1].finish_id == "custom:office"
            assert routes[1].time_needed_minutes == 7
            assert routes[1].bidirectional is False
            assert routes[1].auto_generated is True


def test_sync_walking_routes_handles_api_errors(app: Flask) -> None:
    """Test sync_walking_routes catches Google API errors and records error diagnostics."""
    with app.app_context():
        Setting.set_val("google_maps_api_key", "invalid-key")

        Location.create(
            id="ha:home",
            name="Home",
            latitude=51.5308,
            longitude=-0.1238,
            ha=True,
        )
        Stop.create(
            atco_code="490000077E",
            naptan_code="KGXE",
            stop_type="bus",
            name="King's Cross Stop E",
            latitude=51.5314,
            longitude=-0.1262,
        )
        Journey.create(
            name="Home Journey",
            from_type="ha",
            from_id="ha:home",
            from_name="Home",
            to_type="rail",
            to_id="9100CBG",
            to_name="Cambridge",
        )

        with patch("app.sync.walking_sync.GoogleMapsClient.directions") as mock_dir:
            mock_dir.side_effect = DataSourceAuthError(
                "Invalid API Key", provider="google_maps"
            )

            res = sync_walking_routes()
            assert res["status"] == "error"
            assert "Invalid API Key" in res["message"]

            meta = SyncMetadata.get_meta("walking")
            assert meta is not None
            assert meta.status == "error"


def test_trigger_walking_sync_if_changed_calls_request_sync(app: Flask) -> None:
    """Test _trigger_syncs_if_changed queues walking sync for location changes."""
    from app.views.config.journeys import _trigger_syncs_if_changed

    with app.app_context():
        with patch("app.views.config.journeys.request_sync") as mock_request_sync:
            # No changes — should not queue anything
            _trigger_syncs_if_changed(
                {"added": 0, "updated": 0, "deleted": 0},
                {"added": [], "updated": []},
            )
            mock_request_sync.assert_not_called()

            # With location changes — should queue "walking" and "journey_routes"
            _trigger_syncs_if_changed(
                {"added": 1, "updated": 0, "deleted": 0},
                {
                    "added": [
                        {
                            "from_type": "ha",
                            "from_id": "ha:home",
                            "to_type": "rail",
                            "to_id": "9100WAT",
                        }
                    ],
                    "updated": [],
                },
            )
            mock_request_sync.assert_has_calls(
                [call("walking"), call("journey_routes")]
            )


def test_sync_walking_routes_timetable_stop_resolution(app: Flask) -> None:
    """Test candidate stop discovery from timetables using Stop table lookup."""
    with app.app_context():
        Setting.set_val("google_maps_api_key", "test-api-key")

        Location.create(
            id="ha:flat",
            name="Flat",
            latitude=51.5308,
            longitude=-0.1238,
            ha=True,
        )

        Stop.create(
            atco_code="9100KNGX",
            naptan_code="KGX",
            stop_type="rail",
            name="London King's Cross Rail Station",
            latitude=51.5310,
            longitude=-0.1240,
        )

        # Timetable references 9100KNGX without explicit coordinates
        Timetable.create(
            name="Rail Service",
            transport_type="rail",
            content={
                "stops": [{"id": "9100KNGX", "name": "London King's Cross"}],
                "trips": [],
            },
        )

        Journey.create(
            name="Commute",
            from_type="ha",
            from_id="ha:flat",
            from_name="Flat",
            to_type="rail",
            to_id="9100CBG",
            to_name="Cambridge",
        )

        fwd_resp = [{"legs": [{"duration": {"value": 180, "text": "3 mins"}}]}]
        with patch("app.sync.walking_sync.GoogleMapsClient.directions") as mock_dir:
            mock_dir.return_value = fwd_resp

            res = sync_walking_routes()
            assert res["status"] == "success"
            assert res["records"] >= 1
            assert Walking.select().count() >= 1
            assert Walking.get().time_needed_minutes == 3


def test_sync_walking_routes_connection_error(app: Flask) -> None:
    """Test sync_walking_routes handles DataSourceConnectionError."""
    from app.datasources.exceptions import DataSourceConnectionError

    with app.app_context():
        Setting.set_val("google_maps_api_key", "test-key")
        Location.create(
            id="ha:home",
            name="Home",
            latitude=51.5308,
            longitude=-0.1238,
            ha=True,
        )
        Stop.create(
            atco_code="490000077E",
            stop_type="bus",
            name="Stop E",
            latitude=51.5314,
            longitude=-0.1262,
        )
        Journey.create(
            name="Home Journey",
            from_type="ha",
            from_id="ha:home",
            from_name="Home",
            to_type="rail",
            to_id="9100CBG",
            to_name="Cambridge",
        )

        with patch("app.sync.walking_sync.GoogleMapsClient.directions") as mock_dir:
            mock_dir.side_effect = DataSourceConnectionError(
                "Network timeout", provider="google_maps"
            )
            res = sync_walking_routes()
            assert res["status"] == "error"
            assert "Google Maps API error" in res["message"]


def test_sync_walking_routes_rounds_up_producing_bidirectional(
    app: Flask,
) -> None:
    """Test when Google API returns differing raw seconds that round up to the same whole
    minutes, a single bidirectional entry is created.
    """
    with app.app_context():
        Setting.set_val("google_maps_api_key", "test-api-key")

        Location.create(
            id="ha:home",
            name="Home",
            latitude=51.5308,
            longitude=-0.1238,
            ha=True,
        )
        Stop.create(
            atco_code="490000077E",
            naptan_code="490000077E",
            stop_type="bus",
            name="King's Cross Station",
            latitude=51.5314,
            longitude=-0.1262,
        )
        Journey.create(
            name="Daily Commute",
            from_type="ha",
            from_id="ha:home",
            from_name="Home",
            to_type="rail",
            to_id="9100EUSTON",
            to_name="London Euston",
        )

        # Forward: 185s (3.08m -> rounds up to 4 mins)
        # Reverse: 205s (3.41m -> rounds up to 4 mins)
        fwd_resp = [{"legs": [{"duration": {"value": 185, "text": "4 mins"}}]}]
        rev_resp = [{"legs": [{"duration": {"value": 205, "text": "4 mins"}}]}]

        with patch("app.sync.walking_sync.GoogleMapsClient.directions") as mock_dir:
            mock_dir.side_effect = [fwd_resp, rev_resp]

            res = sync_walking_routes()
            assert res["status"] == "success"
            assert res["records"] == 1

            routes = list(Walking.select())
            assert len(routes) == 1
            r = routes[0]
            assert r.start_id == "ha:home"
            assert r.finish_id == "naptan:490000077E"
            assert r.time_needed_minutes == 4
            assert r.bidirectional is True
            assert r.auto_generated is True


def test_sync_walking_routes_concurrency_lock(app: Flask) -> None:
    """Test that concurrent sync triggers do not create duplicate walking records."""
    import concurrent.futures

    with app.app_context():
        Setting.set_val("google_maps_api_key", "test-api-key")

        Location.create(
            id="ha:home",
            name="Home",
            latitude=51.5308,
            longitude=-0.1238,
            ha=True,
        )
        Stop.create(
            atco_code="490000077E",
            naptan_code="490000077E",
            stop_type="bus",
            name="King's Cross Station",
            latitude=51.5314,
            longitude=-0.1262,
        )
        Journey.create(
            name="Commute",
            from_type="ha",
            from_id="ha:home",
            from_name="Home",
            to_type="rail",
            to_id="9100EUSTON",
            to_name="London Euston",
        )

        fwd_resp = [{"legs": [{"duration": {"value": 210, "text": "4 mins"}}]}]
        rev_resp = [{"legs": [{"duration": {"value": 210, "text": "4 mins"}}]}]

        with patch("app.sync.walking_sync.GoogleMapsClient.directions") as mock_dir:
            mock_dir.side_effect = [
                fwd_resp,
                rev_resp,
                fwd_resp,
                rev_resp,
            ]

            def _run_sync():
                with app.app_context():
                    return sync_walking_routes(app=app)

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                f1 = executor.submit(_run_sync)
                f2 = executor.submit(_run_sync)
                res1 = f1.result()
                res2 = f2.result()

            assert (res1["records"] == 1 and res2["records"] == 0) or (
                res2["records"] == 1 and res1["records"] == 0
            )
            assert Walking.select().count() == 1


def test_sync_walking_routes_bus_stops_added_triggers_bus_sync(app: Flask) -> None:
    """Test discovering bus stops reports bus_stops_added and triggers bus sync."""
    with app.app_context():
        Setting.set_val("google_maps_api_key", "test-api-key")

        Location.create(
            id="ha:home_bus_test",
            name="Home Bus Test",
            latitude=51.5308,
            longitude=-0.1238,
            ha=True,
        )

        Stop.create(
            atco_code="490000077Z",
            naptan_code="KGXZ",
            stop_type="bus",
            name="King's Cross Stop Z",
            latitude=51.5314,
            longitude=-0.1262,
        )

        Journey.create(
            name="Home to Cambridge via Bus",
            from_type="ha",
            from_id="ha:home_bus_test",
            from_name="Home Bus Test",
            to_type="rail",
            to_id="9100CBG",
            to_name="Cambridge",
        )

        mock_directions_resp = [
            {"legs": [{"duration": {"value": 180, "text": "3 mins"}}]}
        ]

        with patch("app.sync.walking_sync.GoogleMapsClient.directions") as mock_dir:
            mock_dir.return_value = mock_directions_resp
            with patch("app.sync.worker.request_sync") as mock_req:
                res = sync_walking_routes()
                assert res["status"] == "success"
                assert res["records"] == 1
                assert res["bus_stops_added"] == 1
                mock_req.assert_has_calls(
                    [call("bus_timetables"), call("journey_routes")]
                )


def test_sync_walking_routes_rail_stops_does_not_trigger_bus_sync(app: Flask) -> None:
    """Test that discovering walking routes to non-bus stops does not trigger bus timetable sync."""
    with app.app_context():
        Setting.set_val("google_maps_api_key", "test-api-key")

        Location.create(
            id="ha:home_rail_test",
            name="Home Rail Test",
            latitude=51.5308,
            longitude=-0.1238,
            ha=True,
        )

        Stop.create(
            atco_code="9100KGX",
            naptan_code="KGX",
            stop_type="rail",
            name="King's Cross Rail Station",
            latitude=51.5314,
            longitude=-0.1262,
        )

        Journey.create(
            name="Home to York",
            from_type="ha",
            from_id="ha:home_rail_test",
            from_name="Home Rail Test",
            to_type="rail",
            to_id="9100YRK",
            to_name="York",
        )

        mock_directions_resp = [
            {"legs": [{"duration": {"value": 240, "text": "4 mins"}}]}
        ]

        with patch("app.sync.walking_sync.GoogleMapsClient.directions") as mock_dir:
            mock_dir.return_value = mock_directions_resp
            with patch("app.sync.worker.request_sync") as mock_req:
                res = sync_walking_routes()
                assert res["status"] == "success"
                assert res["records"] == 1
                assert res["bus_stops_added"] == 0
                mock_req.assert_called_once_with("journey_routes")
