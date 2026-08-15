# Home Assistant Add-on: Travel Assistant

The **Travel Assistant** add-on provides travel and transport intelligence inside Home Assistant.

## Features

- **Ingress Dashboard**: Directly accessible from the Home Assistant sidebar.
- **SQLite Storage**: Persistent database storage for application settings, credentials, timetable entries, and cache.
- **Settings Management**: Multi-page configuration (`/config/xxx`) using the Post/Redirect/Get pattern with a unified left navigation bar, mobile drawer, and unsaved changes protection.
- **API Credentials Configuration**: Centralised storage for Bus API keys, Train S3 bucket details, live train departure tokens, and Open API credentials.
- **Timetables Configuration**: CDN-hosted Grid.js table at `/config/timetables` for managing bus routes and rail station departure feeds with client-side staging, search autocomplete, and atomic persistence.
- **RESTful API**: Endpoints for service status, ping checks, timetable search lookup, and transport insights.
- **Lightweight Execution**: Powered by Python, Flask, and Gunicorn on Debian Bookworm.

## Timetable Architecture & Next Stages

The timetable configuration subsystem operates across incremental stages:
1. **Stage 1 (Current)**: Web UI configuration page (`/config/timetables`) featuring a CDN-hosted Grid.js table, an accessible **Add Timetable** modal with asynchronous search autocomplete (`/api/timetables/search`), client-side staging, and atomic persistence to SQLite on **Save Changes**.
2. **Stage 2 (Upcoming)**: Automated background synchronization workers connecting configured timetable entries to live datasets:
   - **Bus feeds**: Integration with Bus Open Data Service (BODS) for TransXChange / GTFS-RT timetable downloads and SIRI-VM vehicle location streaming.
   - **Rail feeds**: Ingestion of Darwin CIF / Timetable Archives from configured S3 storage and live Darwin Web Services (LDBWS) departures.
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

