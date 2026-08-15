# Home Assistant Add-on: Travel Assistant

The **Travel Assistant** add-on provides travel and transport intelligence inside Home Assistant.

## Features

- **Ingress Dashboard**: Directly accessible from the Home Assistant sidebar.
- **SQLite Storage**: Persistent database storage for application settings, credentials, and cache.
- **Settings Management**: Multi-page configuration (`/config/xxx`) using the Post/Redirect/Get pattern.
- **API Credentials Configuration**: Centralised storage for Bus API keys, Train S3 bucket details, live train departure tokens, and Open API credentials.
- **RESTful API**: Endpoints for service status, ping checks, and transport insights.
- **Lightweight Execution**: Powered by Python, Flask, and Gunicorn on Debian Bookworm.

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
