# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Interactive **Place Type Filter Chips** (`[All] [Train] [Bus] [Metro] [Tram] [Ferry] [Air] [HA] [Custom]`) pinned to the top of all place search autocomplete dropdowns across Journeys (`/config/journeys`), Transfers (`/config/transfers`), and the Timetable Grid Editor (`/config/timetables`).
- Instant re-filtering on chip click with focus retention, active filter styling, and context-aware default transport modes.
- Support for `train` alias mapping to `rail` and strict transport mode filtering in `GET /config/search/places`.
- Full-width interactive **Timetable Grid Editor** on `/config/timetables` allowing direct configuration and matrix editing of stops down the left column and trips / timings across columns.
- Transport Type classification on `Timetable` model and database schema supporting Bus (`bus`), Train / Rail (`rail`), Tram (`tram`), Metro (`metro`), Ferry (`ferry`), and Air (`air`) with Material Symbols icons and dedicated table column.
- Autocomplete stop addition in Timetable Grid Editor querying `/config/search/places` filtered by timetable transport mode while including Home Assistant zones and custom locations.
- Stop sequence management in Timetable Grid Editor with up/down reordering and deletion.
- Multi-column selection and **Duplicate & Retime** workflow supporting single-column new departure times or multi-column batch intervals and copy counts, maintaining stop travel durations and sorting columns chronologically.
- Chronological cell-level timing validation highlighting sequence errors in rose with contextual tooltips and a live validation warning banner.
- Automated SQLite schema migration in `run_migrations` for existing `timetables` tables adding `transport_type` and `content` columns without data loss.
- Automatic startup asset cache busting (`?v={{ cache_bust }}`) appended to all CSS and JavaScript imports across templates to prevent stale asset caching.
- Enhanced collapsible sections across `/config/credentials` and `/config/transfers` with arrow button toggles (`keyboard_arrow_down` when expanded, `chevron_right` when collapsed).
- Interactive API credentials status transformation on `/config/credentials` swapping between green verified `✓ Valid` badges and revealed `Check` action buttons on user edit with default collapse for passing services.
- Database storage size display hiding exact byte counts within an accessible hover tooltip on `/config/db`.
- Fixed Grid.js column widths and disabled sorting on actions and non-sortable columns across timetables, locations, journeys, transfers, and sync tables.
- Added `pytest-xdist>=3.5.0` test runner dependency for parallel test execution.
- Added argument forwarding to `scripts/run_tests.sh` to allow targeted test file execution.

- Consolidated location search endpoint (`GET /config/search/places`) providing unified multi-modal search across rail stations, bus stops, Home Assistant locations, and custom locations with standardised namespaced identifiers (`naptan:<crs>`, `atco:<code>`, `ha:<id>`, `custom:<hex>`).
- Removed obsolete, redundant search endpoints (`/api/timetables/search`, `/config/timetables/search`, `/config/transfers/search`, and `/config/journeys/search`) in favour of the single `/config/search/places` endpoint.

### Removed
- Obsolete backwards-compatibility aliases in `DATASOURCE_REGISTRY` (`bods`, `s3`, `darwin`, `openai`, `ha`, `googlemaps`, `maps`) in favour of canonical service keys.
- Redundant service aliases from credential validation dispatcher (`validate_service_credentials`).
- Obsolete constant re-exports in `app/validators/__init__.py` and view helper re-exports in `app/views/config/__init__.py`.
- Legacy stop type search aliases (`train`, `station`, `stations`, `bus_stop`, `bus_stops`) in `Stop.search` in favour of canonical `rail` and `bus` modes.
- Legacy `crs_code` dictionary fallback in `Stop.bulk_upsert`.
### Changed
- Optimised unit test database fixtures in `app/tests/conftest.py` to use fast shared in-memory SQLite URI databases (`file:mem_test_{uuid}?mode=memory&cache=shared`), eliminating disk I/O, temporary file overhead, and redundant table migration loops.
- Enhanced `create_sqlite_database` and `get_db_stats` in `app/db/core.py` to support SQLite URI paths, in-memory configurations, and memory-safe file size telemetry.
- Eliminated circular import dependencies between `app.db` and `app.models` by removing redundant model re-exports from `app/db/__init__.py`.
- Guarded background transit worker daemon in `app/main.py` to prevent background thread startup during module imports and unit test discovery.
- Mocked Darwin SOAP fallback requests in `test_validate_train_live_openapi_not_found` and sync routines in `test_api_sync_endpoints` to eliminate unmocked external network requests and socket timeouts.
- Refactored monolithic configuration views (`app/views/config.py`) into a modular Python package (`app/views/config/`) with separate modules for `credentials`, `timetables`, `locations`, `places`, `transfers`, `journeys`, and database `sync`.
- Standardised and simplified table action buttons across all Grid.js configuration tables (`Locations`, `Journeys`, `Timetables`, `Transfers`, and `Sync`) into compact 28x28px icon-only tinted buttons (`edit`, `delete`, `visibility`, `refresh`) with contextual native HTML tooltips (`title` and `aria-label`).
- Updated API credentials check buttons on `/config/credentials` into compact 28x28px icon-only check buttons matching the unified action icon design.
- Tightened Actions column widths across data tables to eliminate redundant whitespace.
- Replaced separate `bus_stops` and `stations` synchronisation routines and database tables with the consolidated `stops` pipeline on `/config/sync` and `/config/db`.
- Updated timetable, transfer, and journey location search endpoints (`/config/timetables/search`, `/config/transfers/search`, `/config/journeys/search`) to query the unified `Stop` model with `stop_type` filtering.
- Automated schema migration in `run_migrations` dropping legacy `bus_stops` and `stations` tables and creating `stops`.

### Fixed
- Fixed timetable table action button click delegation on `/config/timetables`, resolving unresponsive table grid (`grid_on`), metadata edit, and delete buttons to open the interactive Timetable Grid Editor and edit dialogues.
- Restored configuration UI design standards, including 80% viewport width modal dialogues across locations, journeys, and timetables, 15-minute interval time datalists, clean action bar Save/Discard icons and initial disabled states without redundant status badges, and single-page table pagination suppression rules in CSS.
- Restored human-readable relative timestamps ("Just now", "2 hours ago") with formatted hover tooltips and dynamic 30-second interval updates on the Background Sync page (`/config/sync`).
- Fixed Google Maps API credential validation error (`HTTP Error: 400`) by executing an active geocoding probe query instead of an empty query parameter.
- Disabled browser caching across all configuration pages and endpoints by serving explicit `Cache-Control: no-cache, no-store, must-revalidate, max-age=0`, `Pragma: no-cache`, and `Expires: 0` response headers alongside HTML head meta tags, ensuring settings changes appear immediately without stale browser caching.
- Eliminated all synthetic placeholder records (`S3-HUB`, `LDBWS-HUB`, `BODS-FEED-{id}`, and `DS-{id}` routes).
- Connected bus stops and railway station synchronisation to public UK NaPTAN open dataset feeds for genuine, complete access node and rail station indexing.
- Fixed visibility of Home Assistant location synchronisation (`locations`) on the Background Sync page (`/config/sync`) by marking the `locations` table as syncable in database telemetry (`get_db_stats`) and including it in client-side syncable table definitions.

### Added
- Unique text ID column (`id`) on the `locations` table and `Location` model with `ha:<object_id>` format for synchronised Home Assistant zones and `custom:<hex>` format for manual entries.
- Automatic database migration for legacy `locations` tables to text primary keys while backfilling and preserving existing records.
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
