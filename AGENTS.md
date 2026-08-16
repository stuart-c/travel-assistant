# Agent Workflow Guide

This document defines the mandatory workflow for all AI agents and developers working on the `travel-assistant` repository. Following these rules ensures consistency, prevents conflicts, and maintains high code quality. All GitHub interactions **MUST** be performed using the GitHub CLI (`gh`) rather than the web browser where possible.

## 0. Language Standard
All documentation, UI labels, and internal code comments (where standards allow) **MUST** use **British English**.
- Use `colour` instead of `color`.
- Use `-ise` suffixes instead of `-ize` (e.g., `initialise`, `standardise`, `optimise`).
- Use `greyscale` instead of `grayscale`.
- Use `centre` instead of `center` (except in CSS property names).

## 1. Documentation First
Before making changes, agents **MUST** read all documentation in the root and relevant subdirectories:
- `README.md`
- `AGENTS.md` (this file)
- `travel-assistant/DOCS.md`
- `travel-assistant/CHANGELOG.md`

## 2. Branch Naming
All branches must be named according to [Conventional Commits](https://www.conventionalcommits.org/):
- `feat/`: New features
- `fix/`: Bug fixes
- `docs/`: Documentation changes
- `style/`: Formatting, missing semicolons, etc; no code change
- `refactor/`: Refactoring production code
- `test/`: Adding missing tests, refactoring tests; no production code change
- `chore/`: Updating build tasks, package manager configs, etc; no production code change

Example: `feat/add-route-planner` or `fix/broken-ingress-links`.

## 3. Pre-Push Verification
Tests and lints **MUST** be run locally before being pushed to GitHub. This is mandatory whenever Python or frontend code is modified.

### Mandatory Verification Scripts
- **Setup Environment**: `bash scripts/make_venv.sh`
- **Run Tests & Lints**: `bash scripts/run_tests.sh`
- **Full Verification**: `bash scripts/verify_all.sh`

### Quality Targets
- **Code Coverage**: Aim for 100% unit test code coverage for new backend code.
- **Linting**: Ensure `black --check` and `flake8` pass with 0 warnings or errors.

## 4. Mandatory Pull Requests & Review Workflow
**All changes, regardless of size or scope, MUST be submitted as a Pull Request (PR) for user review.** Direct pushes or commits to `main` are strictly forbidden.

### Pull Request Rules
- **Always Create a PR**: Every task must culminate in a GitHub Pull Request created using `gh pr create`.
- **Provide Direct PR Link**: Agents **MUST ALWAYS** provide the direct URL/link to the newly created Pull Request in their response to the user so they can review it immediately.
- **Mergeability**: PRs **MUST** be rebased from the latest `main` branch before any review is requested:
  ```bash
  git fetch origin
  git rebase origin/main
  ```
- **Local Verification**: Ensure all tests and lints pass locally via `bash scripts/verify_all.sh` prior to creating or updating a PR.
- **PR Quality**: When creating a PR, provide a detailed title and description explaining:
  - **Purpose**: Why are these changes being made?
  - **Implementation**: How were the changes implemented? Highlight architectural decisions and patterns.
- **Auto-Merge**: Enable auto-merge when creating a pull request:
  ```bash
  gh pr create --fill
  gh pr merge --auto --squash
  ```

## 5. Post-Merge Cleanup
When a PR is merged, tidy the local environment:
1. Delete the local branch: `git branch -d <branch-name>`
2. Update the local `main` branch: `git checkout main && git pull origin main`

## 6. GitHub CLI Authentication
To facilitate automated interactions, agents use a Personal Access Token (PAT) stored in a `.gh_token` file in the repository root or existing `gh` configuration.
- The `.gh_token` file is included in `.gitignore` to prevent accidental commits. Never share or commit this file.

## 7. No Backward-Compatibility Aliases
This repository is a self-contained Home Assistant add-on application and is not consumed as an external library or package.
- **Never create backward-compatibility aliases, wrappers, or fallbacks** when refactoring, replacing, or removing classes, models, functions, or endpoints.
- When replacing a model or function (e.g. `BusStop` / `Station` -> `Stop`), update all call sites, imports, database schemas, and unit tests directly, and delete obsolete identifiers entirely.
- Avoid introducing legacy aliases as they add dead code and unnecessary complexity.
