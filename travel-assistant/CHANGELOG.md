# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Integrated cached transit datasets (`stations`, `bus_stops`, and `bus_routes`) with the Timetables configuration page (`/config/timetables`):
  - **Train Journey Selection**: Two-station bi-directional journey picker with asynchronous autocomplete querying cached rail stations, automatically formulating timetable names (`Station 1 ↔ Station 2`) and identifiers (`CRS1 ↔ CRS2`).
  - **Bus Stop & Route Selection**: Two-step bus picker workflow to select a bus stop from cached stops, followed by an associated bus route from cached routes, automatically formulating timetable names (`Route [Route] at [Stop Name]`) and identifiers (`[Route]@[Stop ATCO Code]`).
  - **Dataset Cache Prerequisite Checks**: Contextual warning alerts and buttons directing users to Database Settings (`/config/db`) when datasets have not been synchronised.
- Added asynchronous `search` query methods with ranking and substring matching to `StationRepository`, `BusStopRepository`, and `BusRouteRepository`.
- Enhanced `GET /config/timetables/search` and `GET /api/timetables/search` supporting `type` filtering (`station`, `bus_stop`, `bus_route`, `status`), limit controls, and dataset cache availability reporting (`is_cached`, `cache_counts`).
- Added RESTful API endpoint `POST /api/sync` and `POST /api/sync/<table_name>` for programmatic dataset synchronisation.
- Database schema tables for transit datasets: `bus_routes`, `bus_stops`, `stations`, and `sync_metadata`.
- Repositories in `app.db` (`BusRouteRepository`, `BusStopRepository`, `StationRepository`, and `SyncMetadataRepository`) with atomic bulk upserting, indexing, and lookup operations.
- Background synchronisation daemon (`TransitBackgroundWorker`) running periodic hourly checks to automatically update transit datasets older than 24 hours (1 day).
- Transit synchronisation provider engine (`app.sync`) integrating with Bus Open Data Service (BODS API) and Train S3 / Darwin credentials with graceful skipping when unconfigured.
- Interactive Database configuration page (`/config/db`) enhancements:
  - Added "Last Updated" timestamp column with status badges (`Synced`, `Syncing...`, `Unconfigured`, `Error`, `Managed`).
  - Added on-demand refresh trigger buttons with animated spinning states and toast notifications per table.
  - Added "Sync All Datasets" action button in the Database Storage Overview header.
- Persistent SQLite database backend and `SettingsRepository` for application configuration and credentials.
- Settings navigation cog button in the web UI header.
- Settings page router (`/config/xxx`) using Jinja2 templates and the Post/Redirect/Get pattern.
- API credentials management page (`/config/credentials`) supporting Bus API keys, Train S3 bucket details, Train live credentials, and Open API credentials.
- Asynchronous credential validation endpoint (`POST /config/credentials/validate`) supporting live verification for Bus Open Data Service (BODS REST API), AWS S3 buckets (`boto3`), National Rail LDBWS (`bravado` OpenAPI / SOAP), and OpenAI services (`openai`).
- OpenAI chat model dropdown (`open_api_model`) auto-populated from discovered endpoint models on credential validation, with chat model filtering and standard fallback choices.
- External OpenAI model pricing documentation link on the credentials configuration page next to the model selection dropdown.
- Real-time client-side status badge indicators and on-demand "Re-check" buttons on the credentials configuration page that validate populated credentials on page load and on user request.
- Timetables configuration page (`/config/timetables`) with CDN-hosted Grid.js table supporting client-side search, sorting, pagination, and deletion.
- Transfers configuration page (`/config/transfers`) with stacked CDN-hosted Grid.js tables for managing inter-location walking links and intra-station platform transfers.
- Dedicated location lookup and autocomplete endpoint (`GET /config/transfers/search`) querying local SQLite `stations` and `bus_stops` datasets with search deduplication and fallback support.
- SQLite schema tables `location_transfers` and `platform_transfers` with index optimisations.
- `LocationTransferRepository`, `PlatformTransferRepository`, and `TransferRepository` in `app/db/transfers.py` providing transactional batch replacement, CRUD helpers, and lifecycle management.
- Search and lookup endpoint (`GET /api/timetables/search` and `/config/timetables/search`) for bus routes and rail stations with autocomplete in the Add Timetable modal.
- `TimetableRepository` in SQLite for managing persisted timetable schedules.
- Unified left sidebar configuration layout (`config_base.html`) across `/config/*` sections with collapsible mobile drawer.
- Unsaved changes protection manager (`ConfigDirtyManager`) intercepting page reloads, tab navigation, and breadcrumbs with warning prompts.
- Standard action bar with dynamic **Save Changes** and **Discard Changes** across all configuration sections.
- Comprehensive unit tests covering database lifecycle, repository operations, credential validators, timetable management, transit search lookups, transfers management, and configuration views with 100% code coverage.



### Changed
- Refactored `app/db` into a modular package with `BaseRepository` (`app/db/base.py`) providing unified connection management, `executemany` batch write optimisation, and timestamp formatting helpers.
- Modularised `app/validators` into a domain-driven package (`app/validators/{bus,s3,train_live,openai,dispatcher,constants}.py`) with preserved backward-compatible top-level exports.
- Decomposed monolithic `test_validators.py` (706 lines) into isolated unit test modules under `app/tests/validators/` maintaining 100% test coverage.
- Extracted client-side JavaScript and CSS from Jinja templates into separate static files (`app/static/js/dirty-manager.js`, `app/static/js/credentials.js`, `app/static/js/timetables.js`, and `app/static/css/timetables.css`), significantly reducing template sizes and complexity.
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
