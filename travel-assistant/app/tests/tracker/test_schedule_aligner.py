"""Unit tests for active journey schedule realignment and propagation."""

import datetime
from flask import Flask

from app.models.timetable import (
    Timetable,
    TimetableContent,
    TimetableStop,
    TimetableTrip,
)
from app.services.dispatcher.tracker.models import (
    ActiveJourney,
    JourneyStepStatus,
)
from app.services.dispatcher.tracker.notification_formatter import (
    format_progress_notification,
)
from app.services.dispatcher.tracker.schedule_aligner import (
    _propagate_leg_timings,
    _realign_active_journey_timings,
)
from app.services.planner.models import (
    ItineraryEndpoint,
    ItineraryLeg,
    ScheduledItinerary,
)


def test_realign_active_journey_timings_bus_and_downstream_egress(app: Flask) -> None:
    """Test realigning past timetable bus departure to next trip and updating egress walk ETA."""
    with app.app_context():
        # Seed bus timetable with trips at 17:43 and 18:20
        Timetable.create(
            name="73",
            transport_type="bus",
            monday=True,
            tuesday=True,
            wednesday=True,
            thursday=True,
            friday=True,
            saturday=True,
            sunday=True,
            content=TimetableContent(
                stops=[
                    TimetableStop(id="490000077E", name="King's Cross (Stop E)"),
                    TimetableStop(id="490000077C", name="Euston Station (Stop C)"),
                ],
                trips=[
                    TimetableTrip(id="t1", times=["17:43", "18:03"]),
                    TimetableTrip(id="t2", times=["18:20", "18:40"]),
                ],
            ),
        )

        legs = [
            ItineraryLeg(
                leg_index=0,
                mode="bus",
                origin=ItineraryEndpoint(id="490000077E", name="King's Cross (Stop E)"),
                destination=ItineraryEndpoint(
                    id="490000077C", name="Euston Station (Stop C)"
                ),
                dep_time="17:43",
                arr_time="18:03",
                duration_minutes=20,
                line="73",
            ),
            ItineraryLeg(
                leg_index=1,
                mode="walk",
                origin=ItineraryEndpoint(
                    id="490000077C", name="Euston Station (Stop C)"
                ),
                destination=ItineraryEndpoint(id="ha:home", name="Home"),
                dep_time="18:03",
                arr_time="18:07",
                duration_minutes=4,
            ),
        ]
        itin = ScheduledItinerary(
            departure_time="17:43",
            arrival_time="18:07",
            total_duration_minutes=24,
            transfers_count=0,
            robustness_score="high",
            legs=legs,
        )
        active = ActiveJourney(
            journey_id=2,
            journey_name="Commute Home",
            from_type="bus",
            from_id="490000077E",
            from_name="King's Cross (Stop E)",
            to_type="ha",
            to_id="ha:home",
            to_name="Home",
            itinerary=itin,
            legs=legs,
            current_leg_index=0,
            current_status=JourneyStepStatus.AT_INTERCHANGE,
            expected_arrival_time="18:07",
        )

        # Commuter arrives at interchange at 18:00 (past 17:43 bus departure)
        dt_1800 = datetime.datetime(2026, 9, 14, 18, 0)
        _realign_active_journey_timings(active, dt_1800)

        assert active.legs[0].dep_time == "18:20"
        assert active.legs[0].arr_time == "18:40"
        # Downstream egress walking leg propagated
        assert active.legs[1].dep_time == "18:40"
        assert active.legs[1].arr_time == "18:44"
        assert active.expected_arrival_time == "18:44"

        # Check formatted notification
        _, msg, _ = format_progress_notification(active, current_dt=dt_1800)
        assert "departing at 18:20" in msg
        assert "Platform" not in msg


def test_propagate_leg_timings_helper() -> None:
    """Test _propagate_leg_timings updates consecutive legs accurately."""
    from app.tests.tracker.conftest import create_sample_active_journey

    active = create_sample_active_journey()
    # Advance leg 0 arrival from 08:08 to 08:12
    active.legs[0].arr_time = "08:12"
    _propagate_leg_timings(active, 0)
    assert active.legs[1].dep_time == "08:12"
    assert active.legs[1].arr_time == "08:26"
    assert active.legs[2].dep_time == "08:26"
    assert active.legs[2].arr_time == "08:32"
    assert active.expected_arrival_time == "08:32"
