# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Enhanced application-wide system and background process logging across `main.py`, `SyncWorker`, dataset synchronisation pipelines (`stops`, `bus_routes`, `train_timetables`, `bus_timetables`, `stop_interchanges`, `ha_locations`, `walking`, `journey_routes`), configuration changeset managers, credential validation probes, database lifecycle operations, and route discovery engines. Background process executions, trigger reasons, pipeline stages, duration measurements, and record summaries are now emitted at `INFO` level with structured British English formatting.
- Added `vis-network` JavaScript library integration in the Journey modal dialogue to render an interactive, vertical Directed Acyclic Graph (DAG) for calculated routes. Topological route corridors are merged into a unified top-to-bottom hierarchy connecting the single origin and destination nodes, with intermediate calling points, mode-coloured edges (walking, train, bus, metro, tram, ferry), rich hover tooltips displaying line and operator details, fit-to-view controls, and seamless light/dark theme adaptation.
- Added hourly background synchronisation job (`journey_routes`) that automatically discovers and computes multi-modal topological routes for configured journeys lacking calculated routes (`calculated_routes is NULL`), with automatic asynchronous re-calculation triggers on journey creation/modification and upon successful walking or transit timetable synchronisations.
- Added `calculated_routes` JSON column to the `Journey` model and SQLite `journeys` table with automated schema migration, and added a 2-tab navigation interface (**Journey Details** and **Calculated Routes**) in the Journey modal dialogue that displays raw calculated route paths when data is present and automatically clears the field upon modifying journey details.
- Added multi-modal Journey Planner library service (`app/services/planner/`) implementing Mode 1 topological route discovery with NetworkX multi-directed graph traversal and 4-rule pruning (Last Possible Interchange, Subsumed Detours, Pareto Dominance, Senseless Detours), and Mode 2 scheduled itinerary planning with an in-memory RAPTOR solver supporting `depart`, `arrive`, and `window` timing constraints, transfer slack scoring, and 3-tier transfer hierarchy resolution.
- Added comprehensive unit test suite (`app/tests/test_journey_planner.py`) verifying topological path discovery, RAPTOR trip scheduling, date validity filtering, transfer hierarchy precedence, and descriptive error diagnostics.
- Added comprehensive technical architecture specification (`docs/architecture/03_journey_routing_and_planning_process.md`) defining the programmatic, multi-modal routing and itinerary planning process using pure SQLite database data (RAPTOR search engine, dual-mode topological corridor discovery and time-dependent trip scheduling, multi-criteria Pareto frontier ranking, and hierarchical transfer resolution).
- Added weekly background synchronisation process and `stop_interchanges` table discovering nearby transit stop interchanges within 250 metres across all transport modes using SQLite R*Tree geospatial indexing on British National Grid `easting` and `northing` coordinates. Includes the `StopInterchange` model, `sync_stop_interchanges` pipeline, automated re-sync trigger upon `stops` ingest, and full integration into `SYNC_REGISTRY` and `/config/sync`.

### Removed
- Removed obsolete `rail_references` table, model (`RailReference`), datasource client (`RailReferencesClient`), and background sync task (`sync_rail_references`), as NaPTAN no longer provides the legacy `RailReferences.csv` endpoint and multi-modal transit linking is handled directly via the unified `stops` table and Darwin station resolvers. A migration automatically drops any legacy `rail_references` database tables on startup.

### Changed
- Synchronised project documentation across README, `travel-assistant/DOCS.md`, architecture specifications (`03_journey_routing_and_planning_process.md`), and `/browser` testing runbooks (`docs/testing/05_journeys.md`, `02_locations.md`, `06_ingress_and_theme.md`) to reflect the tabbed Journey modal dialogue, calculated routes inspection, completed Journey Planner library service, and British English language standards.
- Removed hardcoded `KNOWN_TIPLOCS` dictionary in `TrainS3Client` and standardised train timetable stop generation to use canonical NaPTAN ATCO codes (`9100...`) mapped dynamically from Darwin XML TIPLOC codes and NaPTAN rail stop lookups, eliminating CRS stop ID mismatches across multi-modal `stop_interchanges` and shuttle bus timetables.

### Fixed
- Fixed BODS TransXChange bus timetable parsing dropping preceding and opposing directional corridors (such as inbound routes serving Sweyns Mead) due to an unindented timetable creation block in `BodsClient.parse_transxchange_xml`.
- Fixed Darwin rail timetable synchronisation downloading only a single snapshot from AWS S3 (which omitted weekday timetables when running on weekends) by discovering snapshots across distinct operational day profiles (weekday, Saturday, and Sunday) in `TrainS3Client.get_latest_timetable_keys_by_day_profile` and merging national timetables across day profiles.
- Fixed Route Finder path weighting penalising intermediate calling points on continuous transit lines by assigning unit transit edge weights ($w = 1.0$) and applying explicit transfer penalties ($w = \text{duration} + 8.0$) to vehicle and platform interchanges, ensuring direct and low-transfer train corridors (such as Stevenage to Cambridge with 1 change) are prioritised over multi-transfer detours.
- Added direct transit drop-off support in Route Finder allowing services (such as campus shuttle buses) to terminate directly at configured location endpoints without requiring artificial final walking links.
- Expanded Route Finder corridor exploration across all reachable origin access points (e.g. Sweyns Mead, Emperors Gate, Emperor's Head PH) and increased candidate capacity to 50 routes (`max_routes=50`, `max_stages=10`), with comprehensive diagnostic logging detailing raw options, unique paths, corridor groupings, and duration pruning counts.
- Fixed Route Finder generating single suboptimal routes or disjointed multi-train hops by enforcing transit line continuity (`timetable_id` matching across consecutive calling points) and exploring paths across all reachable access stops to generate multiple diverse viable route corridors.
- Fixed double-prefixed location identifiers (e.g. `ha:ha:office`) appearing in journey routing diagnostic warning logs.
- Fixed topological journey route graph connectivity failures where ATCO code prefix mismatches (`atco:9100...` vs `9100...`), double-prefixed Home Assistant/custom locations (`ha:ha:...`), and missing stop interchange edges prevented transit corridors from being identified and rendered in the Journey Calculated Routes Directed Acyclic Graph (DAG) viewer.
- Fixed route calculation performance bottlenecks by replacing unindexed full-table scans over `stop_interchanges` with filtered batch queries on stops present in the active subgraph, filtering same-station platform transfers by station code, and adopting `nx.shortest_simple_paths` on simplified graph projections for sub-second corridor generation.
- Fixed silent failures during background journey route calculation by elevating `JourneyPlanningError` from `DEBUG` to `WARNING` in `app/sync/journey_sync.py`, emitting detailed diagnostics with journey IDs, names, active operating days, endpoint IDs, and specific routing failure reasons.
- Standardised transit and location identifier prefix scoping across data synchronisation pipelines, timetable parsers, configuration interfaces, sample database seeds, and test suites. Polymorphic stop and node references in `Timetable.content.stops` and multi-modal stage transitions now consistently include explicit namespace prefixes (`naptan:`, `atco:`, `ha:`, `custom:`, `tiploc:`), while strictly typed station identifiers in platform transfers omit redundant prefixes.
- Fixed bus timetable synchronisation creating multiple duplicate timetable matrices for the same route and operating days (e.g. SB1 circular variations and short-working runs) by consolidating route pattern variations into a single master stop sequence using order-preserving topological insertion and padding unserved intermediate calling points with empty time cells (`""`).
- Fixed bus timetables displaying odd operating days (such as Sunday-only for routes expected on weekdays) by parsing `<OperatingProfile>` at the `<VehicleJourney>` level in TransXChange XML feeds, correctly overriding service-level defaults so that weekday, Saturday, and Sunday vehicle journeys produce distinct timetables with accurate operating day flags.
- Fixed rail timetables hardcoding all operating days (`monday..sunday=True` and `bank_holiday=True`) by classifying Darwin S3 XML passenger journeys according to their Scheduled Start Date (`ssd`), partitioning corridors into separate Weekday (`Mon-Fri`), Saturday (`Sat`), and Sunday (`Sun`) timetables with exact boolean day flags.
- Fixed bus timetables being truncated during BODS synchronisation by consolidating TransXChange journey pattern fragments into master route corridors with superset stop alignment and merging trips across dataset files, preserving early morning peak journeys and complete circular route terminations.
- Fixed raw database table identifier `stop_interchanges` displaying in place of a human-readable dataset title on the Background Synchronisation view (`/config/sync`) by defining a user-friendly display title ("Stop Interchanges") and dedicated Material Symbols icon (`transfer_within_a_station`) in `sync.js`.
- Fixed rail transport type label wrapping awkwardly onto multiple lines by updating the display label from "Train / Rail" to "Train" across models, selectors, and UI badge renderers with `whitespace-nowrap` protection.
- Fixed bus timetables not being downloaded during BODS synchronisation by resolving target bus stop references with prefix awareness (`naptan:` vs `atco:`) to their 12-digit ATCO codes before matching against TransXChange XML `<StopPointRef>` elements in `sync_bus_timetables`.
- Fixed BODS dataset listing queries truncating at single-page limits (which omitted published datasets such as Arriva Thameside in Hertfordshire) by implementing multi-page offset-based pagination across `BodsClient.fetch_routes` and `BodsClient.fetch_timetables`.
- Fixed BODS bus timetable synchronisation failing with HTTP 400 Bad Request ("Unsupported query parameter: boundingBox") by removing the unsupported `boundingBox` parameter from dataset metadata queries in `BodsClient.fetch_timetables` and `sync_bus_timetables`, relying on valid `adminArea` filtering.
- Fixed synchronisation errors and skipped status diagnostics (such as bus timetable or bus route synchronisation failures) only appearing on the Web UI by emitting system log entries (`logger.error` and `logger.warning`) across `SyncMetadata.record_error`, `SyncMetadata.record_skipped`, `SyncWorker`, and all sync routines (`bus_timetables`, `bus_routes`, `stops`, `train_timetables`, `ha_locations`, `walking`), and configuring application-wide logging in `create_app` mapped from the `LOG_LEVEL` environment variable.
- Fixed Grid.js table data fetching failure across configuration pages (`locations`, `timetables`, `journeys`, `transfers`, `walking`) caused by an undefined `createChangesetTracker` reference in `transit-ui.js`, which threw a runtime `ReferenceError` during initialisation and prevented `window.TransitUI` and subsequent Grid.js data fetch requests from executing.
- Fixed obsolete dataset entries (e.g. legacy `bus_stops` and `stations`) persisting in `sync_metadata` and appearing on the Background Synchronisation page (`/config/sync`) by implementing automated startup cleanup in `run_migrations` and `SyncMetadata.cleanup_obsolete_entries`, restricting `get_sync_stats()` exclusively to registered datasets in `SYNC_REGISTRY`.
- Fixed Background Synchronisation page (`/config/sync`) and endpoint (`/config/sync/data`) querying physical SQLite tables from `get_db_stats()` by introducing `get_sync_stats()` to query `sync_metadata` directly, restoring independent rows and status telemetry for all 6 registered background synchronisation datasets (`bus_routes`, `stops`, `ha_locations`, `train_timetables`, `walking`, `bus_timetables`).
- Fixed Google Maps Directions API walking duration extraction to round durations in seconds up into whole minutes (`math.ceil`) rather than nearest-integer rounding, ensuring symmetrical forward and reverse walking durations produce a single bi-directional route entry.
- Fixed concurrent walking route synchronisations creating duplicate records by introducing thread synchronization (`_walking_sync_lock`) in `walking_sync.py`.
- Optimised transit candidate stop discovery in `find_candidate_stops_for_location` with bounding-box coordinate pre-filtering for large NaPTAN stop datasets.
- Fixed Darwin live departure board (`LDBWS`) credential validation failing with HTTP 403 on Rail Data Marketplace by setting custom `User-Agent` headers and formatting operational path URLs (`/api/20220120/...`).
- Fixed Timetable Grid Editor stop search autocomplete popup being overlapped by sticky table headers and displaying scrollbars by adjusting z-index stacking contexts, adding no-scrollbar utilities, and ensuring solid background opacities.
- Fixed unmocked transit synchronisation calls (`sync_stops` and `sync_bus_routes`) in `test_sync_table_and_sync_all_with_ha` and background worker daemon checks in `test_sync.py`, eliminating live external NaPTAN CSV downloads and thread timeout delays to reduce unit test suite execution time from ~2 minutes to ~12 seconds.
- Fixed Timetable Grid Editor stop search autocomplete popup being clipped and hidden inside the horizontally scrollable table container by positioning the stop search bar above the matrix table and resolving variable initialisation and Home Assistant Ingress path prefixing.

### Removed
- Removed unused `BusRoute.get_by_route_number()` and `BusRoute.get_all()` methods; neither is called from any production code path.
- Removed unused `NaptanClient.fetch_rail_stations()` method; rail stations have always been ingested via `fetch_stops()` (where `StopType` values `RLY`/`RPL`/`MET` are classified as `"rail"`), so the method was unreachable dead code.
- Removed obsolete inter-location transfers feature, `LocationTransfer` model, and `location_transfers` SQLite table in favour of the dedicated Walking feature (`/config/walking`).
- Removed legacy Darwin SOAP XML protocol fallback, XML envelope generation, and `.asmx` endpoints in favour of pure OpenAPI/Swagger client integration.
- Removed redundant hardcoded default base URL constants (`DEFAULT_DARWIN_OPENAPI_ENDPOINT`, `DEFAULT_LDBWS_BASE`), establishing the Swagger schema as the single source of truth for the default endpoint.

### Changed
- Replaced legacy `flake8` linter with `ruff` across development scripts, test requirements, CI workflows, and documentation.
- Consolidated backend datasource settings resolution with `BaseDataSource.get_setting_getter(settings)` across all provider clients (`bods`, `google_maps`, `train_s3`, `openai`, `train_live`, `homeassistant`, `naptan`), unifying dictionary and `Setting` model lookups.
- Standardised dataset synchronisation orchestration with shared `run_sync_task` and `ensure_db_initialised` in `app/sync/common.py`, eliminating duplicate telemetry tracking (`start`, `success`, `error`, `skipped`), connection contexts, elapsed duration calculations, and exception formatting across HA, Transit (BODS, NaPTAN, Train S3), and Walking sync modules.
- Refactored form and grid item sanitisation across configuration views (`journeys`, `timetables`, `walking`, `transfers`) with `parse_optional_id` and `sanitise_choice` helpers in `app/views/config/common.py`.
- Consolidated frontend UI formatting and components, adding `PlaceAutocomplete.bindSelection` for place search and preview chip binding, and standardising transport mode badges, icons, day matrices, and timestamp formatters across `journeys.js`, `transfers.js`, `walking.js`, `sync.js`, `locations.js`, and `db.js` using `TransitUI`.
- Reordered `SYNC_REGISTRY` in `SyncWorker` so that `walking` route discovery executes prior to `bus_timetables` synchronisation, ensuring newly discovered walking connections immediately feed bus timetable downloads in the same sync pass.

- Updated `post_save_hook` signature in `PageConfig` and `register_config_page` to pass both persistence statistics and the deserialised changeset dictionary (`stats, changeset`), enabling content-aware background sync dispatching without redundant execution.
- Migrated configuration pages (`journeys`, `locations`, `timetables`, `transfers`, `walking`) from full-page HTML form POST submissions to asynchronous AJAX JSON POST persistence (`POST /config/xxx/data`), with inline toast notifications, button loading spinners, shared `ConfigSave` module, and automatic Grid.js table data reloading.
- Refactored background synchronisation worker (`TransitBackgroundWorker` → `SyncWorker`) into a continuously running, flag-driven loop that serialises all sync operations, deduplicates concurrent requests via a `sync_requested` boolean flag persisted in `sync_metadata`, and idles with an interruptible 60-second sleep (`threading.Event`) when no work is pending.
- Replaced fixed single-interval polling with a per-entry `SYNC_REGISTRY` defining ordered sync operations and individual age thresholds: `ha_locations` (1 hour), `bus_routes` / `train_timetables` / `walking` / `bus_timetables` (24 hours), `stops` (7 days).
- Replaced `trigger_journey_walking_sync_async` (ad-hoc daemon thread) and `check_and_run_background_sync` / `sync_all` with a single `request_sync(table_name)` function that sets the DB flag and wakes the background loop immediately.
- Updated `POST /config/db/sync/<table>` and `POST /api/sync/<table>` endpoints to fire-and-forget: they now set the sync flag and return `{"status": "queued"}` immediately rather than blocking until the sync completes.
- Updated `_trigger_walking_sync_if_changed` in the journeys view to call `request_sync("walking")` instead of spawning a separate thread.
- Removed `SYNCABLE_TABLES` constant from `app.db`; valid table names are now derived from `SYNC_REGISTRY` in `app.sync.worker`.
- Refactored Transfers configuration page (`/config/transfers`) into a clean single-section layout focused exclusively on intra-station Platform & Stand Transfers with Grid.js and live autocomplete search.
- Componentised staged collection and changeset management across all configuration controllers (`locations`, `timetables`, `journeys`, `transfers`, `walking`) with `TransitUI.createChangesetTracker` in `transit-ui.js`, unifying modal adjustment detection, item staging, deletion tracking, and delta payload generation.

### Added
- Added `easting` and `northing` (British National Grid) fields to the `Stop` model and NaPTAN sync, extracting the corresponding `Easting`/`Northing` columns from the NaPTAN CSV feed alongside the existing `latitude`/`longitude` values. A schema migration adds both columns to existing `stops` tables without data loss.
- Added focused, entity-aware synchronisation triggers on configuration save: modifying journeys with Home Assistant or custom location endpoints queues `walking` discovery, modifying journeys with bus stop endpoints queues `bus_timetables` synchronisation, and saving walking routes involving bus stops queues `bus_timetables` synchronisation.
- Added automated chaining of `bus_timetables` synchronisation from `sync_walking_routes` whenever newly discovered walking routes connect to bus stops (`bus_stops_added > 0`), avoiding redundant sync requests when only rail or tram connections are discovered.
- Integrated Pydantic v2 schemas (`TimetableContent`, `TimetableStop`, `TimetableTrip`, `TripTiming`, and `JourneyTimeSetting`) and custom Peewee `PydanticField` for structured validation, serialisation, and deserialisation of embedded JSON fields (`Timetable.content` and `Journey.time_settings`).
- Architectural and technical design specification for the **Route Planning Engine** (`docs/architecture/01_route_planning_engine.md`) and companion **Phased Implementation Roadmap** (`docs/architecture/02_route_planning_implementation_plan.md`), defining two-tier route/trip separation, multi-modal graph search across up to 6 modal stages with up to 3 intra-modal transfers each, two-phase intermediate timetable ingestion (BODS / Darwin S3), last-possible interchange pruning, Pareto dominance filtering, and a 6-chunk progressive implementation schedule.
- Daily background synchronisation of bus timetables from the UK Bus Open Data Service (BODS) REST API and TransXChange timetable datasets (`sync_bus_timetables`).
- Automated TransXChange XML and zip archive timetable ingestion, parsing route services, lines, operating periods, operating profiles (days of week, bank holidays), and vehicle journey calling sequences into structured stop-to-stop trip matrices stored in the `timetables` database table with `transport_type='bus'` and `auto_added=True`.
- Automated discovery and extraction of target bus stops referenced in the `walking` and `journeys` tables, with geographic area and bounding box query scoping against BODS datasets.
- Non-interfering timetable reconciliation ensuring train timetable synchronisation and bus timetable synchronisation preserve each other's auto-added entries and custom user timetables.
- `bus_timetables` dataset entry in the Background Synchronisation dashboard (`/config/sync`) and daily 24-hour periodic freshness updates via `TransitBackgroundWorker`.
- Client-side delta changeset calculation and submission across all configuration managers (`locations`, `timetables`, `journeys`, `transfers`, `walking`, `credentials`), computing `{ "added": [...], "updated": [...], "deleted": [...] }` payloads so only modified or newly created entries are sent over the network when clicking **Save Changes**.
- Common differential model persistence architecture (`parse_json_form_changeset`, `apply_model_changeset`, and `save_changeset_config` in `common.py`) applying atomic insertions, updates, and scoped deletions without modifying or touching unchanged database rows.
- Field-level change detection in `Setting.set_val` and API credentials form submissions to selectively update only altered setting keys.
- On-demand SQLite database download option on the Database configuration page (`/config/db`) via dedicated **Download Database** action button and endpoint (`GET /config/db/download`) with WAL checkpointing and attachment streaming.
- Integrated Swagger 2.0 OpenAPI client (`bravado`) into `TrainLiveClient` for National Rail Darwin Live Departure Boards (`LDBWS`), using schema defaults with optional custom base URL overrides.
- Added automated startup schema download and local caching for the live LDBWS Swagger specification.
- Added typed OpenAPI client methods on `TrainLiveClient` (`get_departure_board`, `get_dep_board_with_details`, `get_arrival_board`, `get_service_details`, `get_fastest_departures`) and structured JSON departure fetching.
- Added optional Live Train Base URL override field in the Train Live Credentials web UI (`/config/credentials`).
- Automated walking route discovery and background synchronisation (`walking_sync.py`), identifying public transit stops (NaPTAN stops and custom timetable stops) within 500 metres of custom and Home Assistant journey endpoints using the Haversine formula.
- Google Maps Directions Walking API integration calculating forward and reverse walking durations in minutes, inserting a single `bidirectional=True` record when walking times match or two distinct directional records when they differ.
- `auto_generated` boolean indicator on `Walking` model (`walking` table) and automatic SQLite schema migration, distinguishing auto-discovered walking connections from manual configurations.
- Idempotent route creation preserving existing manual and auto-generated walking routes without overwriting.
- Visual `Auto` badge and edit restrictions for auto-generated walking routes in the Walking configuration table (`/config/walking`), allowing deletion while preventing accidental manual alteration.
- Asynchronous walking route synchronisation triggered automatically upon creating or modifying journeys on `/config/journeys`.
- `walking` dataset entry in Background Synchronisation dashboard (`/config/sync`) and daily 24-hour periodic freshness checks in `TransitBackgroundWorker`.
- Darwin AWS S3 train timetable background synchronisation ingesting National Rail Darwin XML timetable snapshots (`PPTimetable` v8), extracting passenger journey services, and grouping them by route corridor into timetable matrices with calling points and scheduled arrival/departure timings.
- Train Operating Company (`toc`) code and operator name extraction on each timetable journey trip object in the content schema (e.g. `{"toc": "TL", "operator": "Thameslink"}`).
- Auto-added indicator (`auto_added = BooleanField(default=False)`) on `Timetable` model and database schema migration, distinguishing Darwin-synced timetables from custom user timetables.
- Protection and preservation of auto-added train timetables during manual timetable saves in the web configuration interface (`save_timetables_with_auto_preservation`).
- Visual `Auto` badge with cloud sync icon, read-only view mode, and deletion protection for Darwin-synced timetables in the Timetables configuration table and Grid Editor.
- `train_timetables` dataset entry in Background Synchronisation dashboard (`/config/sync`) and automated 24-hour periodic freshness checks in `TransitBackgroundWorker`.
- Polymorphic timetable schema supporting dual arrival and departure timings per stop (`{"arr": "HH:MM", "dep": "HH:MM"}`) alongside standard single times (`"HH:MM"`).
- Interactive stacked dual-input visual design in the Timetable Grid Editor with compact uppercase `ARR` and `DEP` labels and dedicated `<input type="time">` elements.
- Seamless double-click cell interaction allowing users to double-click a single time box to split into Arrival & Departure, and double-click to collapse back to a single box.
- Chronological sequence and dwell time validation checking both intra-stop dwell duration (`Arrival ≤ Departure`) and inter-stop progression (`Departure[i] ≤ Arrival[i+1]`).
- Dwell time preservation during single and batch trip duplication and retiming across intervals.
- Reusable `PlaceAutocomplete` JavaScript component (`place-autocomplete.js`) encapsulating place search querying, debounce management, filter chip bar interaction, and suggestions rendering across Journeys, Transfers, and Timetable views.
- Interactive **Place Type Filter Chips** (`[All] [Train] [Bus] [Metro] [Tram] [Ferry] [Air] [HA] [Custom]`) pinned to the top of all place search autocomplete dropdowns across Journeys (`/config/journeys`), Transfers (`/config/transfers`), and the Timetable Grid Editor (`/config/timetables`).
- Instant re-filtering on chip click with focus retention, active filter styling, and context-aware default transport modes.
- Strict transport mode filtering in `GET /config/search/places`.
- Dedicated **Walking Configuration** page (`/config/walking`) and `Walking` database model (`walking` table) for managing custom walking connections, durations in minutes, and bidirectionality between rail stations, bus stops, Home Assistant zones, and custom locations.
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
- Redesigned Timetables configuration page (`/config/timetables`) and modal dialogue with day selection toggles, quick-select helper buttons (*All*, *Weekdays*, *Weekends*, *Clear*), date range pickers with validation, and support for adding and editing timetable entries.
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
