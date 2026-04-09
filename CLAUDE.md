# Clinical Trial Intelligence MCP Server

## What This Is

A Python MCP (Model Context Protocol) server that provides clinical trial intelligence tools for AI assistants. Built for the BioNTech Hackathon.

**Architecture: LLM-First** — The server exposes atomic, well-filtered data tools. The LLM (Claude) handles all orchestration, analysis, and synthesis. No analytics logic lives in the server.

## How It Works

```
User Question → LLM decides which tools to call → MCP Tools → SourceRegistry → [Source1, Source2, ...] → merge → unified response → LLM synthesizes answer
```

The MCP server runs over **streamable HTTP** and integrates with LibreChat.

## Project Structure

```
src/clinical_trials_mcp/
├── __main__.py              # Entry point — registers sources, starts server
├── server.py                # Shared FastMCP instance (all tools register here)
│
├── models/                  # Pydantic data models
│   └── trials.py            # TrialSummary, TrialDetail, TrialTimeline, Publication
│
├── sources/                 # Data source abstraction layer
│   ├── base.py              # BaseSource ABC — default no-op methods
│   ├── registry.py          # SourceRegistry — fans out to sources, merges results
│   ├── clinicaltrials.py    # ClinicalTrials.gov API v2
│   └── pubmed.py            # PubMed E-utilities
│
└── tools/                   # MCP tool definitions (thin wrappers calling registry)
    ├── __init__.py           # Imports all tool modules → triggers registration
    ├── search.py             # search_trials, get_trial_details
    ├── timelines.py          # get_trial_timelines
    └── publications.py       # search_publications
```

## Key Architecture Patterns

### Source Abstraction
- `BaseSource` (ABC) defines methods: `search_trials`, `get_trial_details`, `get_trial_timelines`, `search_publications`
- Each method has a **default no-op** (returns `[]` or `None`) — sources only override what they support
- `SourceRegistry` fans out calls to all registered sources and merges results
- **Adding a new source** = implement `BaseSource` + register in `__main__.py`. Zero tool changes.

### Tool Registration
- `server.py` creates a single `FastMCP` instance
- Tool files import `mcp` from `server.py` and use `@mcp.tool()` decorators
- `tools/__init__.py` imports all tool modules → decorators fire at import time
- `__main__.py` imports `tools` package → all tools registered before `mcp.run()`

### Response Minimization
- Sources extract only needed fields from raw API responses
- Models have a `source` field for citation/transparency
- `max_results` caps prevent context window overflow

## Available Tools

| Tool | Purpose | Key Params |
|------|---------|------------|
| `search_trials` | Find trials by condition/phase/status/sponsor | `condition`, `phase`, `status`, `sponsor`, `intervention` |
| `get_trial_details` | Deep-dive into a specific trial | `nct_id` |
| `get_trial_timelines` | Timeline/velocity data for trials | `condition`, `sponsor` |
| `search_publications` | PubMed publication search | `query` |

## Data Sources

| Source | API | Provides |
|--------|-----|----------|
| ClinicalTrials.gov | `https://clinicaltrials.gov/api/v2` | Trial search, details, timelines |
| PubMed | `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/` | Scientific publications |

## Running

```bash
# Install
uv pip install -e "."

# Run server (streamable HTTP on port 8000)
python -m clinical_trials_mcp

# Server endpoint: http://localhost:8000/mcp
```

## Development Commands

```bash
uv pip install -e ".[dev]"   # Install with dev deps
ruff check src/               # Lint
ruff format src/               # Format
pytest                         # Test
```

## Environment Variables (optional)

```
PUBMED_API_KEY=    # Higher PubMed rate limit (10 req/sec vs 3)
PUBMED_EMAIL=      # Required by PubMed API policy
```
