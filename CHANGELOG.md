# Changelog

All notable changes to `ionis-mcp` are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.2.10] — 2026-09-28

### Added (CI hygiene)

- **MCP Registry sync** — `publish.yml` publishes to the [Official MCP Registry](https://registry.modelcontextprotocol.io)
  after each PyPI publish, using GitHub OIDC for auth. Triggered on
  `v*` tag push; no manual steps. The Registry job waits until PyPI
  serves the version, and retries. Pattern documented in
  [qso-graph/.github/TEMPLATES.md](https://github.com/qso-graph/.github/blob/main/TEMPLATES.md).
- **Registry version badge** in README — PyPI and Registry versions
  are visible side-by-side so any drift between publishing surfaces
  is immediately apparent.
- **Release gates** — the tag must match `pyproject.toml`, and a
  `verify` job fails the release unless PyPI and the MCP Registry
  both serve the new version.

### Fixed

- The Official MCP Registry listed ionis-mcp at 1.2.7. This release brings it current.
- **current_conditions parsing drift** (same root cause as solar-mcp) — Updated `fetch_current_conditions` in `noaa.py` to handle current SWPC JSON formats for 10cm-flux (list-of-dicts), noaa-planetary-k-index (list-of-dicts), and solar-wind-mag-field (list). Legacy dict support retained. Now correctly returns SFI/Kp/Bz instead of falling back to "unavailable" and error notes. Matches the solar-mcp fix for the same upstream API change.

## [1.2.9] — 2026-05-15

### Added
- New tool `get_version_info` — returns `{service_name, service_version, spec_version}`
  for fleet identity attestation. Lets agents detect version drift across MCP
  deployments without going outside the protocol. Tracks
  [IONIS-AI/ionis-devel#49](https://github.com/IONIS-AI/ionis-devel/issues/49)
  (fleet rollout).
- `__spec_version__` constant in package `__init__.py`, pinned to
  `ionis-dataset-v1` for the current IONIS SourceForge dataset bundle.
- `TestGetVersionInfo` test class covering the new tool (5 tests).
- `.github/workflows/ci.yml` — PR-gating CI workflow (py3.10-3.13 matrix,
  unit + security tests, ci-all-green aggregator).

### Changed
- `__init__.py` modernized: switched from hardcoded `__version__ = "1.1.0"`
  (which was stale relative to pyproject's `1.2.8`) to dynamic resolution
  via `importlib.metadata.version()`. Uses the `adif-mcp`/`solar-mcp`
  pattern (`Final` types, explicit `PackageNotFoundError` handling).

### Fixed
- Version drift between `__init__.__version__` (was `1.1.0`) and
  `pyproject.toml` (was `1.2.8`). Now `__version__` derives from the
  installed PyPI metadata, so they cannot diverge.

## [1.2.8] — Previous release
- See git history for changes prior to the changelog being introduced.
