"""Unit tests for Live Journey tracking screen and real-time telemetry API."""

from unittest.mock import MagicMock, patch
import pytest
from flask import Flask
from flask.testing import FlaskClient

from app.datasources.homeassistant import HomeAssistantClient
from app.datasources.train_live import TrainLiveClient
from app.models.journey import Journey
from app.models.location import Location
from app.models.transit import Stop
from app.services.dispatcher.monitor import DepartureMonitor
from app.services.dispatcher.tracker import (
    ActiveJourney,
    JourneyStepStatus,
    get_journey_live_tracking_data,
)
from app.services.planner.models import (
    ItineraryEndpoint,
    ItineraryLeg,
    ScheduledItinerary,
)


@pytest.fixture(autouse=True)
def clean_journey_tables(app: Flask):
    """Clean up journeys, locations, and stops between tests."""
    with app.app_context():
        Journey.delete().execute()
        Location.delete().execute()
        Stop.delete().execute()
        yield
        Journey.delete().execute()
        Location.delete().execute()
        Stop.delete().execute()


def _seed_sample_journey() -> Journey:
    """Create a sample journey with endpoints and coordinates for testing."""
    Location.create(
        id="ha:home",
        name="London King's Cross Residential",
        latitude=51.5300,
        longitude=-0.1240,
        is_ha_zone=True,
    )
    Location.create(
        id="ha:work",
        name="London Euston Offices",
        latitude=51.5280,
        longitude=-0.1330,
        is_ha_zone=True,
    )
    Stop.create(
        atco_code="490000001",
        naptan_code="KGX",
        name="London King's Cross Station",
        stop_type="rail",
        latitude=51.5308,
        longitude=-0.1238,
    )
    Stop.create(
        atco_code="490000002",
        naptan_code="EUS",
        name="London Euston Station",
        stop_type="rail",
        latitude=51.5284,
        longitude=-0.1332,
    )

    return Journey.create(
        name="Commute to Euston",
        from_type="ha",
        from_id="ha:home",
        from_name="London King's Cross Residential",
        to_type="ha",
        to_id="ha:work",
        to_name="London Euston Offices",
        time_settings=[
            {
                "days": ["mon", "tue", "wed", "thu", "fri"],
                "mode": "depart",
                "start_time": "08:00",
                "end_time": "09:00",
            }
        ],
    )


def _create_test_active_journey(journey: Journey) -> ActiveJourney:
    """Construct an ActiveJourney instance for live tracking tests."""
    leg1 = ItineraryLeg(
        leg_index=0,
        mode="walk",
        origin=ItineraryEndpoint(id="ha:home", name=journey.from_name),
        destination=ItineraryEndpoint(
            id="490000001", name="London King's Cross Station"
        ),
        dep_time="08:00",
        arr_time="08:06",
        duration_minutes=6,
    )
    leg2 = ItineraryLeg(
        leg_index=1,
        mode="rail",
        line="Northern Line",
        operator="London Underground",
        origin=ItineraryEndpoint(
            id="490000001", name="London King's Cross Station", platform="4"
        ),
        destination=ItineraryEndpoint(id="490000002", name="London Euston Station"),
        dep_time="08:08",
        arr_time="08:14",
        duration_minutes=6,
    )
    leg3 = ItineraryLeg(
        leg_index=2,
        mode="walk",
        origin=ItineraryEndpoint(id="490000002", name="London Euston Station"),
        destination=ItineraryEndpoint(id="ha:work", name=journey.to_name),
        dep_time="08:14",
        arr_time="08:20",
        duration_minutes=6,
    )

    itinerary = ScheduledItinerary(
        departure_time="08:00",
        arrival_time="08:20",
        total_duration_minutes=20,
        transfers_count=0,
        robustness_score="high",
        legs=[leg1, leg2, leg3],
    )

    return ActiveJourney(
        journey_id=journey.id,
        journey_name=journey.name,
        from_type=journey.from_type,
        from_id=journey.from_id,
        from_name=journey.from_name,
        to_type=journey.to_type,
        to_id=journey.to_id,
        to_name=journey.to_name,
        itinerary=itinerary,
        legs=[leg1, leg2, leg3],
        current_leg_index=1,
        current_status=JourneyStepStatus.ON_TRANSIT,
        platform="4",
        live_status="On time",
        expected_arrival_time="08:20",
    )


def test_journey_page_empty(client: FlaskClient) -> None:
    """Test /journey screen when no journeys are configured."""
    res = client.get("/journey")
    assert res.status_code == 200
    assert b"No Journeys Configured" in res.data
    assert b"Configure Journeys" in res.data
    assert b"/config/journeys" in res.data


def test_journey_api_live_empty(client: FlaskClient) -> None:
    """Test /api/journey/live endpoint when no journeys are configured."""
    res = client.get("/api/journey/live")
    assert res.status_code == 200
    data = res.get_json()
    assert data["journeys"] == []
    assert data["selected_journey"] is None
    assert data["active"] is False


def test_journey_page_with_configured_journey(client: FlaskClient, app: Flask) -> None:
    """Test /journey screen when journeys are configured in SQLite."""
    with app.app_context():
        j = _seed_sample_journey()

    res = client.get("/journey")
    assert res.status_code == 200
    assert b"Commute to Euston" in res.data
    assert (
        b"London King&#039;s Cross Residential" in res.data
        or b"London King's Cross Residential" in res.data
    )
    assert b"London Euston Offices" in res.data
    assert b"journey-map" in res.data
    assert b"journey-select" in res.data

    # Query with explicit journey_id
    res_id = client.get(f"/journey?journey_id={j.id}")
    assert res_id.status_code == 200
    assert b"Commute to Euston" in res_id.data


def test_journey_api_live_with_configured_journey(
    client: FlaskClient, app: Flask
) -> None:
    """Test /api/journey/live returns telemetry and route coordinates."""
    with app.app_context():
        j = _seed_sample_journey()

    mock_ha = MagicMock(spec=HomeAssistantClient)
    mock_ha.token = "fake_token"
    mock_ha.get_entity_state.return_value = {
        "entity_id": "person.stuart",
        "state": "home",
        "attributes": {"latitude": 51.5300, "longitude": -0.1240},
    }

    with patch(
        "app.views.journey.HomeAssistantClient.from_settings", return_value=mock_ha
    ):
        res = client.get(f"/api/journey/live?journey_id={j.id}")

    assert res.status_code == 200
    data = res.get_json()
    assert len(data["journeys"]) == 1
    assert data["journeys"][0]["name"] == "Commute to Euston"
    assert data["selected_journey"]["name"] == "Commute to Euston"
    assert data["selected_journey"]["from_coords"]["lat"] == 51.5300
    assert data["selected_journey"]["to_coords"]["lat"] == 51.5280
    assert data["person"]["name"] == "Stuart"
    assert data["person"]["state"] == "home"
    assert data["person"]["latitude"] == 51.5300


def test_journey_page_and_api_active_journey(client: FlaskClient, app: Flask) -> None:
    """Test /journey screen and /api/journey/live when a journey is actively tracked."""
    with app.app_context():
        j = _seed_sample_journey()
        active = _create_test_active_journey(j)

        mock_monitor = MagicMock(spec=DepartureMonitor)
        mock_monitor.active_journeys = {j.id: active}

        mock_ha = MagicMock(spec=HomeAssistantClient)
        mock_ha.token = "fake_token"
        mock_ha.get_entity_state.return_value = {
            "entity_id": "person.stuart",
            "state": "not_home",
            "attributes": {"latitude": 51.5295, "longitude": -0.1280},
        }

        with patch(
            "app.services.dispatcher.monitor.get_departure_monitor",
            return_value=mock_monitor,
        ), patch(
            "app.views.journey.HomeAssistantClient.from_settings",
            return_value=mock_ha,
        ):
            # Page load
            res = client.get("/journey")
            assert res.status_code == 200
            assert b"Active Journey" in res.data
            assert b"Stuart is here" in res.data
            assert b"Platform 4" in res.data

            # API Live call
            res_api = client.get("/api/journey/live")
            assert res_api.status_code == 200
            api_data = res_api.get_json()
            assert api_data["active"] is True
            assert api_data["selected_journey"]["is_active"] is True
            assert api_data["selected_journey"]["status"]["code"] == "on_transit"
            assert api_data["selected_journey"]["status"]["label"] == "On board transit"
            assert api_data["selected_journey"]["platform"] == "4"
            assert api_data["person"]["distance_to_next_stop_m"] is not None
            assert api_data["person"]["distance_to_destination_m"] is not None
            assert len(api_data["selected_journey"]["legs"]) == 3
            assert api_data["selected_journey"]["legs"][1]["is_current"] is True


def test_journey_live_rail_platform_resolution(app: Flask) -> None:
    """Test live Darwin platform probing in get_journey_live_tracking_data."""
    with app.app_context():
        j = _seed_sample_journey()
        active = _create_test_active_journey(j)
        active.platform = None
        active.live_status = None

        mock_live = MagicMock(spec=TrainLiveClient)
        mock_live.get_fastest_departures.return_value = [
            {"std": "08:08", "etd": "On time", "platform": "3"}
        ]

        data = get_journey_live_tracking_data(
            journey_id=j.id,
            live_client=mock_live,
            active_journeys={j.id: active},
        )

        assert data["selected_journey"]["platform"] == "3"
        assert data["selected_journey"]["live_status"] == "On time"


def test_base_navigation_active_journey_indicator(
    client: FlaskClient, app: Flask
) -> None:
    """Test that the header navigation shows active journey beacon when a journey is active."""
    with app.app_context():
        j = _seed_sample_journey()
        active = _create_test_active_journey(j)

        mock_monitor = MagicMock(spec=DepartureMonitor)
        mock_monitor.active_journeys = {j.id: active}

        with patch(
            "app.services.dispatcher.monitor.get_departure_monitor",
            return_value=mock_monitor,
        ):
            res = client.get("/")
            assert res.status_code == 200
            assert b"nav-live-journey" in res.data
            assert b"Active journey in progress" in res.data
            assert b"animate-ping" in res.data


def test_dashboard_live_journey_hero_card(client: FlaskClient) -> None:
    """Test that the index.html overview page has a hero card linking to /journey."""
    res = client.get("/")
    assert res.status_code == 200
    assert b"Live Journey Tracking" in res.data
    assert b"btn-view-live-journey" in res.data
    assert b"/journey" in res.data


def test_get_journey_live_tracking_data_stages(app: Flask) -> None:
    """Test telemetry formatting across diverse JourneyStepStatus stages."""
    with app.app_context():
        j = _seed_sample_journey()
        active = _create_test_active_journey(j)

        # 1. PRE_DEPARTURE
        active.current_status = JourneyStepStatus.PRE_DEPARTURE
        active.current_leg_index = 0
        data = get_journey_live_tracking_data(
            journey_id=j.id, active_journeys={j.id: active}
        )
        assert data["selected_journey"]["status"]["label"] == "Preparing to leave"
        assert "Prepare to depart" in data["selected_journey"]["status"]["next_step"]

        # 2. EN_ROUTE_TO_STOP
        active.current_status = JourneyStepStatus.EN_ROUTE_TO_STOP
        data2 = get_journey_live_tracking_data(
            journey_id=j.id, active_journeys={j.id: active}
        )
        assert (
            data2["selected_journey"]["status"]["label"] == "Walking to departure stop"
        )
        assert "Walk to" in data2["selected_journey"]["status"]["next_step"]

        # 3. AT_DEPARTURE_STOP
        active.current_status = JourneyStepStatus.AT_DEPARTURE_STOP
        active.current_leg_index = 1
        active.platform = "2"
        data3 = get_journey_live_tracking_data(
            journey_id=j.id, active_journeys={j.id: active}
        )
        assert data3["selected_journey"]["status"]["label"] == "At departure stop"
        assert "Platform 2" in data3["selected_journey"]["status"]["next_step"]

        # 4. ARRIVED
        active.current_status = JourneyStepStatus.ARRIVED
        data4 = get_journey_live_tracking_data(
            journey_id=j.id, active_journeys={j.id: active}
        )
        assert data4["selected_journey"]["status"]["label"] == "Arrived at destination"
        assert (
            "reached your destination"
            in data4["selected_journey"]["status"]["next_step"]
        )


def test_get_journey_live_tracking_data_no_stuart_coords(app: Flask) -> None:
    """Test telemetry handling when Stuart's coordinates are unavailable."""
    with app.app_context():
        j = _seed_sample_journey()

        mock_ha = MagicMock(spec=HomeAssistantClient)
        mock_ha.token = "token"
        mock_ha.get_entity_state.return_value = {
            "entity_id": "person.stuart",
            "state": "unknown",
            "attributes": {},
        }

        data = get_journey_live_tracking_data(
            journey_id=j.id,
            ha_client=mock_ha,
        )

        assert data["person"]["latitude"] is None
        assert data["person"]["longitude"] is None
        assert data["person"]["distance_to_next_stop_m"] is None
        assert data["person"]["distance_to_destination_m"] is None


def test_journey_invalid_id_query_param(client: FlaskClient, app: Flask) -> None:
    """Test /journey and /api/journey/live with invalid non-numeric journey_id."""
    with app.app_context():
        _seed_sample_journey()

    res_page = client.get("/journey?journey_id=not-a-number")
    assert res_page.status_code == 200

    res_api = client.get("/api/journey/live?journey_id=invalid")
    assert res_api.status_code == 200
    data = res_api.get_json()
    assert data["selected_journey"] is not None
