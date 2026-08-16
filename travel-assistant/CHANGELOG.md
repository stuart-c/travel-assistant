# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Persistent SQLite database backend and `SettingsRepository` for application configuration and credentials.
- Settings navigation cog button in the web UI header.
- Settings page router (`/config/xxx`) using Jinja2 templates and the Post/Redirect/Get pattern.
- API credentials management page (`/config/credentials`) supporting Bus API keys, Train S3 bucket details, Train live credentials, Open API credentials, and Google Maps API credentials with custom region bias.
- Google Maps client library (`GoogleMapsClient`) and validator (`validate_google_maps_api_key`) supporting geocoding, reverse geocoding, distance matrix, directions, and zero-cost credential probe verification.
- Added `googlemaps>=4.10.0` dependency to `requirements.txt`.
- Asynchronous credential validation endpoint (`POST /config/credentials/validate`) supporting live verification for Bus Open Data Service (BODS REST API), AWS S3 buckets (`boto3`), National Rail LDBWS (`bravado` OpenAPI / SOAP), OpenAI services (`openai`), and Google Maps Platform services (`googlemaps`).

- OpenAI chat model dropdown (`open_api_model`) auto-populated from discovered endpoint models on credential validation, with chat model filtering and standard fallback choices.
- External OpenAI model pricing documentation link on the credentials configuration page next to the model selection dropdown.
- Real-time client-side status badge indicators and on-demand "Re-check" buttons on the credentials configuration page that validate populated credentials on page load and on user request.
- Timetables configuration page (`/config/timetables`) with CDN-hosted Grid.js table supporting client-side search, sorting, pagination, and deletion.
- Transfers configuration page (`/config/transfers`) with stacked CDN-hosted Grid.js tables for managing inter-location walking links and intra-station platform transfers.
- Locations configuration page (`/config/locations`) with Grid.js table and Leaflet interactive map modal dialogue supporting add, edit, delete, and two-way coordinate synchronisation.
- Journeys configuration page (`/config/journeys`) with CDN-hosted Grid.js table, live search autocompletion for 4 location types (Train, Bus, Home Assistant, and Custom), and multi-time-window modal dialogue.
- Peewee database model `Journey` and schema table `journeys` for persisting journeys and structured JSON time settings.
- Location lookup endpoint (`GET /config/journeys/search`) supporting rail stations, bus stops, Home Assistant locations, and custom locations with visual indicators and icons.
- Home Assistant location synchronisation (`ha_locations`) importing all Home Assistant zones (`zone.*` entities) daily and on-demand.
- Boolean flag `ha` on `Location` model and schema migration for `locations` table to distinguish Home Assistant synchronised locations from manual entries.
- UI protections and read-only View modal dialogue on `/config/locations` preventing direct editing or deletion of Home Assistant synchronised locations.
- `HomeAssistantClient` datasource client in `app/datasources/homeassistant.py` communicating with Home Assistant Core API via Supervisor or `HA_URL` / `HA_TOKEN`.
- Background worker integration and on-demand synchronisation on `/config/sync` for Home Assistant locations.
- Granted Home Assistant Core API permissions via `homeassistant_api: true` in `travel-assistant/config.yaml`.
- Peewee database model `Location` and schema table `locations` for persisting named geographic coordinates.
- Dedicated location lookup and autocomplete endpoint (`GET /config/transfers/search`) querying local SQLite `stations` and `bus_stops` datasets with search deduplication and fallback support.
- SQLite schema tables `location_transfers` and `platform_transfers` with index optimisations.
- `LocationTransferRepository`, `PlatformTransferRepository`, and `TransferRepository` in `app/db/transfers.py` providing transactional batch replacement, CRUD helpers, and lifecycle management.
- Search and lookup endpoint (`GET /api/timetables/search` and `/config/timetables/search`) for bus routes and rail stations with autocomplete in the Add Timetable modal.
- `TimetableRepository` in SQLite for managing persisted timetable schedules.
- Unified left sidebar configuration layout (`config_base.html`) across `/config/*` sections with collapsible mobile drawer.
- Unsaved changes protection manager (`ConfigDirtyManager`) intercepting page reloads, tab navigation, and breadcrumbs with warning prompts.
- Standard action bar with dynamic **Save Changes** and **Discard Changes** across all configuration sections.
- Dedicated Background Synchronisation page at `/config/sync` featuring Grid.js interactive table for cached transit datasets (Bus Routes, Bus Stops, Train Stations), "Last updated" timestamps, status badges, per-table "Refresh" triggers, and a top "Refresh All Datasets" action without horizontal scrollbars, search, or pagination.
- Restored Database storage page (`/config/db`) displaying the database disk size card alongside a clean, non-paginated 2-column Grid.js table of SQLite schema tables and persisted row counts.
- Relocated **Save Changes** and **Discard Changes** action bar to the top header row of editable configuration pages (`/config/credentials`, `/config/timetables`, `/config/transfers`), omitting action bars on read-only pages.
- Converted Add Timetable and Add Transfer action buttons into compact, rounded `+` icon-only buttons with accessible labels and tooltips.
- Unnumbered API credentials section headings ("Bus API Key", "Train S3 Bucket Details", "Train Live Credentials", "OpenAI & LLM Credentials").
- Replaced "Re-check" buttons with interactive "Check" buttons on the API Credentials page that remain disabled on page load and dynamically enable when text inputs are modified.
- Fixed BODS endpoint resolution in `sync_bus_stops` to correctly target dataset feeds.
- Comprehensive unit tests covering database lifecycle, repository operations, credential validators, timetable management, transit search lookups, transfers management, and configuration views with 100% code coverage.

### Changed
- Updated `Timetable` database model and schema table `timetables` to support timetable name, optional start and end date validity ranges, and individual day operating flags (`monday`, `tuesday`, `wednesday`, `thursday`, `friday`, `saturday`, `sunday`, `bank_holiday`).
- Redesigned Timetables configuration page (`/config/timetables`) and modal dialog with day selection toggles, quick-select helper buttons (*All*, *Weekdays*, *Weekends*, *Clear*), date range pickers with validation, and support for adding and editing timetable entries.
- Standardised page container width across the entire application to `max-w-5xl`, eliminating layout shifting between the Overview dashboard and Configuration pages.
- Standardised status badge and pill styling across all pages to `inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold` with consistent dark-mode ring borders.
- Established strict button sizing tiers: Medium (`rounded-xl px-4 py-2 text-sm font-semibold`) for primary/secondary actions, and Compact (`rounded-lg px-3 py-1.5 text-xs font-semibold`) for table rows and inline actions.
- Unified application copy and terminology:
  - Standardised on **"Refresh"** across all dataset operations on `/config/db` (*"Refresh All Datasets"*, *"Refresh"*, *"Refreshed"*, *"Refreshing..."*, *"Reload Page"*).
  - Renamed Section 4 on the API credentials page to **"4. OpenAI & LLM Credentials"**.
  - Standardised transit modes to **"Bus Route"** and **"Rail Station"** across all labels, selectors, and badges.
  - Renamed Add Timetable modal submit button to **"Add Timetable"**.
- Refactored `app/db` into a modular package with `BaseRepository` (`app/db/base.py`) providing unified connection management, `executemany` batch write optimisation, and timestamp formatting helpers.
- Modularised `app/validators` into a domain-driven package (`app/validators/{bus,s3,train_live,openai,dispatcher,constants}.py`) with preserved backward-compatible top-level exports.
- Decomposed monolithic `test_validators.py` (706 lines) into isolated unit test modules under `app/tests/validators/` maintaining 100% test coverage.
- Extracted client-side JavaScript and CSS from Jinja templates into separate static files (`app/static/js/dirty-manager.js`, `app/static/js/credentials.js`, `app/static/js/timetables.js`, `app/static/js/db.js`, and `app/static/css/tables.css`), significantly reducing template sizes and complexity.
- Migrated frontend styling from custom vanilla CSS to Tailwind CSS v4 via Browser CDN.
- Modernised UI with responsive layout, automated dark mode support via `prefers-color-scheme`, and pulsing status animations.
- Removed legacy `style.css` stylesheet.

### Removed
- Removed hardcoded sample timetable dataset (`SAMPLE_TIMETABLE_DATA`) and location search dataset (`SAMPLE_LOCATION_SEARCH_DATA`) from `app/views/config.py`, ensuring all search endpoints strictly query local cached SQLite datasets and return clean empty states when unpopulated.

### Fixed
- Added automatic SQLite schema migration in `run_migrations` for legacy `timetables` tables, resolving `peewee.OperationalError: no such column: t1.start_date` on `/config/timetables` while preserving existing timetable records.

## [0.1.0] - 2026-08-15

### Added
- Initial scaffolding for Travel Assistant Home Assistant Add-on.
- Flask-based backend service with "Hello World" single page dashboard.
- Home Assistant Ingress dynamic routing support (`X-Ingress-Path`).
- Multi-stage Debian Bookworm Dockerfile.
- Unit testing suite with pytest and code coverage reporting.
- Development automation scripts (`make_venv.sh`, `run_tests.sh`, `run_dev.sh`, `verify_all.sh`).
- GitHub Actions CI/CD workflows for PR testing, multi-arch builds (`amd64`, `aarch64`), automated changelog drafting, and release publishing.
