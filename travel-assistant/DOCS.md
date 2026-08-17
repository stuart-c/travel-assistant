# Home Assistant Add-on: Travel Assistant

The **Travel Assistant** add-on provides travel and transport intelligence inside Home Assistant.

## Features

- **Ingress Dashboard**: Directly accessible from the Home Assistant sidebar.
- **SQLite Storage**: Persistent database storage for application settings, credentials, timetable entries, and cache.
- **Settings Management**: Multi-page configuration (`/config/xxx`) using the Post/Redirect/Get pattern with a unified left navigation bar, mobile drawer, unsaved changes protection, and anti-caching HTTP response headers.
- **API Credentials Configuration**: Centralised storage for Bus API keys, Train S3 bucket details, live train departure tokens, Open API credentials, and Google Maps API credentials with automated validation probes.
- **Timetables Configuration & Grid Editor**: CDN-hosted Grid.js table at `/config/timetables` for managing timetable schedules, validity date ranges, and operating days (Monday–Sunday + Bank Holiday) with client-side staging, date validation, and atomic persistence. Features a dedicated full-width interactive **Timetable Grid Editor** for constructing stop sequence matrices, multi-modal autocomplete stop search, dual arrival & departure timing support with double-click cell splitting/collapsing, chronological dwell sequence validation, and multi-column trip duplication and retiming across intervals.

- **Transfers Configuration**: Dedicated configuration page at `/config/transfers` with stacked Grid.js tables for managing inter-location walking links (e.g. station-to-bus stop) and intra-station platform-to-platform interchange times with search autocomplete and step-free accessibility support.
- **Walking Configuration**: Dedicated configuration page at `/config/walking` with an interactive Grid.js table and modal dialogue for configuring custom walking connections, durations in minutes, and route directionality between any locations or transit stops.
- **Journeys Configuration**: Dedicated configuration page at `/config/journeys` with an interactive Grid.js table and modal dialogue for configuring travel journeys between rail stations, bus stops, Home Assistant locations, and custom locations with multi-time-window scheduling.
- **Locations Configuration & Home Assistant Synchronisation**: Dedicated configuration page at `/config/locations` with an interactive Grid.js table and Leaflet JS map dialogue for managing custom and Home Assistant synchronised geographic locations (`locations` table). Features unique text identifiers (`ha:<object_id>` for Home Assistant zones and `custom:<hex>` for manual entries), a boolean `ha` indicator, read-only viewing modal, deletion protections for synced zones, and automated daily background synchronisation.
- **Database Statistics**: SQLite storage usage and schema table metrics view at `/config/db` displaying database disk size and record counts per table.
- **Background Synchronisation**: Dedicated dashboard at `/config/sync` with interactive Grid.js table displaying cached transit datasets (Bus Routes, NaPTAN Transit Stops, Home Assistant Locations, National Rail Darwin Train Timetables), last updated timestamps, status badges, and on-demand refresh triggers.
- **Automated Background Updates**: Background daemon worker (`TransitBackgroundWorker`) that automatically synchronises transit datasets, Home Assistant zones, and National Rail Darwin train timetables whenever data is older than 24 hours (1 day).
- **Train Timetable Darwin S3 Synchronisation**: Automated ingestion and extraction of National Rail Darwin XML timetable snapshots from AWS S3, grouping passenger services into route corridors, recording Train Operating Companies (TOCs) per journey, and persisting entries into the `timetables` database with `auto_added=True` flags and UI modification protections.
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
3. **Stage 3 (Future)**: Real-time route planning, multi-modal interchange guidance, disruption alerts, and Home Assistant sensor entity publishing.


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

