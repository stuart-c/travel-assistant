# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Persistent SQLite database backend and `SettingsRepository` for application configuration and credentials.
- Settings navigation cog button in the web UI header.
- Settings page router (`/config/xxx`) using Jinja2 templates and the Post/Redirect/Get pattern.
- API credentials management page (`/config/credentials`) supporting Bus API keys, Train S3 bucket details, Train live credentials, and Open API credentials.
- Comprehensive unit tests covering database lifecycle, repository operations, and configuration views with 100% code coverage.

## [0.1.0] - 2026-08-15

### Added
- Initial scaffolding for Travel Assistant Home Assistant Add-on.
- Flask-based backend service with "Hello World" single page dashboard.
- Home Assistant Ingress dynamic routing support (`X-Ingress-Path`).
- Multi-stage Debian Bookworm Dockerfile.
- Unit testing suite with pytest and code coverage reporting.
- Development automation scripts (`make_venv.sh`, `run_tests.sh`, `run_dev.sh`, `verify_all.sh`).
- GitHub Actions CI/CD workflows for PR testing, multi-arch builds (`amd64`, `aarch64`), automated changelog drafting, and release publishing.
