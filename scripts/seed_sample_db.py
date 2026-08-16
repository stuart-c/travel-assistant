#!/usr/bin/env python3
"""Seed sample dataset for Travel Assistant exploratory and UI testing.

Generates a realistic SQLite database populated with UK rail stations, bus stops,
Home Assistant zones, custom locations, timetables, walking/platform transfers,
and configured journeys.
"""

import argparse
import datetime
import os
import sys

# Ensure travel-assistant package is on the Python path
TOP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
APP_DIR = os.path.join(TOP_DIR, "travel-assistant")
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

from app.main import create_app  # noqa: E402
from app.models import (  # noqa: E402
    BusRoute,
    Journey,
    Location,
    LocationTransfer,
    PlatformTransfer,
    Setting,
    Stop,
    Timetable,
    Walking,
)


def seed_database(db_path: str) -> None:
    """Populate the database at db_path with a comprehensive testing dataset."""
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    if os.path.exists(db_path):
        os.remove(db_path)

    print(f"=== Initialising Sample Database at: {db_path} ===")
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": db_path,
            "DISABLE_BACKGROUND_WORKER": True,
        }
    )

    with app.app_context():
        # 1. Seed API Credentials & Settings
        print("  -> Seeding API credentials & application settings...")
        settings_payload = {
            "bus_api_key": "sample-bods-api-key-demo-12345",
            "train_s3_bucket": "sample-darwin-s3-bucket",
            "train_s3_access_key": "sample-s3-access-key",
            "train_s3_secret_key": "sample-s3-secret-key",
            "train_s3_region": "eu-west-1",
            "train_live_api_key": "sample-darwin-live-token",
            "train_live_endpoint": "https://lite.realtime.nationalrail.co.uk/OpenLDBWS/ldb12.asmx",
            "open_api_key": "sk-sample-openai-mock-key",
            "open_api_model": "gpt-4o-mini",
            "open_api_base_url": "https://api.openai.com/v1",
            "google_maps_api_key": "AIzaSySampleGoogleMapsApiKeyDemo",
            "google_maps_region": "uk",
        }
        Setting.bulk_set(settings_payload, category="credentials")

        # 2. Seed Public Transit Stops & Rail Stations
        print("  -> Seeding transit stops and rail stations...")
        stops_data = [
            {
                "atco_code": "9100KNGX",
                "naptan_code": "KGX",
                "name": "London King's Cross",
                "stop_type": "rail",
                "latitude": 51.5308,
                "longitude": -0.1238,
                "locality": "Camden",
                "indicator": "Station",
            },
            {
                "atco_code": "9100STPX",
                "naptan_code": "STP",
                "name": "London St Pancras International",
                "stop_type": "rail",
                "latitude": 51.5314,
                "longitude": -0.1261,
                "locality": "Camden",
                "indicator": "Station",
            },
            {
                "atco_code": "9100EUSTON",
                "naptan_code": "EUS",
                "name": "London Euston",
                "stop_type": "rail",
                "latitude": 51.5284,
                "longitude": -0.1331,
                "locality": "Camden",
                "indicator": "Station",
            },
            {
                "atco_code": "9100MNCR",
                "naptan_code": "MAN",
                "name": "Manchester Piccadilly",
                "stop_type": "rail",
                "latitude": 53.4774,
                "longitude": -2.2309,
                "locality": "Manchester",
                "indicator": "Station",
            },
            {
                "atco_code": "9100EDINBUR",
                "naptan_code": "EDB",
                "name": "Edinburgh Waverley",
                "stop_type": "rail",
                "latitude": 55.9520,
                "longitude": -3.1890,
                "locality": "Edinburgh",
                "indicator": "Station",
            },
            {
                "atco_code": "490000077E",
                "naptan_code": "77E",
                "name": "King's Cross Station",
                "stop_type": "bus",
                "latitude": 51.5302,
                "longitude": -0.1225,
                "locality": "Islington",
                "indicator": "Stop E",
            },
            {
                "atco_code": "490000077W",
                "naptan_code": "77W",
                "name": "King's Cross Station",
                "stop_type": "bus",
                "latitude": 51.5305,
                "longitude": -0.1245,
                "locality": "Islington",
                "indicator": "Stop W",
            },
            {
                "atco_code": "490000077C",
                "naptan_code": "77C",
                "name": "Euston Station",
                "stop_type": "bus",
                "latitude": 51.5281,
                "longitude": -0.1325,
                "locality": "Camden",
                "indicator": "Stop C",
            },
            {
                "atco_code": "9400ZZLUBST",
                "naptan_code": "BST",
                "name": "Baker Street Underground Station",
                "stop_type": "metro",
                "latitude": 51.5226,
                "longitude": -0.1571,
                "locality": "Westminster",
                "indicator": "Underground",
            },
            {
                "atco_code": "9400ZZCRWST",
                "naptan_code": "WST",
                "name": "Wimbledon Tram Stop",
                "stop_type": "tram",
                "latitude": 51.4214,
                "longitude": -0.2064,
                "locality": "Merton",
                "indicator": "Tram Stop",
            },
        ]
        Stop.bulk_upsert(stops_data)

        # 3. Seed Bus Routes
        print("  -> Seeding bus routes...")
        bus_routes = [
            {
                "route_number": "73",
                "operator_name": "Arriva London",
                "operator_code": "ARV",
                "origin": "Oxford Circus",
                "destination": "Stoke Newington Common",
                "description": "via King's Cross, Angel, and Essex Road",
            },
            {
                "route_number": "30",
                "operator_name": "Metroline",
                "operator_code": "MET",
                "origin": "Portman Street / Marble Arch",
                "destination": "Hackney Wick",
                "description": "via Euston, King's Cross, and Highbury",
            },
            {
                "route_number": "205",
                "operator_name": "Stagecoach London",
                "operator_code": "STG",
                "origin": "Paddington Station",
                "destination": "Bow Bus Garage",
                "description": "via Marylebone, Euston, and Old Street",
            },
        ]
        BusRoute.bulk_upsert(bus_routes)

        # 4. Seed Home Assistant Zones & Custom Locations
        print("  -> Seeding Home Assistant zones and custom locations...")
        locations = [
            Location(
                id="zone.home",
                name="Home",
                latitude=51.5360,
                longitude=-0.1250,
                ha=True,
            ),
            Location(
                id="zone.work",
                name="Tech Campus",
                latitude=51.5200,
                longitude=-0.0800,
                ha=True,
            ),
            Location(
                id="zone.gym",
                name="City Health Club",
                latitude=51.5250,
                longitude=-0.1100,
                ha=True,
            ),
            Location(
                id="custom:central_library",
                name="Central Public Library",
                latitude=51.5180,
                longitude=-0.1310,
                ha=False,
            ),
            Location(
                id="custom:community_centre",
                name="St Pancras Community Centre",
                latitude=51.5340,
                longitude=-0.1330,
                ha=False,
            ),
            Location(
                id="custom:parents_house",
                name="Parents' Residence",
                latitude=51.5600,
                longitude=-0.1000,
                ha=False,
            ),
        ]
        for loc in locations:
            loc.save(force_insert=True)

        # 5. Seed Timetables
        print("  -> Seeding timetables and operating schedules...")
        timetable_weekday = Timetable(
            name="Weekday Morning Commute",
            transport_type="rail",
            start_date=datetime.date(2026, 9, 1),
            end_date=datetime.date(2026, 12, 31),
            monday=True,
            tuesday=True,
            wednesday=True,
            thursday=True,
            friday=True,
            saturday=False,
            sunday=False,
            bank_holiday=False,
        )
        timetable_weekday.set_content(
            {
                "stops": [
                    {
                        "id": "9100KNGX",
                        "name": "London King's Cross",
                        "type": "rail",
                        "indicator": "Station",
                        "icon": "train",
                        "latitude": 51.5308,
                        "longitude": -0.1238,
                    },
                    {
                        "id": "490000077E",
                        "name": "King's Cross Station",
                        "type": "bus",
                        "indicator": "Stop E",
                        "icon": "directions_bus",
                        "latitude": 51.5302,
                        "longitude": -0.1225,
                    },
                ],
                "trips": [
                    {"id": "trip-1", "headsign": "City Centre Express", "times": ["07:30", "07:35"]},
                    {"id": "trip-2", "headsign": "City Centre Express", "times": ["07:45", "07:50"]},
                    {"id": "trip-3", "headsign": "City Centre Express", "times": ["08:00", "08:05"]},
                    {"id": "trip-4", "headsign": "City Centre Express", "times": ["08:15", "08:20"]},
                    {"id": "trip-5", "headsign": "City Centre Express", "times": ["08:30", "08:35"]},
                ],
            }
        )
        timetable_weekday.save()

        timetable_weekend = Timetable(
            name="Weekend Leisure Schedule",
            transport_type="bus",
            start_date=datetime.date(2026, 9, 1),
            end_date=datetime.date(2026, 12, 31),
            monday=False,
            tuesday=False,
            wednesday=False,
            thursday=False,
            friday=False,
            saturday=True,
            sunday=True,
            bank_holiday=True,
        )
        timetable_weekend.set_content(
            {
                "stops": [
                    {
                        "id": "490000077E",
                        "name": "King's Cross Station",
                        "type": "bus",
                        "indicator": "Stop E",
                        "icon": "directions_bus",
                        "latitude": 51.5302,
                        "longitude": -0.1225,
                    },
                    {
                        "id": "490000077C",
                        "name": "Euston Station",
                        "type": "bus",
                        "indicator": "Stop C",
                        "icon": "directions_bus",
                        "latitude": 51.5281,
                        "longitude": -0.1325,
                    },
                ],
                "trips": [
                    {"id": "trip-1", "headsign": "Route 73 Weekend", "times": ["10:00", "10:15"]},
                    {"id": "trip-2", "headsign": "Route 73 Weekend", "times": ["10:30", "10:45"]},
                    {"id": "trip-3", "headsign": "Route 73 Weekend", "times": ["11:00", "11:15"]},
                ],
            }
        )
        timetable_weekend.save()

        # 6. Seed Location Transfers & Platform Transfers
        print("  -> Seeding walking links and station platform transfers...")
        loc_transfers = [
            LocationTransfer(
                from_type="rail",
                from_id="9100KNGX",
                from_name="London King's Cross",
                to_type="rail",
                to_id="9100STPX",
                to_name="London St Pancras International",
                transfer_time_minutes=4,
                bidirectional=True,
                step_free=True,
                notes="Pedestrian concourse connection with full ramp and lift access.",
            ),
            LocationTransfer(
                from_type="rail",
                from_id="9100KNGX",
                from_name="London King's Cross",
                to_type="bus",
                to_id="490000077E",
                to_name="King's Cross Station (Stop E)",
                transfer_time_minutes=3,
                bidirectional=True,
                step_free=True,
                notes="Exit via York Way entrance for direct stop access.",
            ),
            LocationTransfer(
                from_type="rail",
                from_id="9100EUSTON",
                from_name="London Euston",
                to_type="bus",
                to_id="490000077C",
                to_name="Euston Station (Stop C)",
                transfer_time_minutes=2,
                bidirectional=True,
                step_free=True,
                notes="Located directly on the bus forecourt.",
            ),
        ]
        for lt in loc_transfers:
            lt.save()

        platform_transfers = [
            PlatformTransfer(
                location_type="rail",
                location_id="9100KNGX",
                location_name="London King's Cross",
                from_platform="1",
                to_platform="8",
                transfer_time_minutes=4,
                bidirectional=True,
                step_free=True,
                notes="Use the central footbridge or ground concourse.",
            ),
            PlatformTransfer(
                location_type="rail",
                location_id="9100KNGX",
                location_name="London King's Cross",
                from_platform="9",
                to_platform="11",
                transfer_time_minutes=3,
                bidirectional=True,
                step_free=True,
                notes="Western concourse access.",
            ),
            PlatformTransfer(
                location_type="rail",
                location_id="9100EUSTON",
                location_name="London Euston",
                from_platform="2",
                to_platform="15",
                transfer_time_minutes=5,
                bidirectional=True,
                step_free=True,
                notes="Ramp access across main waiting area.",
            ),
        ]
        for pt in platform_transfers:
            pt.save()

        # 7. Seed Journeys
        print("  -> Seeding multi-leg travel journeys...")
        journeys = [
            Journey(
                name="Daily Office Commute",
                from_type="ha",
                from_id="zone.home",
                from_name="Home",
                to_type="ha",
                to_id="zone.work",
                to_name="Tech Campus",
            ),
            Journey(
                name="Library Study Session",
                from_type="ha",
                from_id="zone.home",
                from_name="Home",
                to_type="custom",
                to_id="custom:central_library",
                to_name="Central Public Library",
            ),
            Journey(
                name="Weekend Family Visit",
                from_type="ha",
                from_id="zone.home",
                from_name="Home",
                to_type="custom",
                to_id="custom:parents_house",
                to_name="Parents' Residence",
            ),
            Journey(
                name="Intercity Journey: London to Manchester",
                from_type="rail",
                from_id="9100EUSTON",
                from_name="London Euston",
                to_type="rail",
                to_id="9100MNCR",
                to_name="Manchester Piccadilly",
            ),
        ]
        for j in journeys:
            j.set_time_settings(
                [
                    {
                        "target_arrival": "08:45",
                        "buffer_minutes": 10,
                        "preferred_mode": "transit",
                    }
                ]
            )
            j.save()

        # 8. Seed Walking Routes
        print("  -> Seeding walking routes...")
        walking_routes = [
            Walking(
                start_type="ha",
                start_id="zone.home",
                start_name="Home",
                finish_type="bus",
                finish_id="490000077E",
                finish_name="King's Cross Station (Stop E)",
                time_needed_minutes=8,
                bidirectional=True,
            ),
            Walking(
                start_type="rail",
                start_id="9100KNGX",
                start_name="London King's Cross",
                finish_type="custom",
                finish_id="custom:central_library",
                finish_name="Central Public Library",
                time_needed_minutes=12,
                bidirectional=True,
            ),
            Walking(
                start_type="ha",
                start_id="zone.home",
                start_name="Home",
                finish_type="custom",
                finish_id="custom:parents_house",
                finish_name="Parents' Residence",
                time_needed_minutes=15,
                bidirectional=True,
            ),
        ]
        for w in walking_routes:
            w.save()

    print("=== Sample Database Seeding Completed Successfully! ===")
    print(f"File size: {os.path.getsize(db_path)} bytes")


def main() -> None:
    """Parse command line arguments and execute database seeding."""
    parser = argparse.ArgumentParser(
        description="Initialise sample database for Travel Assistant testing."
    )
    parser.add_argument(
        "--output",
        "-o",
        default=os.path.join(TOP_DIR, "instance", "sample_travel_assistant.db"),
        help="Destination path for the seeded SQLite database.",
    )
    args = parser.parse_args()
    seed_database(args.output)


if __name__ == "__main__":
    main()
