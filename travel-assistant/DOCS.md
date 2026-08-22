# Home Assistant Add-on: Travel Assistant

The **Travel Assistant** add-on provides travel and transport intelligence inside Home Assistant.

## Features

- **Ingress Dashboard**: Directly accessible from the Home Assistant sidebar.
- **SQLite Storage**: Persistent database storage for application settings, credentials, timetable entries, and cache.
- **Settings Management & Changeset Persistence**: Multi-page configuration (`/config/xxx`) using asynchronous AJAX JSON changeset persistence (`POST /config/xxx/data`) with a unified left navigation bar, mobile drawer, unsaved changes protection, anti-caching HTTP response headers, inline toast notifications, and client-side differential persistence. When saving table changes, browser scripts compute and submit only delta changesets (`{ "added": [...], "updated": [...], "deleted": [...] }`), ensuring only added, modified, or deleted rows are processed atomically on the server while preserving timestamps and state of unchanged rows, followed by automatic Grid.js table reloading without full-page reloads.
- **API Credentials Configuration**: Centralised storage for Bus API keys, Train S3 bucket details, live train departure tokens, Open API credentials, and Google Maps API credentials with automated validation probes and selective field delta submissions.
- **Timetables Configuration & Grid Editor**: CDN-hosted Grid.js table at `/config/timetables` for managing timetable schedules, validity date ranges, and operating days (Monday–Sunday + Bank Holiday) with client-side staging, date validation, and differential changeset persistence. Features a dedicated full-width interactive **Timetable Grid Editor** for constructing stop sequence matrices, multi-modal autocomplete stop search, dual arrival & departure timing support with double-click cell splitting/collapsing, chronological dwell sequence validation, and multi-column trip duplication and retiming across intervals.

- **Transfers Configuration**: Dedicated configuration page at `/config/transfers` with an interactive Grid.js table for managing intra-station platform-to-platform and stand interchange times with search autocomplete and step-free accessibility support. (Inter-location walking connections are handled by the Walking feature).
- **Walking Configuration & Automated Discovery**: Dedicated configuration page at `/config/walking` with an interactive Grid.js table and modal dialogue for configuring walking connections, durations in minutes, and route directionality between locations and transit stops. Features automated 500m radius stop discovery and Google Directions walking calculations for journey endpoints with `auto_generated` indicators, automatically queuing bus timetable synchronisation whenever bus stop connections are modified or discovered.
- **Journeys Configuration**: Dedicated configuration page at `/config/journeys` with an interactive Grid.js table and 2-tab modal dialogue (**Journey Details** and **Calculated Routes**) for configuring travel journeys between rail stations, bus stops, Home Assistant locations, and custom locations with multi-time-window scheduling. Features a dedicated `calculated_routes` JSON column displaying discovered multi-modal corridors, automatically clearing stale routes when journey parameters are modified, and automatically queuing targeted walking discovery when location endpoints change and bus timetable downloads when bus stop endpoints change.
- **Locations Configuration & Home Assistant Synchronisation**: Dedicated configuration page at `/config/locations` with an interactive Grid.js table and Leaflet JS map dialogue for managing custom and Home Assistant synchronised geographic locations (`locations` table). Features unique text identifiers (`ha:<object_id>` for Home Assistant zones and `custom:<hex>` for manual entries), a boolean `ha` indicator, read-only viewing modal, deletion protections for synced zones, and automated hourly background synchronisation.
- **Database Statistics & Backup**: SQLite storage usage and schema table metrics view at `/config/db` displaying database disk size, record counts per table, and on-demand SQLite database file download (`GET /config/db/download`).
- **Background Synchronisation**: Dedicated dashboard at `/config/sync` with interactive Grid.js table displaying cached transit datasets (Bus Routes, NaPTAN Transit Stops, Stop Interchanges, Home Assistant Locations, National Rail Darwin Train Timetables, Walking Connections, BODS Bus Timetables), last updated timestamps, status badges, and on-demand refresh triggers.
- **Automated Background Updates**: Background daemon worker (`SyncWorker`) that automatically evaluates and synchronises transit datasets, Home Assistant zones, National Rail Darwin train timetables, walking connections, and BODS bus timetables in dependency order whenever data is overdue or requested on demand.
- **Train Timetable Darwin S3 Synchronisation**: Automated ingestion and extraction of National Rail Darwin XML timetable snapshots from AWS S3, grouping passenger services into route corridors, recording Train Operating Companies (TOCs) per journey, and persisting entries into the `timetables` database with `auto_added=True` flags and UI modification protections.
- **Bus Timetable BODS Synchronisation**: Automated ingestion of UK Bus Open Data Service (BODS) TransXChange XML timetable datasets for routes serving bus stops referenced in configured walking and journey tables, converting calling sequences and scheduled departure times into structured timetable matrices stored in the `timetables` database with `auto_added=True` and `transport_type='bus'`.
- **Multi-Modal Journey Planner Library**: Standalone journey planning and route discovery service (`app/services/planner/`) computing topological route corridor templates (Mode 1) using NetworkX multi-directed graph traversal and 4-rule pruning (Last Possible Interchange, Subsumed Detours, Pareto Dominance, Senseless Detours), and scheduled travel itineraries (Mode 2) using an in-memory RAPTOR solver supporting `depart`, `arrive`, and `window` timing constraints, transfer slack scoring, and 3-tier transfer hierarchy resolution.
- **RESTful API**: Endpoints for service status, ping checks, timetable search lookup, and on-demand transit dataset synchronisation (`POST /api/sync/<table_name>` and `/config/db/sync/<table_name>`).
- **Lightweight Execution**: Powered by Python, Flask, and Gunicorn on Debian Bookworm.

## Timetable Architecture & Next Stages

The timetable configuration subsystem operates across incremental stages:
1. **Stage 1 (Complete)**: Web UI configuration page (`/config/timetables`) featuring a CDN-hosted Grid.js table, an accessible **Add Timetable** modal, client-side staging, and atomic persistence to SQLite on **Save Changes**.
2. **Stage 2 (Complete)**: Cached transit dataset integration and background synchronisation:
   - **Unified Stops Database**: Consolidated all UK bus stops, rail stations, metro, tram, and ferry access nodes into a unified `stops` table populated directly from the national NaPTAN dataset with `stop_type` classification (`bus`, `rail`, `metro`, `tram`, `ferry`, `air`).
   - **Automated Schedule**: Periodic daemon thread running hourly freshness checks to trigger updates when records are older than 24 hours.
   - **Cached Transit Timetable Configuration**:
     - **Train Journeys**: Bi-directional rail journey selection between two stations via asynchronous search autocompletion against cached rail stations (`stops` with `stop_type="rail"`), automatically formatting timetable names (`Station 1 ↔ Station 2`) and identifiers (`CRS1 ↔ CRS2`).
     - **Bus Routes**: Two-step bus configuration workflow allowing users to choose a bus stop (`stops` with `stop_type="bus"`), followed by an associated bus route (`bus_routes`), automatically formatting timetable names (`Route [Route] at [Stop Name]`) and identifiers (`[Route]@[Stop ATCO Code]`).
     - **Caching Prerequisites & Guidance**: Contextual guidance alerting users when transit datasets require synchronisation before adding timetables.
3. **Stage 3 (In Progress)**: Route planning engine and real-time transit intelligence:
   - **Route Planning Engine & Journey Planner (Tier 1)**: Two-phase topological route template discovery and multi-modal graph search connecting journey endpoints, with automated intermediate timetable retrieval (BODS / Darwin S3), last-possible interchange pruning, Pareto dominance filtering, and pure SQLite RAPTOR trip scheduling. See the [Architecture Specification](../docs/architecture/01_route_planning_engine.md), [Phased Implementation Roadmap](../docs/architecture/02_route_planning_implementation_plan.md), and [Journey Routing & Planning Process](../docs/architecture/03_journey_routing_and_planning_process.md) for full technical designs.
   - **Real-Time Journey Dispatcher (Tier 2)**: Dynamic trip calculation matching live departure feeds against active route templates, multi-modal interchange guidance, disruption alerts, and Home Assistant sensor entity publishing.


## Configuration

Add-on configuration is managed via the **Configuration** tab in Home Assistant or directly through the web UI settings.

### Option: `log_level`

The `log_level` option controls the verbosity of log output.

- `trace`
- `debug`
- `info` (default)
- `notice`
- `warning`
- `error`
- `fatal`

## Ingress

This add-on supports Home Assistant Ingress. When started, click **Open Web UI** or access it directly via the Home Assistant sidebar. Click the cog icon in the top right to access configuration and API credentials.

## Support

For issues, feature requests, or questions, please visit the [GitHub Repository](https://github.com/stuart-c/travel-assistant).

