"""Conformance with the Model Context Protocol, revision 2026-07-28.

We documented how to *publish* an MCP server in detail and never wrote down what makes
one *valid*, which is how missing annotations reached every server in the fleet.

Two things make this repo unlike the twelve swept before it:

* **`isError` was already satisfied.** Issue #32 says "0 occurrences" of error dicts and
  it is right — this server raises rather than returning payloads, and measured, a
  raised exception already arrives as ``isError: true`` with its message intact. The
  only change on that front is `_require_db`, which now raises ``ToolError`` so the
  message does not depend on ``mask_error_details`` staying off.
  ``TestFailuresAreFlagged`` holds the behaviour either way.

* **`openWorldHint` is mostly *false* here, which is the inverse of the fleet.**
  Everywhere else nearly every tool calls somebody's web API. Here eleven of twelve
  tools answer from data already on this machine — nine query the local SQLite
  datasets, ``grid_info`` is Maidenhead arithmetic, ``get_version_info`` reads the
  wheel — and only ``current_conditions`` leaves the machine, for NOAA SWPC.
  ``TestOpenWorldIsPerTool`` is the point of this file: a copied block would have
  advertised eleven closed-domain tools as open-world.

Test IDs: IO-C01 onward.
"""

from __future__ import annotations

import asyncio

import pytest
from fastmcp.exceptions import ToolError

import ionis_mcp.server as srv

ANNOTATION_HINTS = ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint")

READS_LOCAL_DATASETS = {
    "list_datasets", "query_signatures", "band_openings", "path_analysis",
    "solar_correlation", "compare_sources", "dark_hour_analysis", "solar_history",
    "band_summary",
}
ANSWERS_WITHOUT_LOOKING = {"get_version_info", "grid_info"}
READS_NOAA = {"current_conditions"}
ALL_TOOLS = READS_LOCAL_DATASETS | ANSWERS_WITHOUT_LOOKING | READS_NOAA


def _tools() -> dict[str, object]:
    return {t.name: t for t in asyncio.run(srv.mcp.list_tools())}


def _wire(tool: object) -> dict[str, object]:
    annotations = getattr(tool, "annotations", None)
    assert annotations is not None, "tool declares no annotations"
    return annotations.model_dump(by_alias=True, exclude_none=True)


class TestToolAnnotations:
    def test_every_tool_declares_all_four_hints(self) -> None:
        """IO-C01: the defaults are pessimistic, so silence is the wrong answer."""
        for name, tool in _tools().items():
            wire = _wire(tool)
            for hint in ANNOTATION_HINTS:
                assert hint in wire, f"{name} omits {hint}; got {sorted(wire)}"

    def test_every_tool_is_read_only(self) -> None:
        """IO-C02: nothing here writes.

        `download.py` does write, and is deliberately not reachable from the tool
        layer — `server.py` does not import it. IO-C06 holds that.
        """
        for name, tool in _tools().items():
            wire = _wire(tool)
            assert wire["readOnlyHint"] is True, name
            assert wire["destructiveHint"] is False, name
            assert wire["idempotentHint"] is True, name


class TestOpenWorldIsPerTool:
    """The reason this file exists.

    Eleven of twelve tools answer from this machine. A block copied from any other
    server in the fleet would have set `openWorldHint: true` on all of them, which
    tells a client that a query against a local SQLite file reaches an open world.
    """

    def test_only_current_conditions_leaves_the_machine(self) -> None:
        """IO-C10: one true, eleven false — classified by what each tool touches."""
        tools = _tools()
        assert set(tools) == ALL_TOOLS
        for name in READS_NOAA:
            assert _wire(tools[name])["openWorldHint"] is True, (
                f"{name} reaches NOAA SWPC and must say so"
            )
        for name in READS_LOCAL_DATASETS | ANSWERS_WITHOUT_LOOKING:
            assert _wire(tools[name])["openWorldHint"] is False, (
                f"{name} answers from this machine and must not claim otherwise"
            )

    def test_the_split_is_eleven_to_one(self) -> None:
        """IO-C11: a guard against the whole set drifting one way or the other.

        If a future tool is added, this fails until somebody decides which side it is
        on — which is the decision the sweep found nobody had made.
        """
        wire = {n: _wire(t)["openWorldHint"] for n, t in _tools().items()}
        assert sum(1 for v in wire.values() if v is True) == 1
        assert sum(1 for v in wire.values() if v is False) == 11

    def test_the_classification_matches_the_imports(self) -> None:
        """IO-C12: the hints are checked against the code, not against this file.

        Two lists agreeing with each other proves nothing if both were written from
        the same guess. This reads `server.py` and asserts that exactly the tools
        annotated open-world are the ones whose bodies touch the network helper.
        """
        import ast
        import pathlib
        import re

        source = pathlib.Path(srv.__file__).read_text()
        lines = source.splitlines()
        network = re.compile(r"fetch_current_conditions|urlopen")
        reaches = set()
        for node in ast.parse(source).body:
            if isinstance(node, ast.FunctionDef) and any(
                isinstance(d, ast.Call) and getattr(d.func, "attr", "") == "tool"
                for d in node.decorator_list
            ):
                body = "\n".join(lines[node.lineno - 1:node.end_lineno])
                if network.search(body):
                    reaches.add(node.name)
        # Compared against the *published annotations*, not against the constants in
        # this file. An earlier version compared code to READS_NOAA, so moving a
        # decorator left it green while two other tests caught the fault — the
        # falsification run is what exposed that.
        declared = {n for n, t in _tools().items() if _wire(t)["openWorldHint"] is True}
        assert reaches == declared, (
            f"tools whose code touches the network: {sorted(reaches)}; "
            f"tools declaring openWorldHint true: {sorted(declared)}"
        )


class TestFailuresAreFlagged:
    """`isError` was already satisfied; this holds it that way.

    Issue #32 reports "0 occurrences" of error dicts, correctly. A raised exception
    already reached a client flagged, because FastMCP flags uncaught exceptions. The
    one change is that `_require_db` raises `ToolError`, whose message is shown
    regardless of `mask_error_details` — which defaults to None, i.e. to whatever the
    ambient setting happens to be.
    """

    def test_a_missing_database_is_a_flagged_error(self) -> None:
        """IO-C20: through the sanctioned channel, not the uncaught-exception path."""
        old = srv.db
        srv.db = None
        try:
            with pytest.raises(ToolError, match="Database not initialized"):
                srv._require_db()
        finally:
            srv.db = old

    def test_the_message_says_what_to_do(self) -> None:
        """IO-C21: a flagged error the caller cannot act on is only half the fix."""
        old = srv.db
        srv.db = None
        try:
            with pytest.raises(ToolError) as caught:
                srv._require_db()
            assert "IONIS_DATA_DIR" in str(caught.value)
        finally:
            srv.db = old

    def test_no_tool_returns_an_error_payload(self) -> None:
        """IO-C22: the shape the rest of the fleet had, which this repo never did.

        Read off the source so a path nobody thought to call is still covered.
        `"error"` appears twice as a *formatted value* — `rows_str = ... else "error"`
        — which is why this looks for the payload key specifically.
        """
        import pathlib

        src_dir = pathlib.Path(srv.__file__).parent
        offenders = [
            f"{py.name}:{i}: {line.strip()}"
            for py in src_dir.rglob("*.py")
            for i, line in enumerate(py.read_text().splitlines(), 1)
            if '"error":' in line or "'error':" in line
        ]
        assert not offenders, "error payloads found:\n" + "\n".join(offenders)


class TestTheWriteLayerIsNotReachable:
    def test_download_is_not_imported_by_the_tool_layer(self) -> None:
        """IO-C06: the one module here that writes must stay out of the tools.

        `download.py` writes files and opens sockets. Every tool is annotated
        `readOnlyHint: True`, and that is only honest while `server.py` cannot reach
        it. Asserted because an import is one line and nobody would think to check.
        """
        import pathlib

        source = pathlib.Path(srv.__file__).read_text()
        assert "from .download" not in source
        assert "import download" not in source


class TestVersionInfoShape:
    def test_it_matches_the_shape_the_fleet_returns(self) -> None:
        """IO-C40: the convention that drifted because nobody asserted it."""
        info = srv.get_version_info()
        assert info["service_name"] == "ionis-mcp"
        assert info["service_version"]
        assert info["spec_version"]


class TestRegistration:
    def test_the_twelve_tools_a_client_sees(self) -> None:
        """IO-C50: calling a function directly is not proof a client can."""
        assert set(_tools()) == ALL_TOOLS
