# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Journey Departure Detection, Notification Dispatcher & Rollover** (`app/services/dispatcher/`, `DepartureMonitor`):
  - Automatically detects user (`person.stuart`) near journey origin within scheduled operating windows (`time_settings`) and calculates optimal departure leave-by time ($T_{\text{leave}} = T_{\text{transit\_dep}} - T_{\text{walk\_mins}}$) using the in-memory RAPTOR solver (`plan_journey`) and live departure probe adjustments (National Rail Darwin Live).
  - Dispatches rich departure notifications to mobile device (`notify.mobile_app_stuart_mobile` with no fallback) 15 minutes prior to leave time ($T_{\text{leave}} - 15\text{ mins}$), including leave-by time, walking duration, transit mode/line, origin boarding stop, scheduled vehicle departure time, estimated destination arrival, and dashboard tap action metadata.
  - Automatically detects when Stuart remains at origin past the leave-by time and rolls over the notification with the next viable departure candidate that arrives before the window cutoff (`find_next_departure_candidate`).
  - Automatically clears the mobile push notification via Home Assistant's `clear_notification` action (`HomeAssistantClient.clear_mobile_notification`) when all viable departure options have elapsed or cannot meet the arrival cutoff.
  - Appends connecting transit next-step instructions (mode, line, operator, origin, departure time, and platform) or final walk legs in British English for multi-leg journeys across departure notifications and candidate itinerary evaluations (`format_next_step_for_departure`).
- **Live Journey Tracking Screen, Abstract Vertical Route Diagram & Real-Time Telemetry API** (`/journey`, `/api/journey/live`, `static/js/journey_tracker.js`):
  - User-facing live tracking screen displaying real-time journey progression outside the configuration panel.
  - Abstract vertical route corridor diagram as the primary display, styled after British transport interfaces (TfL Go, Citymapper), featuring mode-coloured transit spines, TfL concentric double-ring interchange discs with platform badges (`Plat 4`), changeover callout cards (`Change here: Board [Line] from Platform [X]`), dynamic user position anchors ("Stuart is here"), and pulsing cyan telemetry beacons along the transit spine.
  - Segmented view toggle (`[ Route Diagram (Default) | Geographic Map ]`) enabling immediate switching between the schematic route corridor and an interactive Leaflet geographic GPS map.
  - Real-time telemetry cards detailing live rail platforms (Darwin LDBWS), service delay status, next-step instructions, and remaining distance/time in British English.
  - Client-side auto-polling (10-second interval) with seamless DOM reconciliation and dynamic Leaflet viewport resizing.
- **Journey Progress Tracking & En-Route Active Session Recovery** (`app/services/dispatcher/tracker.py`, `DepartureMonitor`):
  - Continuously monitors location during active journeys and updates existing mobile notifications in-place using persistent tags (`tag: journey_{id}`) across granular step transitions (`PRE_DEPARTURE`, `EN_ROUTE_TO_STOP`, `AT_DEPARTURE_STOP`, `ON_TRANSIT`, `AT_INTERCHANGE`, `EN_ROUTE_TO_DESTINATION`, `ARRIVED`).
  - Active session recovery (`detect_en_route_journey`) identifying when Stuart has departed origin without an initial alert or departed early, correlating GPS position against route corridors, registering active journey sessions dynamically, and resuming live tracking.
  - Real-time railway platform detection via National Rail Darwin Live (`TrainLiveClient`), probing departures to announce platform numbers and live delay statuses as soon as published.
- **Model Context Protocol (MCP) Server & Configuration UI** (`app/mcp/`, `app/views/config/mcp.py`, `/config/mcp`):
  - Asynchronous Model Context Protocol (MCP) server running on port `8098` supporting Streamable HTTP POST and GET SSE transports (`/mcp`, `/sse`, `/`) with local area network host support and pre-shared Bearer token authentication (`mcp_api_token`).
  - Granular binary opt-in security architecture (`enabled = BooleanField(default=False)`) for tools across journeys (`journey_*`), timetables (`timetable_*`), walking (`walking_*`), transfers (`transfer_*`), transit stop searches and departures (`stops_*`), dispatcher controls (`dispatcher_*`), and background synchronisation (`sync_*`).
  - Dedicated single-purpose database tools: `db_query` (strictly read-only `SELECT`) and `db_execute` (atomic mutating operations).
  - Dedicated `/config/mcp` configuration page with accessible toggle switches and differential changeset persistence (`ConfigSave`).
- **Multi-Modal Journey Planner & Route Engine** (`app/services/planner/`):
  - Mode 1 topological route corridor discovery with NetworkX multi-directed graph traversal, access stop preservation, pure per-change cost model ($w = 0.01$, transfer penalty $w = \text{duration} + 12.0$), and 4-rule pruning (Last Possible Interchange, Subsumed Detours, Pareto Dominance, Senseless Detours).
  - Modal sequence validation rules: no consecutive walking legs, maximum of 2 consecutive legs for direct transit of the same mode, and up to 4 consecutive legs of the same mode for intra-modal transfers.
  - Mode 2 scheduled itinerary planning with an in-memory RAPTOR solver supporting `depart`, `arrive`, and `window` timing constraints, transfer slack scoring, and 3-tier transfer hierarchy resolution.
  - Interactive Directed Acyclic Graph (DAG) viewer (`vis-network`) in the Journey modal dialogue rendering calculated route corridors with intermediate calling points, mode-coloured edges, hover tooltips, and fit-to-view controls.
  - Hourly background synchronisation job (`journey_routes`) and automatic re-calculation triggers on journey/timetable modification.
  - Technical architecture specifications: Route Planning Engine (`01_route_planning_engine.md`), Phased Implementation Roadmap (`02_route_planning_implementation_plan.md`), and Multi-Modal Journey Routing and Planning Process (`03_journey_routing_and_planning_process.md`).
- **Timetable Data Synchronisation (BODS & Darwin S3)**:
  - Daily background synchronisation of bus timetables from the UK Bus Open Data Service (BODS) REST API and TransXChange timetable datasets (`sync_bus_timetables`).
  - Daily background synchronisation of rail timetables from National Rail Darwin AWS S3 XML snapshots (`PPTimetable` v8), classifying services by Scheduled Start Date (`ssd`) into Weekday (`Mon-Fri`), Saturday (`Sat`), and Sunday (`Sun`) trip matrices.
  - Auto-added protection (`auto_added = BooleanField(default=False)`) distinguishing synced timetables from custom user timetables with visual UI badges and deletion protection.
- **Geospatial Walking Discovery & Stop Interchanges**:
  - Automated walking route discovery (`walking_sync.py`) identifying transit stops within 500m of Home Assistant zones and custom locations using Google Maps Directions API, generating bi-directional or directional walking links.
  - Weekly background synchronisation of transit stop interchanges (`stop_interchanges`) within 250m using SQLite R*Tree geospatial indexing on British National Grid `easting` and `northing` coordinates.
  - Added `easting` and `northing` fields to `Stop` model and NaPTAN sync feed.
- **Configuration Suite, Grid Editor & Changeset Architecture**:
  - Full-width interactive Timetable Grid Editor on `/config/timetables` with stop-by-trip matrix, split Arrival/Departure cells, duplicate & retime interval tools, and dwell/progression sequence validation.
  - Universal client-side differential changeset management (`TransitUI.createChangesetTracker`, `ConfigSave`) and atomic backend persistence (`apply_model_changeset`) submitting only modified, added, or deleted entities.
  - Consolidated location search endpoint (`GET /config/search/places`) with interactive Place Type Filter Chips (`[All] [Train] [Bus] [Metro] [Tram] [Ferry] [Air] [HA] [Custom]`) and namespaced identifiers (`naptan:`, `atco:`, `ha:`, `custom:`).
  - Dedicated configuration management views: Journeys (`/config/journeys`), Locations (`/config/locations` with Leaflet map modal), Timetables (`/config/timetables`), Transfers (`/config/transfers`), Walking (`/config/walking`), Credentials (`/config/credentials`), Background Sync (`/config/sync`), and Database (`/config/db` with on-demand SQLite file download).
  - Home Assistant location synchronisation (`ha_locations`) importing all Home Assistant zones daily.
  - Darwin Live OpenAPI client (`bravado`) with Swagger 2.0 schema caching and custom base URL overrides.
- **Developer & Operational Tooling**:
  - Static asset access log filtering (`StaticAccessLogFilter`, `GunicornLogger`) suppressing high-frequency JS and CSS access logs from console output at `INFO` level.
  - Application-wide structured logging across data pipelines, background workers, and lifecycle operations.
  - Parallel test runner support (`pytest-xdist>=3.5.0`) and test argument forwarding in `scripts/run_tests.sh`.

### Changed
- **Location Privacy & London Public Data Standard**: Sanitised all documentation, test suites, architecture walkthroughs, datasource mock fixtures, and sample database seeds to use generic London public transport locations and landmarks (e.g. London King's Cross, London Euston, Old Street, TfL bus routes) per Rule 7.
- **Rail Station ATCO/TIPLOC to CRS Resolver & Darwin Live Activation**:
  - Standardised rail station CRS resolution via `station_resolver.py` and embedded `tiploc_crs_map.json`, resolving NaPTAN rail ATCO codes (`9100...`) and Darwin TIPLOC codes to canonical 3-letter CRS station codes across platform resolution and departure evaluations.
  - Initialised and enabled `train_live_client` in `DepartureMonitor` and `JourneyTracker` so live platform queries execute in background monitoring and live tracking.
- **Modal Sequence Validation for Intra-Modal Transfers**: Relaxed the Mode 1 corridor validation rule to allow up to 4 consecutive legs of the same transport mode for intra-modal transfers (connecting rail services or bus routes), whilst retaining the 2-leg limit for direct non-interchange journeys.
- **Model Context Protocol (MCP) Permissions & Database Tooling**:
  - Transitioned MCP tool permissions from a 3-state access level (`disabled`, `read`, `read_write`) to a clean binary `disabled` / `enabled` schema (`enabled = BooleanField(default=False)`), enforcing strict opt-in security with no backward-compatibility wrappers.
  - Split multi-purpose database tools into dedicated single-purpose tools: `db_query` (strictly read-only `SELECT`) and `db_execute` (mutating `INSERT`, `UPDATE`, `DELETE`).
  - Configured `dispatcher_evaluate` as non-mutating (`is_mutating=False`).
  - Replaced the access level dropdown in `/config/mcp` with an accessible toggle switch control with differential changeset tracking.
- **Background Sync Worker Architecture**:
  - Refactored `TransitBackgroundWorker` into `SyncWorker`, a continuously running flag-driven loop serialising sync operations, deduplicating requests via `sync_metadata` flags, and waking on `request_sync(table_name)` triggers.
  - Reordered `SYNC_REGISTRY` execution (`ha_locations` → `walking` → `bus_timetables`) so newly discovered walking routes immediately feed bus timetable downloads in the same pass.
  - Migrated `/config/db/sync/<table>` and `/api/sync/<table>` to asynchronous fire-and-forget endpoints.
- **Frontend & Styling Standardisation**:
  - Migrated frontend styling from custom vanilla CSS to Tailwind CSS v4 via CDN, standardising page containers (`max-w-5xl`), status badges, button sizing tiers, and dark-mode adaptation.
  - Extracted client-side JavaScript and CSS into modular static files (`dirty-manager.js`, `credentials.js`, `timetables.js`, `db.js`, `tables.css`, `transit-ui.js`, `config-save.js`).
  - Standardised table action buttons across Grid.js configuration tables into compact 28x28px icon-only buttons with tooltips.
- **Codebase Architecture & Testing**:
  - Replaced legacy `flake8` linter with `ruff` across development scripts, test requirements, CI workflows, and documentation.
  - Decomposed monolithic configuration views and validators into modular domain packages (`app/views/config/`, `app/validators/`).
  - Standardised datasource settings resolution with `BaseDataSource.get_setting_getter(settings)` and sync orchestration with `run_sync_task` in `app/sync/common.py`.
  - Optimised unit test database fixtures using fast shared in-memory SQLite URI databases (`file:mem_test_{uuid}?mode=memory&cache=shared`) and mocked external Darwin SOAP and sync routines, reducing test suite execution time from ~2 minutes to ~12 seconds.
  - Synchronised project documentation across README, `travel-assistant/DOCS.md`, architecture specifications, and browser testing runbooks to reflect current UI and British English standards.

### Removed
- **Obsolete Datasets & Models**:
  - Removed obsolete `rail_references` table, model (`RailReference`), client (`RailReferencesClient`), and background sync task (`sync_rail_references`).
  - Removed obsolete inter-location transfers feature, `LocationTransfer` model, and `location_transfers` table in favour of the dedicated Walking feature (`/config/walking`).
  - Removed separate `bus_stops` and `stations` synchronisation routines and database tables in favour of the consolidated `stops` pipeline.
  - Removed hardcoded sample timetable and location search datasets (`SAMPLE_TIMETABLE_DATA`, `SAMPLE_LOCATION_SEARCH_DATA`) and synthetic placeholder records (`S3-HUB`, `LDBWS-HUB`, `BODS-FEED-{id}`).
- **Dead Code & Legacy APIs**:
  - Removed unused `BusRoute.get_by_route_number()` and `BusRoute.get_all()` methods.
  - Removed unused `NaptanClient.fetch_rail_stations()` method.
  - Removed legacy Darwin SOAP XML protocol fallback, XML envelope generation, and `.asmx` endpoints in favour of pure OpenAPI/Swagger client integration.
  - Removed redundant hardcoded default base URL constants (`DEFAULT_DARWIN_OPENAPI_ENDPOINT`, `DEFAULT_LDBWS_BASE`).
  - Removed redundant search endpoints (`/api/timetables/search`, `/config/timetables/search`, `/config/transfers/search`, `/config/journeys/search`) in favour of `/config/search/places`.
- **Backwards-Compatibility Aliases & Fallbacks**:
  - Removed obsolete backwards-compatibility aliases in `DATASOURCE_REGISTRY` (`bods`, `s3`, `darwin`, `openai`, `ha`, `googlemaps`, `maps`).
  - Removed redundant service aliases from credential validation dispatcher (`validate_service_credentials`).
  - Removed obsolete constant re-exports in `app/validators/__init__.py` and view helpers in `app/views/config/__init__.py`.
  - Removed legacy stop type search aliases (`train`, `station`, `stations`, `bus_stop`, `bus_stops`) in `Stop.search` and legacy `crs_code` fallback in `Stop.bulk_upsert`.
  - Removed `SYNCABLE_TABLES` constant from `app.db`.

### Fixed
- **Notification Debouncing, Rate Limiting & Transient Error Backoff** (`app/services/dispatcher/tracker.py`, `app/services/dispatcher/monitor.py`):
  - Added debouncing and rate limiting to in-progress journey updates (`update_journey_progress`) with a 120-second (2-minute) cooldown for minor telemetry fluctuations (small ETA drift $\le 2$ minutes).
  - Reserved immediate notification dispatch for significant state changes (step progression e.g. `PRE_DEPARTURE` $\rightarrow$ `EN_ROUTE_TO_STOP` $\rightarrow$ `AT_DEPARTURE_STOP` $\rightarrow$ `ON_TRANSIT` $\rightarrow$ `AT_INTERCHANGE` $\rightarrow$ `EN_ROUTE_TO_DESTINATION` $\rightarrow$ `ARRIVED`, platform announcements or reassignments, and major delays $\ge 5$ minutes or cancellations).
  - Stabilised walking leg estimated arrival times in `EN_ROUTE_TO_DESTINATION` so that expected arrival is locked upon entering the leg rather than continually recomputed as `now + duration`, eliminating artificial minute-by-minute text churn and notification storms.
  - Added exponential backoff and transient error damping in `DepartureMonitor` daemon loop (`_calculate_backoff_delay`) to smoothly back off from 30s up to 300s during Home Assistant HTTP 502 Bad Gateway outages or network drops, resetting the backoff counter upon successful communication.
  - Persisted debouncing timestamps and state attributes (`last_notification_time`, `last_notified_status`, `last_notified_platform`, `last_notified_delay_minutes`) across `ActiveJourney` session storage in the database.
- **Darwin OpenAPI Platform Resolution, Rollover Future Timing & Commute Window Retention** (`app/datasources/train_live.py`, `app/services/dispatcher/tracker.py`, `app/services/dispatcher/evaluator.py`):
  - Normalised National Rail Darwin LDBWS OpenAPI dictionary responses (`DeparturesBoard` and `StationBoard`) via `extract_live_services`, unwrapping individual service objects to ensure real-time platforms and delay statuses are resolved instead of being dropped by list-type assertions.
  - Added departure board fallback (`get_departure_board`) in `resolve_live_rail_platform` and `apply_live_departure_adjustments` when fastest departures data omits platform assignments.
  - Sanitised `filter_list` inputs in `TrainLiveClient.get_fastest_departures` to join list parameters into valid comma-separated string parameters.
  - Enforced strictly future leave times in `find_next_departure_candidate` (`candidate.leave_minutes >= current_minutes + 1`) and re-validated achievable leave times following live delay adjustments, eliminating confusing past-leave push notifications.
  - Guarded pre-departure rollover expiry in `update_journey_progress` to ensure active journey tracking sessions do not prematurely transition to `JourneyStepStatus.EXPIRED` and clear mobile push notifications while the scheduled commute window remains active and viable options exist.
- **Dispatcher Tracking, Platform Precision & Dynamic Timing Realignment** (`app/services/dispatcher/`):
  - Fixed bus interchange notifications showing "Platform to be announced" by strictly checking for rail mode or explicit bus stand/stop indicators before formatting platform clauses.
  - Added step 3 fallback in `resolve_live_rail_platform` to match the earliest upcoming calling departure when the scheduled time has passed or was adjusted due to earlier leg delays.
  - Implemented dynamic active journey schedule realignment (`_realign_active_journey_timings`, `_find_next_timetable_trip`, `_propagate_leg_timings`) when late arrival at an interchange causes missed connections, propagating revised departure/arrival times downstream and updating the expected journey arrival time.
  - Fixed egress walk ETA calculation and arrival notifications (`format_progress_notification`) to compute remaining walk duration dynamically from current time, record actual arrival timestamps, and format context-aware arrival greetings ("Welcome home! Have a pleasant evening." for evening arrivals at home).
  - Prevented en-route active journey recovery (`detect_en_route_journey`) from selecting candidate itineraries whose connecting transit departure has already elapsed.
  - Added active journey session persistence across daemon or Gunicorn restarts using the `Setting` key-value model (`save_active_journey_session`, `load_active_journey_sessions`, `clear_active_journey_session`).
  - Broadened departure notification evaluation window in `evaluate_journey_notification` up to `leave_minutes + tolerance` to prevent dropped alerts if background ticks miss the initial trigger minute.
  - Corrected MCP tool `dispatcher_get_status` journey name resolution and added persistent session reset support in `dispatcher_reset_session`.
- **Departure Dispatcher & En-Route Recovery**:
  - Fixed en-route journey recovery selecting stale past itineraries by evaluating all candidate legs across the search window, filtering expired departures, and selecting the candidate closest to the current time (`detect_en_route_journey`).
  - Replaced legacy tuple return from `resolve_live_rail_platform` with structured `LiveRailStatus` (platform, expected departure time, delay minutes, disruption reason) to surface original scheduled times, delayed timings, and delay reasons in notifications in British English.
  - Added dynamic journey duration calculation and expanded advance evaluation window (`est_duration + 45` minutes before `start_time`) for `arrive` mode journeys, ensuring departure notifications evaluate and dispatch in ample time for early morning services.
  - Added forward leg scanning in `update_journey_progress` to advance legs automatically when boarding transit before intermediate GPS capture, unified foot and transfer modes under `FOOT_MODES` to prevent "On board Interchange" misclassifications, and stripped timetable title suffixes from notification messages.
  - Added walking leg corridor check returning `JourneyStepStatus.EN_ROUTE_TO_STOP` with live platform telemetry when a user has departed origin and is walking towards the initial transit stop.
  - Updated notification payloads (`url` and `clickAction`) to resolve the dynamic add-on Ingress panel path, preventing Home Assistant Companion App navigation failures.
- **RAPTOR Solver & Journey Route Discovery Performance**:
  - Resolved Out-Of-Memory (OOM) crash in background departure monitoring by replacing unbounded full-table scans on `stop_interchanges` (2.25 million NaPTAN records) in `_run_raptor_forward` and `_check_corridor_connectivity` with targeted indexed queries restricted to stops on active trips, yielding raw tuples (`StopInterchange.select().tuples()`) in 500-item chunks and precomputing `stop_to_trips` once across departure sweeps.
  - Resolved Out-Of-Memory (OOM) killer terminations and worker timeouts on `/journey` and live polling by extending RAPTOR's in-memory parsed trip cache (`_TRIPS_CACHE_TTL_SECONDS = 86400.0`), combining stop extraction and trip conversion into a single pass, caching upcoming itineraries for 300 seconds, and adding SQL-level date range and day-of-week pre-filtering via `get_active_timetables`.
  - Integrated automatic planner cache invalidation hooks (`_clear_planner_caches`) triggered on timetable or journey creation, modification, or removal.
  - Added seamless topological route corridor fallback in live tracking (`j_obj.get_calculated_routes()`) when viewing journeys outside scheduled operating hours.
  - Replaced expensive fallback `find_routes` in `plan_journey` with a fast BFS corridor connectivity check (`_check_corridor_connectivity`), eliminating 3-minute Gunicorn and dispatcher freezes.
  - Added monotonic midnight rollover detection (`rollover_offset += 1440`) in `_extract_parsed_trips` and slack calculations to prevent negative-duration infinite loops on cross-midnight trips.
  - Injected 0-minute direct access/egress edges in `plan_journey` when origin or destination endpoints are served directly by active timetable stops.
  - Enforced a pure per-change cost model ($w = 0.01$ transit edge weight, $w = \text{duration} + 12.0$ transfer penalty), preserved reachable origin access stops in corridor exploration, and compressed contiguous legs while preserving distinct timetables and intermediate transfer stations.
  - Resolved topological route graph connectivity failures by canonicalising namespaced identifiers (`naptan:`, `atco:`, `ha:`, `custom:`, `tiploc:`), eliminating double prefixes (`ha:ha:...`), and replacing unindexed full-table scans with filtered batch queries on `stop_interchanges`.
  - Fixed Calculated Routes DAG viewer layout by replacing heuristic progress averaging with longest-path relaxation on directed legs, preserving transit modes and directional colours, enforcing top-to-bottom hierarchy with level compaction, and canonicalising stop nodes to official NaPTAN/ATCO codes.
- **Data Synchronisation Pipelines**:
  - Fixed Darwin rail timetable single-day validity expiry by setting `end_date = None` so recurring rail services remain active indefinitely, added startup migration clearing legacy single-day `end_date` values, and implemented `ContinuationToken` pagination for S3 buckets with >1,000 keys.
  - Fixed BODS TransXChange bus timetable ingestion by preserving opposing directional corridors, consolidating journey pattern fragments into master route corridors with order-preserving topological insertion, correctly parsing vehicle journey `<OperatingProfile>` overrides for weekday/Saturday/Sunday day flags, resolving bus stops with prefix awareness to ATCO codes, adding multi-page offset pagination, and removing unsupported query parameters (`boundingBox`).
  - Fixed synchronisation errors and skipped diagnostics only appearing on the Web UI by emitting structured system log entries (`logger.error`, `logger.warning`) across all sync routines, and elevated `JourneyPlanningError` to `WARNING`.
  - Rounded Google Maps walking durations in seconds up into whole minutes (`math.ceil`) to produce symmetrical bi-directional records, and introduced `_walking_sync_lock` thread synchronisation.
  - Resolved Darwin LDBWS credential validation HTTP 403 on Rail Data Marketplace by configuring custom `User-Agent` headers and operational path URLs.
- **Model Context Protocol (MCP) Server**:
  - Migrated `create_mcp_app` to `MCPServer.streamable_http_app` supporting HTTP POST initialisation, JSON-RPC execution, GET SSE streams, and route aliases (`/sse`, `/mcp`, `/`).
  - Disabled strict DNS rebinding protection by default in `MCPServer.sse_app` to accept local network clients and Home Assistant reverse proxy requests with LAN Host headers without `HTTP 421 Misdirected Request`.
  - Fixed Grid.js runtime exception on `StagedChangesetManager.getUpdated()` in MCP config UI, synchronised dirty state with `ConfigDirtyManager`, and resolved module namespace collision with the external `mcp` library.
- **Configuration Web UI & Table Management**:
  - Restored original Save button inner HTML and state in `ConfigSave.save` on completion, ensuring `ConfigDirtyManager.updateUI` resets button markup reliably without sticking on `Saving...`.
  - Fixed timetable action button click delegation on `/config/timetables` to reliably open the Timetable Grid Editor and edit dialogues.
  - Fixed Timetable Grid Editor stop search autocomplete popup layering (z-index stacking, positioning above table, no-scrollbar styling) and container clipping.
  - Resolved undefined `createChangesetTracker` reference in `transit-ui.js` that caused runtime exceptions during Grid.js data fetch.
  - Disabled browser caching across configuration pages and endpoints by serving explicit `Cache-Control: no-cache, no-store, must-revalidate` headers.
  - Fixed Google Maps credential validation HTTP 400 error by executing an active geocoding probe query instead of an empty parameter.
  - Added automatic SQLite schema migration in `run_migrations` for legacy `timetables` tables (`start_date`, `transport_type`, `content`).
  - Mocked unmocked transit synchronisation calls and worker daemon checks in unit test fixtures, eliminating external network requests.

## [0.1.0] - 2026-08-15

### Added
- Initial scaffolding for Travel Assistant Home Assistant Add-on.
- Flask-based backend service with "Hello World" single page dashboard.
- Home Assistant Ingress dynamic routing support (`X-Ingress-Path`).
- Multi-stage Debian Bookworm Dockerfile.
- Unit testing suite with pytest and code coverage reporting.
- Development automation scripts (`make_venv.sh`, `run_tests.sh`, `run_dev.sh`, `verify_all.sh`).
- GitHub Actions CI/CD workflows for PR testing, multi-arch builds (`amd64`, `aarch64`), automated changelog drafting, and release publishing.
