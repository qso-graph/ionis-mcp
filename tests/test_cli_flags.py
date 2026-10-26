"""The console script answers --version instead of rejecting it.

--help already worked here: ionis-mcp uses argparse, which supplies it. --version
was simply not declared, so argparse exited 2 with a usage line. Fourteen sibling
servers had the worse form of this — they ignored both flags and started the MCP
server on stdio, leaving an apparently hung terminal — and are fixed in their own
repositories.
"""

from __future__ import annotations

import pytest

from ionis_mcp import __version__, server


def test_version_exits_without_serving(capsys, monkeypatch):
    monkeypatch.setattr("sys.argv", ["ionis-mcp", "--version"])
    # argparse's "version" action prints and raises SystemExit(0), so the server
    # is never reached.
    with pytest.raises(SystemExit) as exc:
        server.main()
    assert exc.value.code == 0
    assert f"ionis-mcp {__version__}" in capsys.readouterr().out
