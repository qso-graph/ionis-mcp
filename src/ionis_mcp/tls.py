"""The one verifying TLS context this package uses, and why it carries its own roots.

Two modules open sockets — `noaa.py` for NOAA SWPC and `download.py` for the dataset
downloads — so the context lives here rather than in either of them. One root set, one
place to change it, and one thing for `tests/test_security.py` to point at.
"""

from __future__ import annotations

import ssl
from functools import cache

import certifi


@cache
def context() -> ssl.SSLContext:
    """A verifying context with a current root set. Built once.

    The roots come from ``certifi`` — Mozilla's root program, the set the rest of the
    Python ecosystem verifies against — rather than whichever store the running Python
    was built against. On macOS that distinction is real: Apple ships
    ``/etc/ssl/cert.pem`` for OpenSSL, and therefore for Python, as a deliberately
    *reduced* file. It is current, not stale, but it omits roots the OS itself trusts,
    so a certificate chaining to one of them fails for Python while ``curl`` to the
    same URL succeeds (qso-graph-devel#73, found when meteor-mcp could not reach NASA
    at all).

    Measured 2026-10-19, both hosts this package talks to verify against Apple's file
    and against ``certifi`` alike:

    * ``services.swpc.noaa.gov`` chains to Amazon Root CA 1
    * ``sourceforge.net`` chains to ISRG Root X2

    So this is latent rather than an outage. What it buys is that the root set is a
    dependency this project updates, not a file the operating system hands us — and
    with two different certificate authorities in play, the chance that one of them
    rotates to a root Apple omits is twice what a single-host server carries.

    This server holds no credential, so a trust failure costs an answer rather than a
    secret. But it would cost it invisibly: the user is told the download failed, or
    that conditions could not be read, with nothing pointing at trust.

    Verification is never disabled. ``ssl.CERT_NONE`` or ``check_hostname = False``
    would also make a call "work", by accepting any certificate from anyone — a worse
    defect than this one, and a silent one. The fix is the right root set, not a
    relaxed check.
    """
    return ssl.create_default_context(cafile=certifi.where())
