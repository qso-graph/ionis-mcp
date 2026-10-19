# Changelog

All notable changes to `ionis-mcp` are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Lint (#31, qso-graph-devel#70)

- **`E501` is adopted.** It reported **56 lines** and not one of them was a defect — the finding,
  not an argument against enforcing it. The rules that do find defects (`F`, `I`, mypy strict)
  went in first, which is why this waited.
- **No line is exempt**; there is no `# noqa: E501` in the repo. The two markdown table headers
  in `server.py` split at a column boundary, so every column name stays whole and the rendered
  output is unchanged. Most of the rest are user-facing f-strings — progress lines, warnings,
  band advice — which split across adjacent literals with the same result.
- **Nothing moved on the wire.** Every tool's description and `inputSchema` was dumped through a
  real client before and after: byte-identical.
- **One mistake worth recording.** Removing the `E501` entry, my regex also deleted
  `select = ["E", "F", "I"]`, which silently switched ruff to its *default* rule set — 26
  violations appeared from rules (`BLE`, `UP`, `RUF`) this repo never opted into. They looked
  like pre-existing debt and were not. Caught by reconciling two counts that disagreed, 26
  against 56, rather than by reading the diff.
- Falsified: a long line planted in `src/` and another in `tests/`, both caught.

### TLS (#30, qso-graph-devel#73)

- **`certifi` is carried, and both fetch paths verify against it.** Neither `urlopen` passed a
  context, so both trusted whichever root store the running Python was built against. On macOS
  that is `/etc/ssl/cert.pem`, a deliberately *reduced* OpenSSL-compatibility file: current, not
  stale, but it omits roots the OS itself trusts.
- **There are two call sites here, in two modules, reaching two different certificate
  authorities** — `noaa.py` for NOAA SWPC and `download.py` for the dataset downloads. The
  context therefore lives in a new `tls.py` rather than in either of them: one root set, one
  place to change it, and one thing for the gate to point at. Two contexts would be two root
  sets to keep in step.
- **Measured 2026-10-19**, both hosts verify against Apple's file and against `certifi` alike, so
  this was latent rather than an outage: `services.swpc.noaa.gov` chains to Amazon Root CA 1, and
  `sourceforge.net` chains to ISRG Root X2. With two unrelated authorities in play, the chance
  that one rotates to a root Apple omits is twice what a single-host server carries.
- `certifi` is declared directly. Measured: it is **not** transitive through `fastmcp>=4.0,<5`,
  this package's only other dependency, so an undeclared import would be an ImportError at
  startup for anyone who ran `pip install ionis-mcp`.
- This server holds no credential, so a trust failure costs an answer rather than a secret — but
  invisibly: the user is told the download failed, or that conditions could not be read, with
  nothing pointing at trust. Verification is never disabled; `ssl.CERT_NONE` would make a call
  "work" by accepting any certificate from anyone.
- Four checks in `tests/test_security.py`, written to **this** repo's conventions rather than the
  fleet's — it uses `os.path` strings and `_all_py_sources()`, not `pathlib` and the
  `_py_files()` helper the other twelve have. My first version assumed the common shape and
  failed four ways.
- Six falsifications, every one caught, including **a third fetch path added with no context** —
  this is the repo that makes the whole-package scan matter, and the check is aimed at the
  package rather than at the file being edited.
- Live, with a negative control: both hosts return 200 through a context carrying 117 roots with
  `CERT_REQUIRED` and hostname checking on, and the same host with an empty root set fails with
  `CERTIFICATE_VERIFY_FAILED` — so the probe is evidence of verification rather than of the
  request merely working.

### MCP specification 2026-07-28 (#32)

**No upgrading note, and that is the finding.** Issue #32 reports "0 occurrences" of error
dicts in `src/` and it is right — the first issue in this fleet sweep whose count was not
inflated. This server raises rather than returning error payloads, and measured through a real
client, a raised exception already arrived as `isError: true` with its message intact. So the
protocol half of this issue was already satisfied before any change.

- **All 12 tools declare the four annotation hints**, which was the actual gap: they declared
  none, and the defaults advertise a tool as `destructiveHint: true`, `idempotentHint: false`
  and `openWorldHint: true`.
- **`openWorldHint` is false on eleven of twelve tools — the inverse of every other server in
  the fleet.** Everywhere else nearly every tool calls somebody's web API. Here nine tools query
  the SQLite datasets already on this machine (the specification's own example of a closed
  domain is a database query), `grid_info` is Maidenhead arithmetic, and `get_version_info`
  reads the wheel. Only `current_conditions` leaves the machine, for NOAA SWPC. A block copied
  from any other repo in this sweep would have told clients that querying a local file reaches
  an open world.
- Classified by reading what each tool touches, with an AST walk, not by reading the tool names.
- `idempotentHint: true` throughout, including `current_conditions` where space weather changes
  between calls: the hint is about the tool not changing state, not about a stable answer.
- **`_require_db` raises `ToolError`** instead of `RuntimeError`. Not a fix for a broken path —
  it already reached the client flagged. It removes a dependence on a default:
  `FastMCP(mask_error_details=...)` defaults to `None`, i.e. to whatever the ambient setting
  says, and with masking on an uncaught exception's text is replaced. `ToolError` is the channel
  whose message is always shown. It also drops FastMCP's `Error calling tool 'x': ` prefix and
  the ERROR-level traceback, so the client now sees exactly
  `Database not initialized. Set IONIS_DATA_DIR.`
- **A test asserts `download.py` stays out of the tool layer.** It is the one module here that
  writes files and opens sockets, every tool is annotated `readOnlyHint: true`, and that is only
  honest while `server.py` cannot reach it. An import is one line and nobody would think to
  check.
- **`tests/test_mcp_conformance.py`**: 11 tests, `IO-C01` onward. One compares the *published
  annotations* against an AST walk of the source, so a tool that gains a network call without
  gaining the hint fails. Its first version compared the code against a constant in the test
  file instead — two lists agreeing with each other, which proves nothing — and the
  falsification run is what exposed that.
- Nine falsifications, every one caught, including the copied-block mistake in both directions:
  the local readers claiming open-world, and `current_conditions` pretending it stays home.

## [1.3.2] — 2026-10-11

- **ruff and mypy run in CI** (qso-graph-devel#66), as a job the `ci-all-green` gate requires.
  Settings follow `adif-mcp`, the reference for every qso-graph Python repo, rather than a style of
  this repo's own. They run once rather than per Python version: both read the source, and neither
  answer changes with the interpreter.
- **`noaa.py` was annotated with the builtin `any`, not `typing.Any`.** `_fetch_json` declared
  `-> any` and the response cache `tuple[float, any]`. `any` is a function, so neither annotation
  named a type, and nothing NOAA returns was checked anywhere it was read. Ten of this repo's
  forty-three findings came from that one letter.
- Return and parameter types across `database.py`, `download.py` and `server.py`: the query methods
  say what their rows hold, `close` and the two console entry points say they return nothing, and
  the download progress reporter names the stream and clock its tests replace.
- Six unused imports removed, and one f-string with nothing to interpolate.
- `E501` is deferred rather than adopted (qso-graph-devel#70): what it reports in these repos are
  widths, not defects, and some lines are long because they name a publisher's field exactly.
- `mcp.run` is given the literal fastmcp asks for rather than a `str` that happens to hold the
  right word.
- **`fastmcp` is bounded: `>=4.0,<5`** (qso-graph-devel#60). It was `>=3.0` with no upper bound, and
  these servers are run with `uvx`, which resolves fresh — so a `fastmcp` 5.0 would have reached
  every user automatically, before anything here had been run against it. The floor rises to 4.0
  because that is what is actually tested: every lock in the fleet held a 4.x, and nothing in CI
  has ever exercised 3.x. A claim of 3.x support that no test backs is not support.
- `fastmcp` is locked at 4.1.0, the current release, so CI runs against what a new install gets.
- **The published contact is `maintainers@qso-graph.io`** (qso-graph-devel#69). The `authors` field
  carried a personal address, and that field is what PyPI shows on the package page. Everything in
  qso-graph is open source and open to contribution, so the contact is the project's.

## [1.3.1] — 2026-10-07

- LICENSE: the full GPL-3.0 text. The file held only its opening and a link, so GitHub detected no licence.

## [1.3.0] — 2026-10-06

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
