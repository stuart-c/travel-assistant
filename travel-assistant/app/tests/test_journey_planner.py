"""Unit tests for the Journey Planner library service."""

import datetime
from flask import Flask
import pytest

from app.models.location import Location
from app.models.timetable import (
    Timetable,
    TimetableContent,
    TimetableStop,
    TimetableTrip,
)
from app.models.transfer import PlatformTransfer
from app.models.transit import Stop, StopInterchange
from app.models.walking import Walking
from app.services.planner import (
    InvalidEndpointError,
    JourneyPlanningError,
    JourneyPlanningErrorCode,
    NoAccessStopsError,
    NoCorridorPathError,
    NoServicesOnDayError,
    NoTripsInWindowError,
    RouteTemplate,
    ScheduledItinerary,
    find_routes,
    format_minutes_to_time,
    parse_time_to_minutes,
    plan_journey,
    resolve_endpoint_name,
    resolve_transfer_duration,
)


@pytest.fixture
def seeded_planner(app: Flask):
    """Seed multi-modal testing data in app context."""
    with app.app_context():
        # 1. Locations
        Location.create(
            id="ha:home",
            name="Home Residence",
            latitude=51.5360,
            longitude=-0.1250,
            ha=True,
        )
        Location.create(
            id="ha:work",
            name="Tech Campus",
            latitude=52.2300,
            longitude=0.1500,
            ha=True,
        )
        Location.create(
            id="custom:parents_house",
            name="Parents' Residence",
            latitude=51.5600,
            longitude=-0.1000,
            ha=False,
        )
        Location.create(
            id="custom:isolated_spot",
            name="Isolated Island",
            latitude=50.0000,
            longitude=-5.0000,
            ha=False,
        )

        # 2. Transit Stops
        Stop.create(
            atco_code="490000077E",
            naptan_code="490000077E",
            name="King's Cross Station",
            stop_type="bus",
            indicator="Stop E",
        )
        Stop.create(
            atco_code="490000077C",
            naptan_code="490000077C",
            name="Euston Station",
            stop_type="bus",
            indicator="Stop C",
        )
        Stop.create(
            atco_code="9100KNGX",
            naptan_code="KGX",
            name="London King's Cross",
            stop_type="rail",
            indicator="Station",
        )
        Stop.create(
            atco_code="9100FPK",
            naptan_code="FPK",
            name="Finsbury Park Rail Station",
            stop_type="rail",
            indicator="Station",
        )
        Stop.create(
            atco_code="9100EUSTON",
            naptan_code="EUS",
            name="London Euston",
            stop_type="rail",
            indicator="Station",
        )
        Stop.create(
            atco_code="9100MNCR",
            naptan_code="MAN",
            name="Manchester Piccadilly",
            stop_type="rail",
            indicator="Station",
        )

        # 3. Walking Connections (Priority 1)
        Walking.create(
            start_type="ha",
            start_id="ha:home",
            start_name="Home Residence",
            finish_type="bus",
            finish_id="490000077E",
            finish_name="King's Cross Station",
            time_needed_minutes=4,
            bidirectional=True,
        )
        Walking.create(
            start_type="ha",
            start_id="ha:home",
            start_name="Home Residence",
            finish_type="custom",
            finish_id="custom:parents_house",
            finish_name="Parents' Residence",
            time_needed_minutes=12,
            bidirectional=True,
        )
        Walking.create(
            start_type="rail",
            start_id="9100FPK",
            start_name="Finsbury Park Rail Station",
            finish_type="ha",
            finish_id="ha:work",
            finish_name="Tech Campus",
            time_needed_minutes=6,
            bidirectional=True,
        )

        # 4. Nearby Stop Interchanges (Priority 2)
        StopInterchange.create(
            from_stop_atco="490000077C",
            from_stop_name="Euston Station",
            from_stop_type="bus",
            to_stop_atco="9100EUSTON",
            to_stop_name="London Euston",
            to_stop_type="rail",
            distance_metres=120,
            estimated_walk_minutes=2,
        )

        # 5. Station Platform Transfers (Priority 1 & Fallback)
        PlatformTransfer.create(
            location_type="rail",
            location_id="9100EUSTON",
            location_name="London Euston",
            from_platform="1",
            to_platform="4",
            transfer_time_minutes=3,
            bidirectional=True,
            step_free=True,
        )

        # 6. Timetables
        # Bus 73: King's Cross Station -> Euston Station
        tt_bus = Timetable.create(
            name="Bus 73",
            transport_type="bus",
            monday=True,
            tuesday=True,
            wednesday=True,
            thursday=True,
            friday=True,
            saturday=False,
            sunday=False,
            bank_holiday=False,
            start_date=datetime.date(2026, 1, 1),
            end_date=datetime.date(2026, 12, 31),
        )
        tt_bus.set_content(
            TimetableContent(
                stops=[
                    TimetableStop(
                        id="490000077E", name="King's Cross Station", type="bus"
                    ),
                    TimetableStop(id="490000077C", name="Euston Station", type="bus"),
                ],
                trips=[
                    TimetableTrip(
                        id="bus73_01",
                        headsign="Euston Station",
                        operator="Arriva London",
                        times=[{"dep": "07:30"}, {"arr": "07:42"}],
                    ),
                    TimetableTrip(
                        id="bus73_02",
                        headsign="Euston Station",
                        operator="Arriva London",
                        times=[{"dep": "08:00"}, {"arr": "08:12"}],
                    ),
                ],
            )
        )
        tt_bus.save()

        # Train Thameslink: London Euston -> Finsbury Park
        tt_train = Timetable.create(
            name="Thameslink",
            transport_type="rail",
            monday=True,
            tuesday=True,
            wednesday=True,
            thursday=True,
            friday=True,
            saturday=True,
            sunday=True,
            bank_holiday=True,
            start_date=datetime.date(2026, 1, 1),
            end_date=datetime.date(2026, 12, 31),
        )
        tt_train.set_content(
            TimetableContent(
                stops=[
                    TimetableStop(id="9100EUSTON", name="London Euston", type="rail"),
                    TimetableStop(
                        id="9100FPK",
                        name="Finsbury Park Rail Station",
                        type="rail",
                    ),
                ],
                trips=[
                    TimetableTrip(
                        id="tl_01",
                        headsign="Finsbury Park",
                        operator="Thameslink",
                        times=[
                            {"dep": "07:50"},
                            {"arr": "08:35"},
                        ],
                    ),
                    TimetableTrip(
                        id="tl_02",
                        headsign="Finsbury Park",
                        operator="Thameslink",
                        times=[
                            {"dep": "08:20"},
                            {"arr": "09:05"},
                        ],
                    ),
                ],
            )
        )
        tt_train.save()

        # Intercity Train: London Euston -> Manchester Piccadilly
        tt_intercity = Timetable.create(
            name="Avanti West Coast",
            transport_type="rail",
            monday=True,
            tuesday=True,
            wednesday=True,
            thursday=True,
            friday=True,
            saturday=True,
            sunday=True,
            bank_holiday=True,
        )
        tt_intercity.set_content(
            TimetableContent(
                stops=[
                    TimetableStop(id="9100EUSTON", name="London Euston", type="rail"),
                    TimetableStop(
                        id="9100MNCR", name="Manchester Piccadilly", type="rail"
                    ),
                ],
                trips=[
                    TimetableTrip(
                        id="av_01",
                        headsign="Manchester",
                        operator="Avanti",
                        times=[{"dep": "09:00"}, {"arr": "11:06"}],
                    )
                ],
            )
        )
        tt_intercity.save()

        yield app


def test_time_parsing_helpers():
    """Verify time parsing and formatting utility functions."""
    assert parse_time_to_minutes("08:30") == 510
    assert parse_time_to_minutes("00:00") == 0
    assert parse_time_to_minutes("23:59") == 1439
    assert parse_time_to_minutes("invalid") is None
    assert parse_time_to_minutes("") is None

    assert format_minutes_to_time(510) == "08:30"
    assert format_minutes_to_time(0) == "00:00"
    assert format_minutes_to_time(1439) == "23:59"


def test_resolve_endpoint_name(seeded_planner: Flask):
    """Verify human-readable name resolution for locations and transit stops."""
    with seeded_planner.app_context():
        assert resolve_endpoint_name("ha", "ha:home") == "Home Residence"
        assert (
            resolve_endpoint_name("custom", "custom:parents_house")
            == "Parents' Residence"
        )
        assert (
            resolve_endpoint_name("bus", "490000077E")
            == "King's Cross Station (Stop E)"
        )
        assert (
            resolve_endpoint_name("rail", "9100KNGX") == "London King's Cross (Station)"
        )
        assert resolve_endpoint_name("custom", "nonexistent") == "nonexistent"


def test_transfer_resolution_hierarchy(seeded_planner: Flask):
    """Verify 3-tier transfer hierarchy: walking/platform_transfers -> stop_interchanges -> default 5 min."""
    with seeded_planner.app_context():
        # Priority 1: Exact match in walking table
        walk_res = resolve_transfer_duration("ha", "ha:home", "bus", "490000077E")
        assert walk_res is not None
        assert walk_res[0] == 4
        assert walk_res[1] == "walk"

        # Priority 1: Exact match in platform_transfers table
        plat_res = resolve_transfer_duration(
            "rail",
            "9100EUSTON",
            "rail",
            "9100EUSTON",
            from_platform="1",
            to_platform="4",
        )
        assert plat_res is not None
        assert plat_res[0] == 3
        assert plat_res[1] == "platform_transfer"

        # Priority 2: Nearby stop interchange in stop_interchanges table
        interchange_res = resolve_transfer_duration(
            "bus", "490000077C", "rail", "9100EUSTON"
        )
        assert interchange_res is not None
        assert interchange_res[0] == 2
        assert interchange_res[1] == "interchange"
        assert interchange_res[2] == 120

        # Priority 3 Fallback: Default 5 min for unconfigured platform interchange
        fallback_plat = resolve_transfer_duration("rail", "9100FPK", "rail", "9100FPK")
        assert fallback_plat is not None
        assert fallback_plat[0] == 5
        assert fallback_plat[1] == "platform_transfer"

        # Unconnected endpoints return None
        assert (
            resolve_transfer_duration("ha", "ha:home", "custom", "custom:isolated_spot")
            is None
        )


def test_find_routes_direct_walk(seeded_planner: Flask):
    """Verify Mode 1 topological route discovery for a pure walking route."""
    with seeded_planner.app_context():
        routes = find_routes("ha", "ha:home", "custom", "custom:parents_house")
        assert len(routes) >= 1
        r = routes[0]
        assert isinstance(r, RouteTemplate)
        assert r.primary_mode == "walk"
        assert r.total_duration_est_minutes == 12
        assert r.transfer_count == 0
        assert len(r.legs) == 1
        assert r.legs[0].leg_type == "walk"
        assert r.legs[0].duration_minutes == 12


def test_find_routes_multi_modal(seeded_planner: Flask):
    """Verify Mode 1 topological route discovery for multi-modal chained corridor."""
    with seeded_planner.app_context():
        routes = find_routes(
            from_type="ha",
            from_id="ha:home",
            to_type="ha",
            to_id="ha:work",
            days_of_week=["mon"],
        )
        assert len(routes) >= 1
        r = routes[0]
        assert r.primary_mode in ("bus", "rail")
        assert len(r.legs) >= 3

        # Check legs structure: Walk -> Bus -> Interchange -> Rail -> Walk
        leg_types = [leg.leg_type for leg in r.legs]
        assert "walk" in leg_types
        assert "transit" in leg_types
        assert r.transfer_count >= 1

        # Verify JSON serialisation schema matching docs
        dumped = r.model_dump()
        assert "corridor_id" in dumped
        assert "legs" in dumped
        assert len(dumped["legs"]) == len(r.legs)


def test_find_routes_intercity_rail(seeded_planner: Flask):
    """Verify Mode 1 topological discovery for direct single-line rail."""
    with seeded_planner.app_context():
        routes = find_routes(
            "rail", "9100EUSTON", "rail", "9100MNCR", days_of_week=["mon"]
        )
        assert len(routes) == 1
        r = routes[0]
        assert r.primary_mode == "rail"
        assert r.transfer_count == 0
        assert any(leg.line_name == "Avanti West Coast" for leg in r.legs)


def test_plan_journey_depart_mode(seeded_planner: Flask):
    """Verify Mode 2 RAPTOR planning with depart_after constraint."""
    with seeded_planner.app_context():
        itineraries = plan_journey(
            from_type="ha",
            from_id="ha:home",
            to_type="ha",
            to_id="ha:work",
            timing_mode="depart",
            time_str="07:25",
            days_of_week=["mon"],
        )
        assert len(itineraries) >= 1
        it = itineraries[0]
        assert isinstance(it, ScheduledItinerary)
        assert it.arrival_time == "08:41"
        assert it.total_duration_minutes > 0
        assert it.transfers_count == 1
        assert "slack" in it.robustness_score.lower()

        # Verify legs sequence
        assert len(it.legs) >= 3
        assert it.legs[0].mode == "walk"
        assert it.legs[0].origin.id == "ha:home"
        assert it.legs[-1].destination.id == "ha:work"


def test_plan_journey_arrive_mode(seeded_planner: Flask):
    """Verify Mode 2 RAPTOR planning with arrive_by constraint."""
    with seeded_planner.app_context():
        itineraries = plan_journey(
            from_type="ha",
            from_id="ha:home",
            to_type="ha",
            to_id="ha:work",
            timing_mode="arrive",
            time_str="09:15",
            days_of_week=["mon"],
        )
        assert len(itineraries) >= 1
        it = itineraries[0]
        assert parse_time_to_minutes(it.arrival_time) <= parse_time_to_minutes("09:15")
        # Latest valid departure
        assert parse_time_to_minutes(it.departure_time) >= parse_time_to_minutes(
            "07:00"
        )


def test_plan_journey_window_mode(seeded_planner: Flask):
    """Verify Mode 2 RAPTOR planning over a multi-hour time window."""
    with seeded_planner.app_context():
        itineraries = plan_journey(
            from_type="ha",
            from_id="ha:home",
            to_type="ha",
            to_id="ha:work",
            timing_mode="window",
            time_str="07:00",
            time_window_end="08:30",
            days_of_week=["mon"],
        )
        assert (
            len(itineraries) >= 2
        )  # Should capture both 07:30 and 08:00 bus departures
        for it in itineraries:
            dep_m = parse_time_to_minutes(it.departure_time)
            assert dep_m >= parse_time_to_minutes("07:00")
            assert dep_m <= parse_time_to_minutes("08:30")


def test_error_invalid_endpoints(seeded_planner: Flask):
    """Verify InvalidEndpointError and same origin/destination errors."""
    with seeded_planner.app_context():
        with pytest.raises(InvalidEndpointError):
            find_routes("", "", "rail", "9100EUSTON")

        with pytest.raises(JourneyPlanningError) as exc_info:
            find_routes("rail", "9100EUSTON", "rail", "9100EUSTON")
        assert exc_info.value.code == JourneyPlanningErrorCode.SAME_ORIGIN_DESTINATION


def test_error_no_access_stops(seeded_planner: Flask):
    """Verify NoAccessStopsError when endpoint has no walking connections."""
    with seeded_planner.app_context():
        with pytest.raises(NoAccessStopsError) as exc_info:
            find_routes("custom", "custom:isolated_spot", "rail", "9100EUSTON")
        assert exc_info.value.code == JourneyPlanningErrorCode.NO_ACCESS_STOPS
        assert "isolated_spot" in exc_info.value.message


def test_error_no_corridor_path(seeded_planner: Flask):
    """Verify NoCorridorPathError when no transit services connect the access stops."""
    with seeded_planner.app_context():
        with pytest.raises(NoCorridorPathError) as exc_info:
            find_routes("rail", "9100FPK", "rail", "9100MNCR", days_of_week=["mon"])
        assert exc_info.value.code == JourneyPlanningErrorCode.NO_CORRIDOR_PATH


def test_error_no_services_on_day(seeded_planner: Flask):
    """Verify NoServicesOnDayError or NoCorridorPathError on non-operating days (e.g. Sunday for Bus 73)."""
    with seeded_planner.app_context():
        # Bus 73 does not run on Sunday, Thameslink does. But King's Cross Station Stop E only has Bus 73.
        with pytest.raises((NoServicesOnDayError, NoCorridorPathError)):
            plan_journey(
                from_type="ha",
                from_id="ha:home",
                to_type="ha",
                to_id="ha:work",
                days_of_week=["sun"],
            )


def test_error_no_trips_in_window(seeded_planner: Flask):
    """Verify NoTripsInWindowError when corridor exists but window has no departures."""
    with seeded_planner.app_context():
        with pytest.raises(NoTripsInWindowError) as exc_info:
            plan_journey(
                from_type="rail",
                from_id="9100EUSTON",
                to_type="rail",
                to_id="9100MNCR",
                timing_mode="depart",
                time_str="14:00",  # Trip is at 09:00 only
                days_of_week=["mon"],
            )
        assert exc_info.value.code == JourneyPlanningErrorCode.NO_TRIPS_IN_WINDOW


def test_journey_planning_error_to_dict():
    """Verify error serialization via to_dict()."""
    err = JourneyPlanningError(
        JourneyPlanningErrorCode.NO_CORRIDOR_PATH,
        "Custom error message",
        {"detail": 123},
    )
    d = err.to_dict()
    assert d["error_code"] == "NO_CORRIDOR_PATH"
    assert d["message"] == "Custom error message"
    assert d["diagnostics"] == {"detail": 123}


def test_date_and_day_resolution_edge_cases(seeded_planner: Flask):
    """Verify target_date strings, weekday names, and date validity filtering."""
    with seeded_planner.app_context():
        # Valid date string
        routes = find_routes(
            "rail",
            "9100EUSTON",
            "rail",
            "9100MNCR",
            target_date="2026-08-24",  # A Monday
        )
        assert len(routes) == 1

        # Full day name "monday"
        routes_day = find_routes(
            "rail", "9100EUSTON", "rail", "9100MNCR", days_of_week=["monday"]
        )
        assert len(routes_day) == 1

        # Invalid date string falls back gracefully
        routes_inv = find_routes(
            "rail", "9100EUSTON", "rail", "9100MNCR", target_date="not-a-date"
        )
        assert len(routes_inv) == 1

        # Date out of validity range (start_date=2026-01-01, end_date=2026-12-31)
        with pytest.raises(NoCorridorPathError):
            find_routes(
                "bus",
                "490000077E",
                "bus",
                "490000077C",
                target_date="2025-05-01",  # Before start_date
                days_of_week=["mon"],
            )


def test_direct_walk_planning_modes(seeded_planner: Flask):
    """Verify direct walking in arrive and window timing modes."""
    with seeded_planner.app_context():
        # Arrive mode for direct walk
        it_arr = plan_journey(
            from_type="ha",
            from_id="ha:home",
            to_type="custom",
            to_id="custom:parents_house",
            timing_mode="arrive",
            time_str="10:00",
        )
        assert len(it_arr) == 1
        assert it_arr[0].arrival_time == "10:00"
        assert it_arr[0].departure_time == "09:48"

        # Window mode default end time
        it_win = plan_journey(
            from_type="ha",
            from_id="ha:home",
            to_type="custom",
            to_id="custom:parents_house",
            timing_mode="window",
            time_str="10:00",
            time_window_end=None,  # Tests default +120 min window
        )
        assert len(it_win) == 1


def test_timetable_with_string_times(seeded_planner: Flask):
    """Verify handling of timetables with plain string times and empty stop sequences."""
    with seeded_planner.app_context():
        tt_str = Timetable.create(
            name="Express Shuttle",
            transport_type="bus",
            monday=True,
            tuesday=True,
            wednesday=True,
            thursday=True,
            friday=True,
            saturday=True,
            sunday=True,
            bank_holiday=True,
        )
        tt_str.set_content(
            TimetableContent(
                stops=[
                    TimetableStop(
                        id="490000077E", name="King's Cross Station", type="bus"
                    ),
                    TimetableStop(id="490000077C", name="Euston Station", type="bus"),
                ],
                trips=[
                    TimetableTrip(
                        id="shuttle_01",
                        headsign="Express",
                        operator="ShuttleCorp",
                        times=["08:30", "08:40"],  # Plain string times
                    )
                ],
            )
        )
        tt_str.save()

        it = plan_journey(
            from_type="bus",
            from_id="490000077E",
            to_type="bus",
            to_id="490000077C",
            timing_mode="depart",
            time_str="08:25",
            days_of_week=["mon"],
        )
        assert len(it) >= 1
        assert any(leg.line == "Express Shuttle" for plan in it for leg in plan.legs)


def test_pruning_pareto_dominance(seeded_planner: Flask):
    """Verify Pareto dominance filtering eliminates strictly slower routes with equal/more transfers."""
    with seeded_planner.app_context():
        # Create a slow parallel bus line between same stops
        tt_slow = Timetable.create(
            name="Slow Bus 73X",
            transport_type="bus",
            monday=True,
            tuesday=True,
            wednesday=True,
            thursday=True,
            friday=True,
            saturday=True,
            sunday=True,
            bank_holiday=True,
        )
        tt_slow.set_content(
            TimetableContent(
                stops=[
                    TimetableStop(
                        id="490000077E", name="King's Cross Station", type="bus"
                    ),
                    TimetableStop(id="490000077C", name="Euston Station", type="bus"),
                ],
                trips=[
                    TimetableTrip(
                        id="slow_01",
                        headsign="Euston Station Slow",
                        operator="Arriva London",
                        times=[{"dep": "07:30"}, {"arr": "08:30"}],  # 60 min vs 12 min
                    )
                ],
            )
        )
        tt_slow.save()

        routes = find_routes(
            from_type="bus",
            from_id="490000077E",
            to_type="bus",
            to_id="490000077C",
            days_of_week=["mon"],
        )
        # Should only retain the fastest non-dominated Bus 73
        assert len(routes) == 1
        assert routes[0].legs[0].line_name == "Bus 73"
