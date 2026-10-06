"""ionis-download — Download IONIS datasets from SourceForge.

User-friendly CLI for downloading SQLite datasets used by ionis-mcp.
Supports preset bundles (minimal, recommended, full) or individual datasets.
Downloads to the platform default directory unless overridden.
"""

import argparse
import http.client
import os
import sys
import time
import urllib.error
import urllib.request

from . import default_data_dir

SF_BASE = "https://sourceforge.net/projects/ionis-ai/files/v1.0"

# Dataset registry: key → (relative path, filename, description, size in bytes)
# Sizes are the v1.0 files on SourceForge, exactly (#16).
DATASETS = {
    # Propagation signatures
    "wspr": (
        "propagation/wspr-signatures",
        "wspr_signatures_v2.sqlite",
        "WSPR beacon signatures (93.6M rows, 2008-2026)",
        9_059_115_008,
    ),
    "rbn": (
        "propagation/rbn-signatures",
        "rbn_signatures.sqlite",
        "RBN CW/RTTY signatures (67.3M rows, 2009-2026)",
        6_032_490_496,
    ),
    "contest": (
        "propagation/contest-signatures",
        "contest_signatures.sqlite",
        "CQ contest signatures (5.7M rows, 2005-2025)",
        444_567_552,
    ),
    "dxpedition": (
        "propagation/dxpedition-signatures",
        "dxpedition_signatures.sqlite",
        "DXpedition rare-grid signatures (260K rows)",
        22_233_088,
    ),
    "pskr": (
        "propagation/pskr-signatures",
        "pskr_signatures.sqlite",
        "PSK Reporter FT8/WSPR signatures (8.4M rows, Feb 2026+)",
        634_847_232,
    ),
    # Solar
    "solar": (
        "solar/solar-indices",
        "solar_indices.sqlite",
        "Solar indices — SFI, SSN, Kp, Ap (76.7K rows, 2000-2026)",
        8_024_064,
    ),
    "dscovr": (
        "solar/dscovr",
        "dscovr_l1.sqlite",
        "DSCOVR L1 solar wind — Bz, speed, density (23K rows)",
        3_006_464,
    ),
    # Tools
    "grids": (
        "tools/grid-lookup",
        "grid_lookup.sqlite",
        "Maidenhead grid coordinates (31.7K grids)",
        1_118_208,
    ),
    "balloons": (
        "tools/balloon-callsigns",
        "balloon_callsigns_v2.sqlite",
        "Known balloon/telemetry callsigns (1.5K entries)",
        118_784,
    ),
}

# Preset bundles
BUNDLES = {
    "minimal": {
        "description": "Basic propagation queries",
        "datasets": ["contest", "grids", "solar"],
    },
    "recommended": {
        "description": "Contest + PSKR + solar + tools",
        "datasets": ["contest", "pskr", "grids", "solar", "dscovr", "balloons"],
    },
    "full": {
        "description": "All 9 datasets",
        "datasets": list(DATASETS.keys()),
    },
}


def _download_url(key: str) -> str:
    """Build SourceForge download URL for a dataset."""
    path, filename, _, _ = DATASETS[key]
    return f"{SF_BASE}/{path}/{filename}/download"


def _dest_path(data_dir: str, key: str) -> str:
    """Build the local destination path preserving directory structure."""
    path, filename, _, _ = DATASETS[key]
    return os.path.join(data_dir, path, filename)


def _format_size(size: int) -> str:
    """Bytes as decimal MB or GB, as disks and download speeds are labelled (#16)."""
    if size >= 1_000_000_000:
        return f"{size / 1e9:.1f} GB"
    if size >= 10_000_000:
        return f"{size / 1e6:,.0f} MB"
    return f"{size / 1e6:.1f} MB"


def _bundle_size(name: str) -> int:
    return sum(DATASETS[k][3] for k in BUNDLES[name]["datasets"])


class Progress:
    """Download progress (#15).

    On a terminal, one line rewritten in place, at most twice a second. Anywhere else
    (a log, CI, an AI client running the command), where every rewrite would be a new
    line, a line every 10% or every 30 seconds, whichever comes first.
    """

    TTY_INTERVAL = 0.5
    LOG_STEP_PERCENT = 10
    LOG_INTERVAL = 30.0

    def __init__(self, total: int, start_at: int = 0, tty: bool | None = None, out=None, clock=time.monotonic):
        self.total = total
        self.done = start_at
        self.out = out or sys.stdout
        self.tty = self.out.isatty() if tty is None else tty
        self.clock = clock
        self.last_time = clock()
        self.last_step = self._percent() // self.LOG_STEP_PERCENT

    def _percent(self) -> int:
        return int(self.done * 100 / self.total) if self.total > 0 else 0

    def _line(self) -> str:
        if self.total > 0:
            return f"  {self.done * 100 / self.total:5.1f}%  {_format_size(self.done)} of {_format_size(self.total)}"
        return f"  {_format_size(self.done)} downloaded"

    def update(self, n: int) -> None:
        self.done += n
        now = self.clock()
        if self.tty:
            if now - self.last_time >= self.TTY_INTERVAL:
                self.out.write("\r" + self._line())
                self.out.flush()
                self.last_time = now
            return
        step = self._percent() // self.LOG_STEP_PERCENT
        if step > self.last_step or now - self.last_time >= self.LOG_INTERVAL:
            self.out.write(self._line() + "\n")
            self.out.flush()
            self.last_step = step
            self.last_time = now

    def end(self) -> str:
        """What to print before the result line: clears the live line on a terminal."""
        return "\r" if self.tty else ""


# SQLite files begin with this exact 16-byte string, including the terminating NUL.
SQLITE_MAGIC = b"SQLite format 3\x00"

# Below this, a response is an error page rather than any dataset we publish. The smallest
# dataset is ~1 MB; 64 KiB is comfortably under it and comfortably over a stray HTTP header.
MIN_PLAUSIBLE_BYTES = 64 * 1024


class DownloadNotADatabase(Exception):
    """The server returned something, and it was not the database we asked for."""


def _verify_sqlite(dest: str, filename: str, expected_size: int, headers) -> None:
    """Fail loudly when the download is not the database it claims to be.

    WHY THIS EXISTS. A download that returns the wrong thing used to be reported as success.
    urlretrieve only raises on an HTTP error status, and a hosting provider that has lost a
    file does not necessarily answer with one: on 2026-09-21 every path under the project --
    including paths that had never existed -- returned HTTP 200 with a 74 KB HTML page. So
    urlretrieve completed, the size was read off the HTML, and the user was told:

        OK   wspr_signatures_v2.sqlite (0 MB in 1s, 0.1 MB/s)

    Nine HTML files with .sqlite extensions, and a success message. The failure only surfaced
    later, somewhere unrelated, as a corrupt-database error. Before that day the same URLs
    returned 404 and the tool failed honestly -- so the user-visible behaviour got worse
    without a line of code changing, which is exactly the kind of regression a downloader
    cannot detect by trusting its transport.

    Three checks, cheapest first. Each is sufficient alone; together they are hard to fool by
    accident:

      content type   an HTML body is never a database, whatever the status line said
      magic bytes    the authoritative test -- a real SQLite file starts with SQLITE_MAGIC
      size           a 74 KB answer to a 9 GB request is wrong even if it were a database

    The size check warns rather than fails, deliberately. Published files legitimately change
    size between releases, and refusing a download because a dataset grew would be a worse
    bug than the one this guards against.
    """
    ctype = (headers.get("Content-Type") or "").split(";")[0].strip().lower()
    if ctype in ("text/html", "application/xhtml+xml"):
        raise DownloadNotADatabase(
            f"server returned {ctype}, not a database -- the file is probably missing or moved. "
            f"Check {SF_BASE} in a browser."
        )

    actual = os.path.getsize(dest)
    if actual < MIN_PLAUSIBLE_BYTES:
        raise DownloadNotADatabase(
            f"got {actual:,} bytes for a ~{_format_size(expected_size)} dataset -- almost certainly an "
            f"error page rather than {filename}"
        )

    with open(dest, "rb") as fh:
        magic = fh.read(len(SQLITE_MAGIC))
    if magic != SQLITE_MAGIC:
        raise DownloadNotADatabase(
            f"not a SQLite database (starts with {magic[:16]!r}) -- the download completed but "
            f"returned something else"
        )

    # Informational only: never fail a download for being a different size than a number
    # compiled in months ago.
    if expected_size and actual < expected_size * 0.5:
        print(
            f"  WARN {filename} is {_format_size(actual)}, expected ~{_format_size(expected_size)}",
        )


# Resume and retry (#14). The big files (WSPR 9 GB, RBN 6 GB) come from SourceForge's
# mirrors; a dropped connection used to throw the partial file away and start from zero.
RETRIES = 5            # attempts per file
BACKOFF_SECONDS = 2.0  # doubled after each failed attempt
TIMEOUT_SECONDS = 60
CHUNK = 1024 * 1024


class TransientError(Exception):
    """A failure worth retrying: a timeout, a dropped connection, a 5xx."""


def _range_total(content_range: str | None) -> int:
    """The total size from a Content-Range header ("bytes 0-99/1234"), or 0 if unknown."""
    total = (content_range or "").rsplit("/", 1)[-1].strip()
    return int(total) if total.isdigit() else 0


def _open(req: urllib.request.Request):
    """Open a request (tests replace this)."""
    return urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS)


def _fetch_into(url: str, part: str, expected_size: int):
    """Fetch url into part, resuming from what part already holds. Returns the response
    headers once part holds the whole file; raises TransientError to retry."""
    have = os.path.getsize(part) if os.path.exists(part) else 0
    req = urllib.request.Request(url)
    if have:
        req.add_header("Range", f"bytes={have}-")
    try:
        resp = _open(req)
    except urllib.error.HTTPError as e:
        if e.code == 416 and have:
            if _range_total(e.headers.get("Content-Range")) == have:
                return {}  # already whole (stopped before it was checked and moved): check it
            os.remove(part)  # larger than the file: no good
            raise TransientError("the partial file didn't match the server's; starting again") from e
        if e.code >= 500:
            raise TransientError(f"HTTP {e.code}") from e
        raise
    except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException) as e:
        raise TransientError(str(e)) from e

    with resp:
        if not resp.geturl().startswith("https://"):
            raise DownloadNotADatabase(f"redirected away from HTTPS ({resp.geturl().split('?')[0]})")
        headers = resp.headers
        if have and resp.status == 206:
            total = _range_total(headers.get("Content-Range"))
            mode = "ab"
            print(f"  resuming at {_format_size(have)}")
        else:
            have = 0  # no Range asked for, or the server sent the whole file
            total = int(headers.get("Content-Length") or 0)
            mode = "wb"
        progress = Progress(total or expected_size, start_at=have)
        with open(part, mode) as fh:
            while True:
                try:
                    chunk = resp.read(CHUNK)
                except (OSError, http.client.HTTPException) as e:  # the connection, not the disk
                    sys.stdout.write(progress.end())
                    raise TransientError(str(e) or type(e).__name__) from e
                if not chunk:
                    break
                fh.write(chunk)
                progress.update(len(chunk))
        sys.stdout.write(progress.end())

    got = os.path.getsize(part)
    if total and got < total:
        raise TransientError(f"connection closed at {_format_size(got)} of {_format_size(total)}")
    return headers


def download_dataset(key: str, data_dir: str, force: bool = False, sleep=time.sleep) -> bool:
    """Download a single dataset. Returns True on success."""
    dest = _dest_path(data_dir, key)
    part = dest + ".part"
    _, filename, desc, size = DATASETS[key]

    if force:
        for f in (dest, part):
            if os.path.exists(f):
                os.remove(f)
    if os.path.exists(dest):
        print(f"  SKIP {filename} ({_format_size(os.path.getsize(dest))} exists, use --force to re-download)")
        return True

    # Create directory structure
    os.makedirs(os.path.dirname(dest), exist_ok=True)

    url = _download_url(key)
    print(f"  GET  {filename} ({_format_size(size)})")

    start = time.time()
    wait = BACKOFF_SECONDS
    for attempt in range(1, RETRIES + 1):
        try:
            headers = _fetch_into(url, part, size)
            _verify_sqlite(part, filename, size, headers)
            os.replace(part, dest)
            elapsed = time.time() - start
            got = os.path.getsize(dest)
            speed = got / 1e6 / elapsed if elapsed > 0 else 0
            print(f"  OK   {filename} ({_format_size(got)} in {elapsed:.0f}s, {speed:.1f} MB/s)")
            return True
        except TransientError as e:
            if attempt == RETRIES:
                kept = os.path.getsize(part) if os.path.exists(part) else 0
                note = f"; {_format_size(kept)} kept, run the same command again to resume" if kept else ""
                print(f"  FAIL {filename}: {e} (after {RETRIES} attempts{note})")
                return False
            print(f"  RETRY {filename}: {e} (attempt {attempt + 1} of {RETRIES} in {wait:.0f}s)")
            sleep(wait)
            wait *= 2
        except Exception as e:
            # Not the file we asked for, or a permanent HTTP error: nothing worth resuming.
            print(f"  FAIL {filename}: {e}")
            if os.path.exists(part):
                os.remove(part)
            return False
    return False


def list_available():
    """Print available datasets and bundles."""
    print("Available datasets:\n")
    total = 0
    for key, (_, filename, desc, size) in DATASETS.items():
        total += size
        print(f"  {key:12s}  {_format_size(size):>8s}  {desc}")

    print(f"\n  {'TOTAL':12s}  {_format_size(total):>8s}")

    print("\nPreset bundles:\n")
    for name, bundle in BUNDLES.items():
        ds_list = ", ".join(bundle["datasets"])
        print(f"  {name:12s}  {_format_size(_bundle_size(name)):>8s}  {bundle['description']}")
        print(f"  {'':12s}           [{ds_list}]")

    print(f"\nDefault data directory: {default_data_dir()}")

    print("\nSizes are in MB and GB (1 MB = 1,000,000 bytes).")
    print("\nExamples:")
    print("  ionis-download --bundle minimal")
    print("  ionis-download --bundle full")
    print("  ionis-download --bundle minimal /custom/path")
    print("  ionis-download --datasets wspr,rbn,grids,solar")
    print("  ionis-download --list")


def main():
    default_dir = default_data_dir()

    parser = argparse.ArgumentParser(
        description="Download IONIS datasets from SourceForge",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  ionis-download --bundle minimal             # download to default location\n"
            "  ionis-download --bundle recommended          # contest + pskr + solar\n"
            f"  ionis-download --bundle full                 # all 9 datasets ({_format_size(_bundle_size('full'))})\n"
            "  ionis-download --bundle minimal /custom/path # custom location\n"
            "  ionis-download --datasets wspr,grids,solar   # pick individual datasets\n"
            "  ionis-download --list                        # show available datasets\n"
            f"\nDefault data directory: {default_dir}\n"
        ),
    )
    parser.add_argument(
        "data_dir",
        nargs="?",
        default=default_dir,
        help=f"Destination directory (default: {default_dir})",
    )
    parser.add_argument(
        "--bundle",
        choices=list(BUNDLES.keys()),
        help="Download a preset bundle: " + ", ".join(
            f"{n} ({_format_size(_bundle_size(n))})" for n in BUNDLES
        ),
    )
    parser.add_argument(
        "--datasets",
        help="Comma-separated list of datasets to download (e.g., wspr,rbn,grids,solar)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available datasets and bundles",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download files even if they already exist",
    )
    args = parser.parse_args()

    if args.list:
        list_available()
        return

    if not args.bundle and not args.datasets:
        parser.error("specify --bundle or --datasets (use --list to see options)")

    # Resolve dataset list
    if args.bundle:
        keys = BUNDLES[args.bundle]["datasets"]
        print(f"Bundle: {args.bundle} ({BUNDLES[args.bundle]['description']})")
        print(f"Datasets: {', '.join(keys)} ({_format_size(_bundle_size(args.bundle))})")
    else:
        keys = [k.strip() for k in args.datasets.split(",")]
        invalid = [k for k in keys if k not in DATASETS]
        if invalid:
            print(f"Unknown datasets: {', '.join(invalid)}")
            print(f"Valid options: {', '.join(DATASETS.keys())}")
            sys.exit(1)

    data_dir = os.path.abspath(args.data_dir)
    print(f"Destination: {data_dir}\n")

    # Download
    ok = 0
    fail = 0
    try:
        for key in keys:
            if download_dataset(key, data_dir, force=args.force):
                ok += 1
            else:
                fail += 1
    except KeyboardInterrupt:
        print("\n\nStopped. Run the same command again to resume where it left off.")
        sys.exit(130)

    print(f"\nDone: {ok} downloaded, {fail} failed")
    if fail > 0:
        sys.exit(1)

    # Print next steps
    if data_dir == os.path.abspath(default_dir):
        print("\nNext steps:")
        print("  ionis-mcp  # start the MCP server (uses default data directory)")
    else:
        print("\nNext steps:")
        print(f"  export IONIS_DATA_DIR={data_dir}")
        print("  ionis-mcp  # start the MCP server")


if __name__ == "__main__":
    main()
