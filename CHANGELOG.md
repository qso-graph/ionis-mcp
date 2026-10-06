# Changelog

All notable changes to `ionis-mcp` are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

- **Missing data is no longer reported as a closed band** (#13). With a dataset not installed (or
  none at all), the signature tools answered with empty tables, e.g. `band_openings` gave 24 hours
  of 0 spots. They now say which dataset is missing and the `ionis-download` command that gets it.
  An unknown `source` is an error too. A path with no observations in an installed dataset is still
  answered as such.
- **Bad SFI values in the datasets are treated as unknown** (#17). Some signatures carry an SFI of
  0 or single-day spikes up to 938.6, which made 20m's SFI range read 66–939. Analyses now use SFI
  only within 50–400 and say how many signatures were left out. `band_summary`'s range,
  `solar_correlation`'s brackets (now 50-80 … 200-400) and `band_openings`' hourly SFI (which a 0
  also diluted) all use it, and the row listings show an implausible SFI as —. Measured in the
  v1.0 datasets: WSPR 63,715 signatures (0.07%), RBN 51,204 (0.08%), PSKR 92,609 (1.1%),
  DXpedition 149 (0.06%), contest none.
- PyPI: a Documentation link (qso-graph/.github#15).
- CI: the release flow (qso-graph/.github TEMPLATES.md). Work lands on `develop`; a release is a
  PR from `develop` into `main`, and merging it publishes to PyPI and the MCP Registry, verifies both
  and tags the release. CI runs on `develop` too, and PRs into `main` must come from `develop` or a
  `security/` branch.

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
