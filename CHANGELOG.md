# Changelog

All notable changes to `ionis-mcp` are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

- **ionis-download resumes and retries** (#14). It downloads to `<file>.part` and, after a dropped
  connection or Ctrl-C, picks up where it stopped (an HTTP Range request) instead of starting again
  from zero. Timeouts, dropped connections and server errors (5xx) are retried up to 5 times with
  backoff. The file is moved into place only after the database check passes. An error page or a
  404 is not retried, and a redirect away from HTTPS is refused.
- **ionis-download progress no longer floods logs** (#15). Off a terminal it prints a line every
  10% (or every 30 seconds); on a terminal the live line is redrawn at most twice a second.
- **ionis-download sizes are right** (#16). They were MiB labelled MB, and the bundle sizes were
  hand-written. They are now exact decimal MB/GB from the v1.0 files: WSPR 9.1 GB (was "8,639 MB"),
  the full set 16.2 GB (was "~15 GB"), minimal 454 MB (was "~430 MB"). The README matches.
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
