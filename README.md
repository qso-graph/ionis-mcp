<!-- mcp-name: io.github.qso-graph/ionis-mcp -->
# ionis-mcp

A [Model Context Protocol](https://modelcontextprotocol.io) (MCP) server for HF radio propagation analytics, built on the [IONIS](https://ionis-ai.com/) dataset collection — 175M+ aggregated signatures derived from 14 billion WSPR, RBN, Contest, DXpedition, and PSK Reporter observations spanning 2005-2026.

## Overview

IONIS (Ionospheric Neural Inference System) is an open-source machine learning system for predicting HF (shortwave) radio propagation. The datasets — curated from the world's largest amateur radio telemetry networks — are distributed as SQLite files on [SourceForge](https://sourceforge.net/projects/ionis-ai/).

**ionis-mcp** bridges those datasets to AI assistants via the Model Context Protocol. Install the package, download data, and Claude (Desktop or Code) can answer propagation questions using 11 specialized tools — no SQL required.

**Example questions:**
- "When is 20m open from Idaho to Europe?"
- "How does solar flux affect 15m propagation?"
- "Show me 10m paths at 03z where both stations are in the dark"
- "Compare WSPR and RBN observations on 20m FN31 to JO51"
- "What are the current band conditions? I'm heading out for POTA."
- "What were the solar conditions during the February 2026 geomagnetic storm?"

## Datasets

| Source | Signatures | Raw Observations | SNR Type | Years |
|--------|-----------|-----------------|----------|-------|
| [WSPR](https://www.wsprnet.org/) | 93.6M | 10.9B beacon spots | Measured (-30 to +20 dB) | 2008-2026 |
| [RBN](https://reversebeacon.net/) | 67.3M | 2.3B CW/RTTY spots | Measured (8-29 dB) | 2009-2026 |
| [CQ Contests](https://cqww.com/) | 5.7M | 234M SSB/RTTY QSOs | Anchored (+10/0 dB) | 2005-2025 |
| [DXpeditions](https://www.ng3k.com/misc/adxo.html) | 260K | 3.9M rare-grid paths | Measured | 2009-2025 |
| [PSK Reporter](https://pskreporter.info/) | 8.4M | 514M+ FT8/WSPR spots | Measured (-34 to +38 dB) | Feb 2026+ |
| Solar Indices | — | 77K daily/3-hour records | SFI, SSN, Kp, Ap | 2000-2026 |
| DSCOVR L1 | — | 23K solar wind samples | Bz, speed, density | Feb 2026+ |

All signature tables share an identical 13-column schema (tx\_grid, rx\_grid, band, hour, month, median\_snr, spot\_count, snr\_std, reliability, avg\_sfi, avg\_kp, avg\_distance, avg\_azimuth) — ready for cross-source analysis.

## Quick Start

```bash
# 1. Install
pip install ionis-mcp

# 2. Download datasets (to default location: ~/.ionis-mcp/data/)
ionis-download --bundle minimal          # ~430 MB — contest + solar + grids
ionis-download --bundle recommended      # ~1.1 GB — adds PSKR + DSCOVR
ionis-download --bundle full             # ~15 GB  — all 9 datasets

# 3. Configure Claude (see below) and restart — tools appear automatically
```

That's it. Both `ionis-download` and `ionis-mcp` use the same default data directory. No environment variables needed.

### Default Data Directory

| Platform | Location |
|----------|----------|
| Linux / macOS | `~/.ionis-mcp/data/` |
| Windows | `%LOCALAPPDATA%\ionis-mcp\data\` |

Override with a custom path:

```bash
# Download to custom location
ionis-download --bundle minimal /path/to/my/data

# Tell the server where to find it
ionis-mcp --data-dir /path/to/my/data
# or
export IONIS_DATA_DIR=/path/to/my/data
```

### Download Individual Datasets

```bash
# Pick specific datasets
ionis-download --datasets wspr,rbn,grids,solar

# See all available datasets and bundles
ionis-download --list

# Re-download (overwrite existing)
ionis-download --bundle minimal --force
```

## Configure Your MCP Client

ionis-mcp works with any MCP-compatible client. Add the server config and restart — tools appear automatically.

If you downloaded data to a custom location, add `"env": { "IONIS_DATA_DIR": "/path/to/data" }` to any config below.

### Claude Desktop

Add to `claude_desktop_config.json` (`~/Library/Application Support/Claude/` on macOS, `%APPDATA%\Claude\` on Windows):

```json
{
  "mcpServers": {
    "ionis": {
      "command": "ionis-mcp"
    }
  }
}
```

### Claude Code

Add to `.claude/settings.json`:

```json
{
  "mcpServers": {
    "ionis": {
      "command": "ionis-mcp"
    }
  }
}
```

### ChatGPT Desktop

ChatGPT supports MCP via the [OpenAI Agents SDK](https://developers.openai.com/api/docs/mcp/). Add under Settings > Apps & Connectors, or configure in your agent definition:

```json
{
  "mcpServers": {
    "ionis": {
      "command": "ionis-mcp"
    }
  }
}
```

### Cursor

Add to `.cursor/mcp.json` (project-level) or `~/.cursor/mcp.json` (global):

```json
{
  "mcpServers": {
    "ionis": {
      "command": "ionis-mcp"
    }
  }
}
```

### VS Code / GitHub Copilot

Add to `.vscode/mcp.json` in your workspace:

```json
{
  "servers": {
    "ionis": {
      "command": "ionis-mcp"
    }
  }
}
```

### Gemini CLI

Add to `~/.gemini/settings.json` (global) or `.gemini/settings.json` (project):

```json
{
  "mcpServers": {
    "ionis": {
      "command": "ionis-mcp"
    }
  }
}
```

## Tools

| Tool | Purpose |
|------|---------|
| `list_datasets` | Show available datasets with row counts and file sizes |
| `query_signatures` | Flexible signature lookup — filter by source, band, grid, hour, month |
| `band_openings` | Hour-by-hour propagation profile for a path on a specific band |
| `path_analysis` | Complete path analysis across all bands, hours, months, and sources |
| `solar_correlation` | SFI effect on propagation — grouped by solar flux bracket |
| `grid_info` | Maidenhead grid decode with solar elevation computation |
| `compare_sources` | Cross-dataset comparison (WSPR vs RBN vs Contest vs PSKR) |
| `dark_hour_analysis` | Classify paths by solar geometry — both-day, cross-terminator, both-dark |
| `solar_history` | Historical solar indices for any date range |
| `band_summary` | Band overview — hour distribution, top grid pairs, distance range |
| `current_conditions` | Live propagation forecast — SFI, Kp, solar wind, band outlook, POTA/SOTA tips |
| `get_version_info` | Service version + upstream dataset version (fleet identity attestation) |

## Data Directory Layout

```
~/.ionis-mcp/data/                  (or $IONIS_DATA_DIR)
├── propagation/
│   ├── wspr-signatures/wspr_signatures_v2.sqlite      (8.4 GB, 93.6M rows)
│   ├── rbn-signatures/rbn_signatures.sqlite            (5.6 GB, 67.3M rows)
│   ├── contest-signatures/contest_signatures.sqlite    (424 MB, 5.7M rows)
│   ├── dxpedition-signatures/dxpedition_signatures.sqlite (22 MB, 260K rows)
│   └── pskr-signatures/pskr_signatures.sqlite          (606 MB, 8.4M rows)
├── solar/
│   ├── solar-indices/solar_indices.sqlite               (7.7 MB, 76.7K rows)
│   └── dscovr/dscovr_l1.sqlite                         (2.9 MB, 23K rows)
└── tools/
    ├── grid-lookup/grid_lookup.sqlite                   (1.1 MB, 31.7K rows)
    └── balloon-callsigns/balloon_callsigns_v2.sqlite    (116 KB, 1.5K rows)
```

The server works with whatever datasets are present. Missing datasets degrade gracefully — tools that need unavailable data return clear messages instead of errors.

## Architecture

- **Transport**: stdio (Claude Desktop / Claude Code) or streamable-http (MCP Inspector)
- **Database**: Read-only `sqlite3` connections (`?mode=ro`) — no writes, ever
- **Query safety**: All queries use parameterized SQL (`?` placeholders), result limits enforced server-side (max 1000 rows)
- **Grid lookup**: 31.7K Maidenhead grids loaded into memory at startup (~2 MB) for instant lat/lon resolution
- **Solar geometry**: Pure Python solar elevation computation (same algorithm as the IONIS training pipeline) — classifies endpoints as day/twilight/night for propagation context
- **Cross-source queries**: Each SQLite database opened separately, results merged in Python with source labels

## Testing with MCP Inspector

```bash
ionis-mcp --transport streamable-http --port 8000
# Open http://localhost:8000/mcp in browser
```

## Related Projects

| Repository | Purpose |
|-----------|---------|
| [ionis-validate](https://pypi.org/project/ionis-validate/) | IONIS model validation suite (PyPI) |
| [IONIS Datasets](https://sourceforge.net/projects/ionis-ai/) | Distributed dataset files (SourceForge) |

## License

GPL-3.0-or-later

## Citation

If you use the IONIS datasets in research, please cite:

> Beam, G. (KI7MT). *IONIS: Ionospheric Neural Inference System — HF Propagation Prediction Datasets.* SourceForge, 2026. https://sourceforge.net/projects/ionis-ai/
