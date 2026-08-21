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

        # Always initialise clean sample DB for UI test run
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
            "/config/walking",
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

        r_download = self.client.get("/config/db/download")
        self.record(
            "Database File Download (/config/db/download)",
            r_download.status_code == 200
            and r_download.data.startswith(b"SQLite format 3\x00"),
            f"Downloaded valid SQLite payload ({len(r_download.data)} bytes)",
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
        locations_payload = {
            "added": [
                {
                    "id": "custom:lab",
                    "name": "Innovation Lab",
                    "latitude": 51.5150,
                    "longitude": -0.0900,
                    "ha": False,
                },
            ],
            "updated": [],
            "deleted": [],
        }
        r_loc_post = self.client.post(
            "/config/locations/data",
            json=locations_payload,
        )
        r_loc_get = self.client.get("/config/locations/data")
        loc_data = (
            r_loc_get.get_json().get("data", [])
            if r_loc_get.status_code == 200
            else []
        )
        self.record(
            "Locations Grid.js Data Persistence",
            r_loc_post.status_code == 200
            and any(loc.get("name") == "Innovation Lab" for loc in loc_data),
            f"Verified {len(loc_data)} locations in payload",
        )

        # Timetables Grid.js
        tt_payload = {
            "added": [
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
            ],
            "updated": [],
            "deleted": [],
        }
        r_tt_post = self.client.post(
            "/config/timetables/data",
            json=tt_payload,
        )
        r_tt_get = self.client.get("/config/timetables/data")
        tt_data = (
            r_tt_get.get_json().get("data", [])
            if r_tt_get.status_code == 200
            else []
        )
        self.record(
            "Timetables Grid.js Data Persistence",
            r_tt_post.status_code == 200
            and any(t.get("name") == "Automated Express Schedule" for t in tt_data),
            f"Verified {len(tt_data)} timetables in payload",
        )

        # Transfers Grid.js
        plat_trans_payload = {
            "added": [
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
            ],
            "updated": [],
            "deleted": [],
        }
        r_tr_post = self.client.post(
            "/config/transfers/data",
            json=plat_trans_payload,
        )
        r_tr_get = self.client.get("/config/transfers/data")
        plat_tr = (
            r_tr_get.get_json().get("data", [])
            if r_tr_get.status_code == 200
            else []
        )
        self.record(
            "Transfers Grid.js Data Persistence",
            r_tr_post.status_code == 200 and len(plat_tr) > 0,
            f"Verified {len(plat_tr)} platform transfers in payload",
        )

        # Journeys Grid.js
        j_payload = {
            "added": [
                {
                    "name": "Lab Commute",
                    "from_type": "ha",
                    "from_id": "zone.home",
                    "from_name": "Home Base",
                    "to_type": "custom",
                    "to_id": "custom:lab",
                    "to_name": "Innovation Lab",
                    "time_settings": [],
                }
            ],
            "updated": [],
            "deleted": [],
        }
        r_j_post = self.client.post(
            "/config/journeys/data",
            json=j_payload,
        )
        r_j_get = self.client.get("/config/journeys/data")
        j_data = (
            r_j_get.get_json().get("data", [])
            if r_j_get.status_code == 200
            else []
        )
        self.record(
            "Journeys Grid.js Data Persistence",
            r_j_post.status_code == 200
            and any(j.get("name") == "Lab Commute" for j in j_data),
            f"Verified {len(j_data)} journeys in payload",
        )

        # Walking Grid.js
        w_payload = {
            "added": [
                {
                    "start_type": "ha",
                    "start_id": "zone.home",
                    "start_name": "Home Base",
                    "finish_type": "custom",
                    "finish_id": "custom:lab",
                    "finish_name": "Innovation Lab",
                    "time_needed_minutes": 15,
                    "bidirectional": True,
                }
            ],
            "updated": [],
            "deleted": [],
        }
        r_w_post = self.client.post(
            "/config/walking/data",
            json=w_payload,
        )
        r_w_get = self.client.get("/config/walking/data")
        w_data = (
            r_w_get.get_json().get("data", [])
            if r_w_get.status_code == 200
            else []
        )
        self.record(
            "Walking Grid.js Data Persistence",
            r_w_post.status_code == 200
            and any(w.get("time_needed_minutes") == 15 for w in w_data),
            f"Verified {len(w_data)} walking routes in payload",
        )

        # Sync Datasets Grid.js & Human Display Labels
        r_sync_get = self.client.get("/config/sync/data")
        sync_data = (
            r_sync_get.get_json().get("data", [])
            if r_sync_get.status_code == 200
            else []
        )
        r_sync_js = self.client.get("/static/js/sync.js")
        sync_js_content = (
            r_sync_js.get_data(as_text=True) if r_sync_js.status_code == 200 else ""
        )
        has_human_titles = (
            "Stop Interchanges" in sync_js_content
            and "transfer_within_a_station" in sync_js_content
            and "Transit Stops (NaPTAN)" in sync_js_content
        )
        self.record(
            "Sync Datasets Grid.js Data & Human Labels",
            r_sync_get.status_code == 200
            and len(sync_data) >= 7
            and has_human_titles,
            f"Verified {len(sync_data)} sync datasets with human labels",
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
