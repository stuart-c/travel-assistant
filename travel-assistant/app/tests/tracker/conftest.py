"""Common fixtures and helpers for journey tracker tests."""

from app.services.dispatcher.tracker.models import ActiveJourney
from app.services.planner.models import (
    ItineraryEndpoint,
    ItineraryLeg,
    ScheduledItinerary,
)


def create_sample_active_journey(
    journey_id: int = 1,
    with_rail: bool = False,
) -> ActiveJourney:
    """Create a sample ActiveJourney fixture with walk -> transit -> walk legs."""
    legs = [
        ItineraryLeg(
            leg_index=1,
            mode="walk",
            origin=ItineraryEndpoint(id="ha:home", name="Home"),
            destination=ItineraryEndpoint(
                id="naptan:KGX" if with_rail else "atco:490000077E",
                name="London King's Cross" if with_rail else "King's Cross (Stop E)",
            ),
            dep_time="08:00",
            arr_time="08:08",
            duration_minutes=8,
        ),
        ItineraryLeg(
            leg_index=2,
            mode="rail" if with_rail else "bus",
            line="Thameslink" if with_rail else "73",
            operator="Govia" if with_rail else "Arriva",
            origin=ItineraryEndpoint(
                id="naptan:KGX" if with_rail else "atco:490000077E",
                name="London King's Cross" if with_rail else "King's Cross (Stop E)",
            ),
            destination=ItineraryEndpoint(
                id="naptan:CBG" if with_rail else "atco:490000077C",
                name="Cambridge" if with_rail else "Euston Station (Stop C)",
            ),
            dep_time="08:08",
            arr_time="08:22",
            duration_minutes=14,
        ),
        ItineraryLeg(
            leg_index=3,
            mode="walk",
            origin=ItineraryEndpoint(
                id="naptan:CBG" if with_rail else "atco:490000077C",
                name="Cambridge" if with_rail else "Euston Station (Stop C)",
            ),
            destination=ItineraryEndpoint(id="ha:office", name="Tech Campus"),
            dep_time="08:22",
            arr_time="08:28",
            duration_minutes=6,
        ),
    ]

    itin = ScheduledItinerary(
        departure_time="08:00",
        arrival_time="08:28",
        total_duration_minutes=28,
        transfers_count=0,
        robustness_score="High",
        legs=legs,
    )

    return ActiveJourney(
        journey_id=journey_id,
        journey_name="Daily Office Commute",
        from_type="ha",
        from_id="ha:home",
        from_name="Home",
        to_type="ha",
        to_id="ha:office",
        to_name="Tech Campus",
        itinerary=itin,
        legs=legs,
        expected_arrival_time="08:28",
        last_notification_message=None,
    )
