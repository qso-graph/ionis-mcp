"""Spacing between requests to NOAA SWPC.

NOAA's Space Weather Prediction Center serves these files publicly and states
no per-client limit. solar-mcp already reads the same service and already
settled on a figure, so this matches that decision rather than making a second
one for one provider.

Deliberately not applied to download.py. That fetches multi-gigabyte
SourceForge datasets, where a fraction of a second between whole-file
transfers measures nothing; the restraint that matters there is not
re-downloading, which its checksum check already provides.

This is not throttling the user (KI7MT, 2026-10-11): it limits what this server
sends to somebody else's service, and does not limit the person asking. The
cache in noaa.py, holding responses 900 s does the larger share of the
work -- it removes requests rather than delaying them -- and this covers what the
cache cannot: a model calling tools in a loop over inputs that each miss.
"""

from __future__ import annotations

import threading
import time
from typing import Final

# Seconds between outbound requests.
# The same 200 ms solar-mcp uses against NOAA SWPC. One provider, one figure.
MIN_INTERVAL: Final[float] = 0.2

_lock = threading.Lock()
_last: float = 0.0


def wait() -> None:
    """Block until MIN_INTERVAL has passed since the previous request.

    Held across threads by one lock, so concurrent tool calls queue rather than
    each measuring their own gap and all firing at once.
    """
    global _last
    with _lock:
        elapsed = time.monotonic() - _last
        if elapsed < MIN_INTERVAL:
            time.sleep(MIN_INTERVAL - elapsed)
        _last = time.monotonic()
