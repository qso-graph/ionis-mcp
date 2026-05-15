"""ionis-mcp — MCP server for IONIS HF propagation analytics."""

from __future__ import annotations

import os
import sys
from importlib.metadata import PackageNotFoundError, version
from typing import Final

try:
    _pkg_version = version("ionis-mcp")
except PackageNotFoundError:  # local dev / editable installs without dist metadata
    _pkg_version = "0.0.0-dev"

__version__: Final[str] = _pkg_version

# Upstream data spec the server is bound to. Pinned to the IONIS
# SourceForge dataset bundle revision we consume. Bump this when a new
# dataset bundle is released that changes the schema or signature
# semantics. Reported by the get_version_info tool so agents can detect
# fleet drift without going outside the MCP protocol.
__spec_version__: Final[str] = "ionis-dataset-v1"


def default_data_dir() -> str:
    """Return the platform-specific default data directory.

    - Linux/macOS: ~/.ionis-mcp/data
    - Windows: %LOCALAPPDATA%\\ionis-mcp\\data
    """
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
        return os.path.join(base, "ionis-mcp", "data")
    return os.path.join(os.path.expanduser("~"), ".ionis-mcp", "data")
