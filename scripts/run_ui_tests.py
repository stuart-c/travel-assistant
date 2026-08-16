#!/usr/bin/env python3
"""Automated UI, DOM structure, and Ingress validation script for Travel Assistant."""

import argparse
import json
import os
import re
import sys
from typing import Dict, List, Tuple
from bs4 import BeautifulSoup

TOP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
APP_DIR = os.path.join(TOP_DIR, "travel-assistant")
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)
if TOP_DIR not in sys.path:
    sys.path.insert(0, TOP_DIR)

from app.main import create_app  # noqa: E402


class UITester:
    """In-memory or HTTP test executor for Travel Assistant UI views."""

    def __init__(self, sample_db_path: str = None) -> None:
        if sample_db_path is None:
            sample_db_path = os.path.join(
                TOP_DIR, "instance", "sample_travel_assistant.db"
            )

        # If sample DB doesn't exist, generate it
        if not os.path.exists(sample_db_path):
            from scripts.seed_sample_db import seed_database

            seed_database(sample_db_path)

        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE_PATH": sample_db_path,
                "DISABLE_BACKGROUND_WORKER": True,
            }
        )
        self.client = self.app.test_client()
        self.results: List[Tuple[str, bool, str]] = []

    def record(self, test_name: str, passed: bool, details: str = "") -> None:
        """Record test result."""
        self.results.append((test_name, passed, details))
        status_str = "PASS" if passed else "FAIL"
        print(f"[{status_str}] {test_name}: {details}")

    def run_all(self) -> bool:
        """Run all automated UI and route verification checks."""
        print("=" * 65)
        print("  TRAVEL ASSISTANT - AUTOMATED UI & ROUTE VALIDATION SUITE")
        print("=" * 65)

        # 1. Base Routes & Static Assets
        print("\n--- 1. Testing Core Views & Static Assets ---")
        resp = self.client.get("/")
        self.record(
            "Dashboard Root View (/)",
            resp.status_code == 200,
            f"Status {resp.status_code}",
        )

        routes_to_check = [
            "/config/credentials",
            "/config/locations",
            "/config/timetables",
            "/config/transfers",
            "/config/journeys",
            "/config/db",
            "/config/sync",
        ]
        static_assets = set()

        for route in routes_to_check:
            r = self.client.get(route)
            self.record(
                f"View Accessibility ({route})",
                r.status_code == 200,
                f"Status {r.status_code}",
            )
            soup = BeautifulSoup(r.get_data(as_text=True), "html.parser")
            for tag in soup.find_all(["link", "script", "img"]):
                src = tag.get("src") or tag.get("href")
                if src and "/static/" in src:
                    clean = src.split("?")[0]
                    if not clean.startswith("/"):
                        clean = "/" + clean
                    static_assets.add(clean)

        for asset in sorted(static_assets):
            r_asset = self.client.get(asset)
            self.record(
                f"Static Asset: {asset}",
                r_asset.status_code == 200,
                f"Status {r_asset.status_code}",
            )

        # 2. Ingress Path Header Injection
        print("\n--- 2. Testing Home Assistant Ingress Integration ---")
        ingress_path = "/api/hassio_ingress/demo-token"
        r_ing = self.client.get(
            "/config/credentials",
            headers={"X-Ingress-Path": ingress_path},
        )
        html_ing = r_ing.get_data(as_text=True)
        ingress_ok = (
            f'action="{ingress_path}/config/credentials"' in html_ing
            and f'href="{ingress_path}/static/css/tables.css' in html_ing
        )
        self.record(
            "Ingress Header Injection",
            ingress_ok,
            "Forms and assets prefixed with X-Ingress-Path",
        )

        # 3. Autocomplete & API Endpoints
        print("\n--- 3. Testing Transit Autocomplete & APIs ---")
        r_ping = self.client.get("/api/ping")
        self.record(
            "API Ping (/api/ping)",
            r_ping.status_code == 200
            and json.loads(r_ping.get_data(as_text=True)).get("status") == "ok",
            "Health check OK",
        )

        r_info = self.client.get("/api/info")
        self.record(
            "API Info (/api/info)",
            r_info.status_code == 200
            and "version" in json.loads(r_info.get_data(as_text=True)),
            "Version & metadata OK",
        )

        r_search = self.client.get("/config/search/places?q=King")
        search_data = json.loads(r_search.get_data(as_text=True))
        self.record(
            "Places Search Autocomplete",
            r_search.status_code == 200 and len(search_data) > 0,
            f"Found {len(search_data)} matching places for 'King'",
        )

        # 4. Form Submissions & Data Persistence
        print("\n--- 4. Testing Form Submissions & Grid.js Data Bindings ---")
        # Credentials save
        r_cred_post = self.client.post(
            "/config/credentials",
            data={
                "bus_api_key": "bods-automated-test-key",
                "open_api_key": "openai-automated-test-key",
                "open_api_model": "gpt-4o-mini",
                "google_maps_region": "uk",
            },
            follow_redirects=True,
        )
        self.record(
            "Credentials POST Form Submission",
            r_cred_post.status_code == 200,
            "Saved successfully",
        )

        # Locations Grid.js
        locations_payload = [
            {
                "id": "zone.home",
                "name": "Home Base",
                "latitude": 51.5300,
                "longitude": -0.1200,
                "ha": True,
            },
            {
                "id": "custom:lab",
                "name": "Innovation Lab",
                "latitude": 51.5150,
                "longitude": -0.0900,
                "ha": False,
            },
        ]
        r_loc_post = self.client.post(
            "/config/locations",
            data={"locations_json": json.dumps(locations_payload)},
            follow_redirects=True,
        )
        soup_loc = BeautifulSoup(r_loc_post.get_data(as_text=True), "html.parser")
        loc_script = soup_loc.find("script", id="initial-locations-data")
        loc_data = json.loads(loc_script.string) if loc_script else []
        self.record(
            "Locations Grid.js Data Persistence",
            any(loc.get("name") == "Innovation Lab" for loc in loc_data),
            f"Verified {len(loc_data)} locations in payload",
        )

        # Timetables Grid.js
        tt_payload = [
            {
                "name": "Automated Express Schedule",
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
                "content": {"stops": ["9100KNGX"], "trips": [{"time": "09:00"}]},
            }
        ]
        r_tt_post = self.client.post(
            "/config/timetables",
            data={"timetables_json": json.dumps(tt_payload)},
            follow_redirects=True,
        )
        soup_tt = BeautifulSoup(r_tt_post.get_data(as_text=True), "html.parser")
        tt_script = soup_tt.find("script", id="initial-timetables-data")
        tt_data = json.loads(tt_script.string) if tt_script else []
        self.record(
            "Timetables Grid.js Data Persistence",
            any(t.get("name") == "Automated Express Schedule" for t in tt_data),
            f"Verified {len(tt_data)} timetables in payload",
        )

        # Transfers Grid.js
        loc_trans_payload = [
            {
                "from_type": "rail",
                "from_id": "9100KNGX",
                "from_name": "London King's Cross",
                "to_type": "bus",
                "to_id": "490000077E",
                "to_name": "King's Cross Stop E",
                "transfer_time_minutes": 3,
                "bidirectional": True,
                "step_free": True,
                "notes": "Direct concourse connection",
            }
        ]
        plat_trans_payload = [
            {
                "location_type": "rail",
                "location_id": "9100KNGX",
                "location_name": "London King's Cross",
                "from_platform": "1",
                "to_platform": "8",
                "transfer_time_minutes": 4,
                "bidirectional": True,
                "step_free": True,
                "notes": "Footbridge",
            }
        ]
        r_tr_post = self.client.post(
            "/config/transfers",
            data={
                "location_transfers_json": json.dumps(loc_trans_payload),
                "platform_transfers_json": json.dumps(plat_trans_payload),
            },
            follow_redirects=True,
        )
        soup_tr = BeautifulSoup(r_tr_post.get_data(as_text=True), "html.parser")
        loc_tr_script = soup_tr.find("script", id="initial-location-transfers-data")
        plat_tr_script = soup_tr.find("script", id="initial-platform-transfers-data")
        loc_tr = json.loads(loc_tr_script.string) if loc_tr_script else []
        plat_tr = json.loads(plat_tr_script.string) if plat_tr_script else []
        self.record(
            "Transfers Grid.js Data Persistence",
            len(loc_tr) > 0 and len(plat_tr) > 0,
            f"Verified {len(loc_tr)} location transfers and {len(plat_tr)} platform transfers",
        )

        # Journeys Grid.js
        j_payload = [
            {
                "name": "Lab Commute",
                "from_type": "ha",
                "from_id": "zone.home",
                "from_name": "Home Base",
                "to_type": "custom",
                "to_id": "custom:lab",
                "to_name": "Innovation Lab",
                "time_settings": [{"target_arrival": "09:30"}],
            }
        ]
        r_j_post = self.client.post(
            "/config/journeys",
            data={"journeys_json": json.dumps(j_payload)},
            follow_redirects=True,
        )
        soup_j = BeautifulSoup(r_j_post.get_data(as_text=True), "html.parser")
        j_script = soup_j.find("script", id="initial-journeys-data")
        j_data = json.loads(j_script.string) if j_script else []
        self.record(
            "Journeys Grid.js Data Persistence",
            any(j.get("name") == "Lab Commute" for j in j_data),
            f"Verified {len(j_data)} journeys in payload",
        )

        # 5. British English Compliance
        print("\n--- 5. Checking British English Standards ---")
        prohibited_us_words = [
            r"\bcolor\b",
            r"\bcolors\b",
            r"\binitialize\b",
            r"\binitialized\b",
            r"\boptimizing\b",
            r"\bgrayscale\b",
        ]
        violations: Dict[str, List[str]] = {}
        for route in routes_to_check:
            r = self.client.get(route)
            text = BeautifulSoup(r.get_data(as_text=True), "html.parser").get_text()
            for pattern in prohibited_us_words:
                matches = re.findall(pattern, text, re.IGNORECASE)
                if matches:
                    violations.setdefault(route, []).extend(matches)

        self.record(
            "British English Standard Adherence",
            len(violations) == 0,
            f"Violations: {violations if violations else 'None (100% compliant)'}",
        )

        # Summary
        total = len(self.results)
        passed = sum(1 for _, s, _ in self.results if s)
        print("\n" + "=" * 65)
        print(f"  UI TESTS SUMMARY: {passed}/{total} Passed ({passed/total*100:.1f}%)")
        print("=" * 65)
        return passed == total


def main() -> None:
    """Parse CLI options and run the automated UI validation suite."""
    parser = argparse.ArgumentParser(
        description="Run automated UI and route tests for Travel Assistant."
    )
    parser.add_argument(
        "--db",
        default=None,
        help="Path to sample database file (defaults to instance/sample_travel_assistant.db).",
    )
    args = parser.parse_args()

    tester = UITester(sample_db_path=args.db)
    success = tester.run_all()
    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
