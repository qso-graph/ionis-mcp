"""L1 Security tests for ionis-mcp — MCP Security Framework compliance.

Verifies the 10 non-negotiable security guarantees from
planning/MCP-SECURITY-FRAMEWORK.md. These tests scan source code
statically — no runtime, no network, no fixtures needed.

Guarantees tested:
  S1: Credentials in OS keyring only (N/A — ionis-mcp has no credentials)
  S2: Credentials never in logs/tool results/errors
  S3: No command injection surface (no subprocess, no shell=True)
  S4: All external connections HTTPS only
  S5: Rate limiting (structural — NOAA cache TTL)
  S6: Input validation on user strings
  S7: No eval/exec
  S8: No hardcoded secrets
  S9: Read-only database access (sqlite mode=ro)
  S10: No credential leakage in error messages
"""

import ast
import os
import re

SRC_DIR = os.path.join(os.path.dirname(__file__), "..", "src", "ionis_mcp")


def _all_py_sources():
    """Yield all Python source files under SRC_DIR."""
    for root, _, files in os.walk(SRC_DIR):
        for f in files:
            if f.endswith(".py"):
                yield os.path.join(root, f)


# ── S2: No credential logging ───────────────────────────────────────────────

def test_no_print_credentials():
    """S2: No print() calls with credential keywords."""
    pattern = re.compile(
        r'print\s*\(.*?(password|passwd|secret|api_key|token|credential)',
        re.IGNORECASE,
    )
    for path in _all_py_sources():
        with open(path) as fh:
            src = fh.read()
        assert not pattern.search(src), f"Credential print in {path}"


def test_no_logging_credentials():
    """S2: No logging calls with credential keywords."""
    pattern = re.compile(
        r'log(?:ging|ger)?\.\w+\s*\(.*?(password|passwd|secret|api_key|credential)',
        re.IGNORECASE,
    )
    for path in _all_py_sources():
        with open(path) as fh:
            src = fh.read()
        assert not pattern.search(src), f"Credential logging in {path}"


# ── S3: No command injection ─────────────────────────────────────────────────

def test_no_subprocess():
    """S3: No subprocess or shell=True usage."""
    pattern = re.compile(r'\bsubprocess\b|shell\s*=\s*True')
    for path in _all_py_sources():
        with open(path) as fh:
            src = fh.read()
        assert not pattern.search(src), f"subprocess/shell in {path}"


def test_no_os_system():
    """S3: No os.system() or os.popen() calls."""
    pattern = re.compile(r'os\.(system|popen)\s*\(')
    for path in _all_py_sources():
        with open(path) as fh:
            src = fh.read()
        assert not pattern.search(src), f"os.system/popen in {path}"


# ── S4: HTTPS only ──────────────────────────────────────────────────────────

def test_all_urls_https():
    """S4: All hardcoded URLs use HTTPS (except localhost)."""
    pattern = re.compile(r'http://(?!localhost|127\.0\.0\.1)')
    for path in _all_py_sources():
        with open(path) as fh:
            src = fh.read()
        assert not pattern.search(src), f"Non-HTTPS URL in {path}"


# ── S5: Rate limiting ───────────────────────────────────────────────────────

def test_noaa_cache_ttl_exists():
    """S5: NOAA module has a cache TTL to prevent hammering."""
    noaa_path = os.path.join(SRC_DIR, "noaa.py")
    with open(noaa_path) as fh:
        src = fh.read()
    assert "_CACHE_TTL" in src, "NOAA cache TTL not found"
    assert "_cache" in src, "NOAA cache dict not found"


# ── S7: No eval/exec ────────────────────────────────────────────────────────

def test_no_eval_exec():
    """S7: No eval() or exec() in source code."""
    for path in _all_py_sources():
        with open(path) as fh:
            src = fh.read()
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id in ("eval", "exec"):
                    raise AssertionError(f"eval/exec found in {path}")


# ── S8: No hardcoded secrets ────────────────────────────────────────────────

def test_no_hardcoded_secrets():
    """S8: No hardcoded API keys, passwords, or tokens in source."""
    patterns = [
        re.compile(
            r'(?:api_key|password|secret|token)\s*=\s*["\'][^"\']{8,}["\']',
            re.IGNORECASE),
        re.compile(r'sk-[a-zA-Z0-9]{20,}'),  # OpenAI-style keys
        re.compile(r'Bearer\s+[a-zA-Z0-9]{20,}'),
    ]
    for path in _all_py_sources():
        with open(path) as fh:
            for i, line in enumerate(fh, 1):
                if line.lstrip().startswith("#"):
                    continue
                for pat in patterns:
                    assert not pat.search(line), (
                        f"Possible hardcoded secret in {path}:{i}: {line.strip()[:80]}"
                    )


# ── S9: Read-only database ──────────────────────────────────────────────────

def test_sqlite_read_only():
    """S9: All SQLite connections use mode=ro (read-only)."""
    db_path = os.path.join(SRC_DIR, "database.py")
    with open(db_path) as fh:
        src = fh.read()
    # Every sqlite3.connect call should use mode=ro
    connect_calls = re.findall(r'sqlite3\.connect\([^)]+\)', src)
    assert connect_calls, "No sqlite3.connect calls found in database.py"
    for call in connect_calls:
        assert "mode=ro" in call, f"SQLite connection without mode=ro: {call}"


# ── S10: Safe error messages ────────────────────────────────────────────────

def test_error_messages_safe():
    """S10: No credential interpolation in error messages."""
    dangerous = re.compile(
        r'\{(password|api_key|secret|creds\.password|creds\.api_key)\}',
        re.IGNORECASE,
    )
    for path in _all_py_sources():
        with open(path) as fh:
            for i, line in enumerate(fh, 1):
                if line.lstrip().startswith("#"):
                    continue
                matches = dangerous.findall(line)
                assert not matches, (
                    f"Credential interpolation in {path}:{i}: {line.strip()}"
                )


# ── S6: Input validation ────────────────────────────────────────────────────

def test_sql_uses_parameterized_queries():
    """S6: All SQL queries use parameterized ? placeholders, not f-strings for values."""
    db_path = os.path.join(SRC_DIR, "database.py")
    with open(db_path) as fh:
        src = fh.read()
    # Check that execute calls use ? params, not direct string interpolation of user values
    # The table names are from a fixed registry (safe), but WHERE values must be parameterized
    dangerous = re.compile(r'execute\([^)]*\{(tx_grid|rx_grid|band|hour|month|source)')
    assert not dangerous.search(src), "User input interpolated directly in SQL query"


def test_grid_validation_exists():
    """S6: Grid validation function exists and rejects bad input."""
    from ionis_mcp.grids import validate_grid

    # Valid grids
    assert validate_grid("DN13") is not None
    assert validate_grid("dn13") is not None
    assert validate_grid("JO51ab") is not None

    # Invalid grids — must return None
    assert validate_grid("") is None
    assert validate_grid("ZZ99") is None  # Z > R in field
    assert validate_grid("AAAA") is None
    assert validate_grid("12AB") is None
    assert validate_grid("'; DROP TABLE--") is None
    assert validate_grid("<script>") is None


def _code_only(path: str) -> str:
    """The file with comments and string literals removed.

    Some checks must read what the code *does*, not what it says about itself.
    `tls.context()` carries a docstring explaining that `ssl.CERT_NONE` would be the
    wrong fix, and a plain text search cannot tell that sentence from the thing it
    warns against.
    """
    import tokenize

    kept = []
    with open(path, "rb") as handle:
        for token in tokenize.tokenize(handle.readline):
            if token.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            kept.append(token.string)
    return " ".join(kept)


def test_tls_verification_is_never_disabled():
    """Guarantee #8: no context here stops checking certificates.

    This server holds no credential, so a trust failure costs an answer rather than a
    secret. But `ssl.CERT_NONE` would still accept any certificate from anyone, which
    is a worse defect than the one qso-graph-devel#73 fixes, and an invisible one.
    """
    forbidden = re.compile(r"CERT_NONE|check_hostname\s*=\s*False|_create_unverified")
    for py_file in _all_py_sources():
        matches = forbidden.findall(_code_only(py_file))
        assert not matches, (
            f"TLS verification weakened in {os.path.basename(py_file)}: {matches}"
        )


def test_the_root_set_is_carried_not_borrowed():
    """Guarantee #8: the roots come from certifi, not the host's OpenSSL store.

    One context for the whole package, in tls.py, because two modules open sockets:
    noaa.py and download.py. Two contexts would be two root sets to keep in step.
    """
    with open(os.path.join(SRC_DIR, "tls.py")) as fh:
        assert "cafile=certifi.where()" in fh.read()


def test_certifi_is_declared_not_merely_imported():
    """Guarantee #8: an import the wheel does not declare is an ImportError at startup.

    Measured 2026-10-19: `certifi` is not transitive through `fastmcp>=4.0,<5`, this
    package's only other dependency. Drop the declaration and `pip install ionis-mcp`
    gives a server that cannot start.
    """
    root = os.path.join(SRC_DIR, "..", "..", "pyproject.toml")
    with open(root) as fh:
        pyproject = fh.read()
    deps = pyproject.split("dependencies = [", 1)[1].split("]", 1)[0]
    assert re.search(r'^\s*"certifi', deps, re.MULTILINE), (
        "tls.py imports certifi but [project] dependencies does not declare it"
    )


def test_every_outbound_call_verifies():
    """Guarantee #8: neither fetch path can quietly skip the context.

    This repo is why the check is written across the whole package rather than against
    one file: there are **two** call sites, in different modules, reaching different
    certificate authorities — NOAA SWPC and SourceForge. lotw-mcp, qrz-mcp and
    eqsl-mcp each had two as well, and a check aimed at the file you happen to be
    editing is a check that misses the other one.

    Line by line rather than by matching balanced parentheses: a regex for the whole
    call ends at the first ")", which is the one inside "context()", so it would read a
    call that passes no context as though it did.
    """
    calls = []
    for py_file in _all_py_sources():
        with open(py_file) as fh:
            for i, line in enumerate(fh.read().splitlines(), 1):
                if "urllib.request.urlopen(" in line:
                    calls.append((os.path.basename(py_file), i, line))
    assert len(calls) >= 2, f"expected both fetch paths, found {calls}"
    for filename, number, line in calls:
        assert "context=tls.context()" in line, (
            f"{filename}:{number} opens a connection without a verifying context: "
            f"{line.strip()}"
        )
