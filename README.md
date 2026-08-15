# Travel Assistant

Home Assistant Add-on providing travel and transport intelligence powered by Python and Flask.

## Features

- **Home Assistant Ingress Support**: Integrated dashboard embedded into Home Assistant.
- **Python & Flask Core**: Lightweight, extensible backend architecture.
- **Multi-Architecture Support**: Built for both `amd64` and `aarch64` architectures.
- **Automated CI/CD & Releases**: Automated linting, testing, multi-arch container image publishing on GitHub Container Registry, and changelog drafting.

## Development

### Prerequisites

- Python 3.11+
- Git

### Setup & Local Testing

1. **Initialise Virtual Environment**:
   ```bash
   bash scripts/make_venv.sh
   ```

2. **Run Linting and Unit Tests**:
   ```bash
   bash scripts/run_tests.sh
   ```

3. **Start Development Server**:
   ```bash
   bash scripts/run_dev.sh
   ```
   Access the web interface at `http://localhost:8099`.

4. **Verify Everything Pre-Push**:
   ```bash
   bash scripts/verify_all.sh
   ```

## Agent and Contribution Guidelines

Please read [AGENTS.md](AGENTS.md) before making contributions. All development follows a PR-based git worktree workflow with British English language conventions.

## License

This project is licensed under the Apache 2.0 License - see the [LICENSE](LICENSE) file for details.
