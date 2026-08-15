# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Database schema tables for transit datasets: `bus_routes`, `bus_stops`, `stations`, and `sync_metadata`.
- Repositories in `app.db` (`BusRouteRepository`, `BusStopRepository`, `StationRepository`, and `SyncMetadataRepository`) with atomic bulk upserting, indexing, and lookup operations.
- Background synchronisation daemon (`TransitBackgroundWorker`) running periodic hourly checks to automatically update transit datasets older than 24 hours (1 day).
- Transit synchronisation provider engine (`app.sync`) integrating with Bus Open Data Service (BODS API) and Train S3 / Darwin credentials with graceful skipping when unconfigured.
- Interactive Database configuration page (`/config/db`) enhancements:
  - Added "Last Updated" timestamp column with status badges (`Synced`, `Syncing...`, `Unconfigured`, `Error`, `Managed`).
  - Added on-demand refresh trigger buttons with animated spinning states and toast notifications per table.
  - Added "Sync All Datasets" action button in the Database Storage Overview header.
- RESTful API endpoints `POST /api/sync/<table_name>` and `POST /api/sync` for programmatic dataset update triggering.
- Persistent SQLite database backend and `SettingsRepository` for application configuration and credentials.

- Settings navigation cog button in the web UI header.
- Settings page router (`/config/xxx`) using Jinja2 templates and the Post/Redirect/Get pattern.
- API credentials management page (`/config/credentials`) supporting Bus API keys, Train S3 bucket details, Train live credentials, and Open API credentials.
- Asynchronous credential validation endpoint (`POST /config/credentials/validate`) supporting live verification for Bus Open Data Service (BODS REST API), AWS S3 buckets (`boto3`), National Rail LDBWS (`bravado` OpenAPI / SOAP), and OpenAI services (`openai`).
- OpenAI chat model dropdown (`open_api_model`) auto-populated from discovered endpoint models on credential validation, with chat model filtering and standard fallback choices.
- External OpenAI model pricing documentation link on the credentials configuration page next to the model selection dropdown.
- Real-time client-side status badge indicators and on-demand "Re-check" buttons on the credentials configuration page that validate populated credentials on page load and on user request.
- Timetables configuration page (`/config/timetables`) with CDN-hosted Grid.js table supporting client-side search, sorting, pagination, and deletion.
- Database statistics page (`/config/db`) displaying total database file size, SQLite storage path, and user table row counts with live refresh.
- `get_db_stats` and `format_file_size` utilities in `app.db` for inspecting database storage and discovering schema tables.
- Left sidebar navigation link for Database section with dedicated icon and active state styling.
- Search and lookup endpoint (`GET /api/timetables/search` and `/config/timetables/search`) for bus routes and rail stations with autocomplete in the Add Timetable modal.
- `TimetableRepository` in SQLite for managing persisted timetable schedules.
- Unified left sidebar configuration layout (`config_base.html`) across `/config/*` sections with collapsible mobile drawer.
- Unsaved changes protection manager (`ConfigDirtyManager`) intercepting page reloads, tab navigation, and breadcrumbs with warning prompts.
- Standard action bar with dynamic **Save Changes** and **Discard Changes** across all configuration sections.
- Comprehensive unit tests covering database lifecycle, repository operations, database statistics, credential validators, timetable management, and configuration views with 100% code coverage.



### Changed
- Removed the Columns column from the Database Tables overview table on the `/config/db` configuration page to streamline the UI layout.
- Refactored `app/db` into a modular package with per-table repository modules (`app/db/settings.py` and `app/db/timetables.py`) and connection lifecycle management in `app/db/core.py`, while maintaining top-level `app.db` exports.
- Migrated frontend styling from custom vanilla CSS to Tailwind CSS v4 via Browser CDN.
- Modernised UI with responsive layout, automated dark mode support via `prefers-color-scheme`, and pulsing status animations.
- Removed legacy `style.css` stylesheet.

## [0.1.0] - 2026-08-15



### Added
- Initial scaffolding for Travel Assistant Home Assistant Add-on.
- Flask-based backend service with "Hello World" single page dashboard.
- Home Assistant Ingress dynamic routing support (`X-Ingress-Path`).
- Multi-stage Debian Bookworm Dockerfile.
- Unit testing suite with pytest and code coverage reporting.
- Development automation scripts (`make_venv.sh`, `run_tests.sh`, `run_dev.sh`, `verify_all.sh`).
- GitHub Actions CI/CD workflows for PR testing, multi-arch builds (`amd64`, `aarch64`), automated changelog drafting, and release publishing.
