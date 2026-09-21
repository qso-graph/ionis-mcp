"""ionis-download — Download IONIS datasets from SourceForge.

User-friendly CLI for downloading SQLite datasets used by ionis-mcp.
Supports preset bundles (minimal, recommended, full) or individual datasets.
Downloads to the platform default directory unless overridden.
"""

import argparse
import os
import sys
import time
import urllib.request

from . import default_data_dir

SF_BASE = "https://sourceforge.net/projects/ionis-ai/files/v1.0"

# Dataset registry: key → (relative path, filename, description, size_mb)
DATASETS = {
    # Propagation signatures
    "wspr": (
        "propagation/wspr-signatures",
        "wspr_signatures_v2.sqlite",
        "WSPR beacon signatures (93.6M rows, 2008-2026)",
        8639,
    ),
    "rbn": (
        "propagation/rbn-signatures",
        "rbn_signatures.sqlite",
        "RBN CW/RTTY signatures (67.3M rows, 2009-2026)",
        5753,
    ),
    "contest": (
        "propagation/contest-signatures",
        "contest_signatures.sqlite",
        "CQ contest signatures (5.7M rows, 2005-2025)",
        424,
    ),
    "dxpedition": (
        "propagation/dxpedition-signatures",
        "dxpedition_signatures.sqlite",
        "DXpedition rare-grid signatures (260K rows)",
        22,
    ),
    "pskr": (
        "propagation/pskr-signatures",
        "pskr_signatures.sqlite",
        "PSK Reporter FT8/WSPR signatures (8.4M rows, Feb 2026+)",
        606,
    ),
    # Solar
    "solar": (
        "solar/solar-indices",
        "solar_indices.sqlite",
        "Solar indices — SFI, SSN, Kp, Ap (76.7K rows, 2000-2026)",
        8,
    ),
    "dscovr": (
        "solar/dscovr",
        "dscovr_l1.sqlite",
        "DSCOVR L1 solar wind — Bz, speed, density (23K rows)",
        3,
    ),
    # Tools
    "grids": (
        "tools/grid-lookup",
        "grid_lookup.sqlite",
        "Maidenhead grid coordinates (31.7K grids)",
        2,
    ),
    "balloons": (
        "tools/balloon-callsigns",
        "balloon_callsigns_v2.sqlite",
        "Known balloon/telemetry callsigns (1.5K entries)",
        1,
    ),
}

# Preset bundles
BUNDLES = {
    "minimal": {
        "description": "Basic propagation queries (~430 MB)",
        "datasets": ["contest", "grids", "solar"],
    },
    "recommended": {
        "description": "Contest + PSKR + solar + tools (~1.1 GB)",
        "datasets": ["contest", "pskr", "grids", "solar", "dscovr", "balloons"],
    },
    "full": {
        "description": "All 9 datasets (~15 GB)",
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


def _format_size(mb: int) -> str:
    """Format size in MB to human-readable string."""
    if mb >= 1024:
        return f"{mb / 1024:.1f} GB"
    return f"{mb} MB"


def _progress_hook(block_num, block_size, total_size):
    """Print download progress."""
    if total_size > 0:
        downloaded = block_num * block_size
        percent = min(100, downloaded * 100 / total_size)
        mb_done = downloaded / (1024 * 1024)
        mb_total = total_size / (1024 * 1024)
        sys.stdout.write(f"\r  {percent:5.1f}%  {mb_done:,.0f} / {mb_total:,.0f} MB")
        sys.stdout.flush()
    else:
        mb_done = block_num * block_size / (1024 * 1024)
        sys.stdout.write(f"\r  {mb_done:,.0f} MB downloaded")
        sys.stdout.flush()


# SQLite files begin with this exact 16-byte string, including the terminating NUL.
SQLITE_MAGIC = b"SQLite format 3\x00"

# Below this, a response is an error page rather than any dataset we publish. The smallest
# dataset is ~1 MB; 64 KiB is comfortably under it and comfortably over a stray HTTP header.
MIN_PLAUSIBLE_BYTES = 64 * 1024


class DownloadNotADatabase(Exception):
    """The server returned something, and it was not the database we asked for."""


def _verify_sqlite(dest: str, filename: str, expected_mb: int, headers) -> None:
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
            f"got {actual:,} bytes for a ~{expected_mb:,} MB dataset -- almost certainly an "
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
    if expected_mb and actual < (expected_mb * 1024 * 1024) * 0.5:
        print(
            f"\r  WARN {filename} is {actual / 1048576:,.0f} MB, expected ~{expected_mb:,} MB",
        )


def download_dataset(key: str, data_dir: str, force: bool = False) -> bool:
    """Download a single dataset. Returns True on success."""
    dest = _dest_path(data_dir, key)
    _, filename, desc, size_mb = DATASETS[key]

    if os.path.exists(dest) and not force:
        existing_mb = os.path.getsize(dest) / (1024 * 1024)
        print(f"  SKIP {filename} ({existing_mb:,.0f} MB exists, use --force to re-download)")
        return True

    # Create directory structure
    os.makedirs(os.path.dirname(dest), exist_ok=True)

    url = _download_url(key)
    print(f"  GET  {filename} (~{_format_size(size_mb)})")

    start = time.time()
    try:
        _, headers = urllib.request.urlretrieve(url, dest, reporthook=_progress_hook)
        elapsed = time.time() - start
        _verify_sqlite(dest, filename, size_mb, headers)
        actual_mb = os.path.getsize(dest) / (1024 * 1024)
        speed = actual_mb / elapsed if elapsed > 0 else 0
        print(f"\r  OK   {filename} ({actual_mb:,.0f} MB in {elapsed:.0f}s, {speed:.1f} MB/s)")
        return True
    except Exception as e:
        print(f"\r  FAIL {filename}: {e}")
        # Clean up partial download
        if os.path.exists(dest):
            os.remove(dest)
        return False


def list_available():
    """Print available datasets and bundles."""
    print("Available datasets:\n")
    total_mb = 0
    for key, (_, filename, desc, size_mb) in DATASETS.items():
        total_mb += size_mb
        print(f"  {key:12s}  {_format_size(size_mb):>8s}  {desc}")

    print(f"\n  {'TOTAL':12s}  {_format_size(total_mb):>8s}")

    print("\nPreset bundles:\n")
    for name, bundle in BUNDLES.items():
        bundle_mb = sum(DATASETS[k][3] for k in bundle["datasets"])
        ds_list = ", ".join(bundle["datasets"])
        print(f"  {name:12s}  {_format_size(bundle_mb):>8s}  {bundle['description']}")
        print(f"  {'':12s}           [{ds_list}]")

    print(f"\nDefault data directory: {default_data_dir()}")

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
            "  ionis-download --bundle full                 # all 9 datasets (~15 GB)\n"
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
        help="Download a preset bundle: minimal (~430 MB), recommended (~1.1 GB), or full (~15 GB)",
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
        bundle_mb = sum(DATASETS[k][3] for k in keys)
        print(f"Bundle: {args.bundle} ({BUNDLES[args.bundle]['description']})")
        print(f"Datasets: {', '.join(keys)} (~{_format_size(bundle_mb)})")
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
    for key in keys:
        if download_dataset(key, data_dir, force=args.force):
            ok += 1
        else:
            fail += 1

    print(f"\nDone: {ok} downloaded, {fail} failed")
    if fail > 0:
        sys.exit(1)

    # Print next steps
    if data_dir == os.path.abspath(default_dir):
        print(f"\nNext steps:")
        print(f"  ionis-mcp  # start the MCP server (uses default data directory)")
    else:
        print(f"\nNext steps:")
        print(f"  export IONIS_DATA_DIR={data_dir}")
        print(f"  ionis-mcp  # start the MCP server")


if __name__ == "__main__":
    main()
