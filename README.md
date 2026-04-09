# Clinical Trial Intelligence MCP

Python MCP server for clinical trial and publication intelligence, built for the BioNTech Hackathon.

The project follows an LLM-first design:
- MCP tools return structured, minimal data
- source adapters handle HTTP, parsing, and normalization
- the LLM performs synthesis, reasoning, and interpretation

## Status

The server currently includes:
- ClinicalTrials.gov source scaffolding
- PubMed source with `esearch -> efetch` integration
- MCP tools for trial search, trial details, timelines, and publications
- local PubMed tests using `pytest` and `httpx.MockTransport`

## Architecture

Current layout:

```text
src/Medical_Wizard_MCP/
├── __main__.py
├── server.py
├── models/
│   └── trials.py
├── sources/
│   ├── base.py
│   ├── registry.py
│   ├── clinicaltrials.py
│   └── pubmed.py
└── tools/
    ├── __init__.py
    ├── search.py
    ├── timelines.py
    └── publications.py

tests/
├── conftest.py
└── test_pubmed.py
```

Runtime flow:

```text
User question
  -> MCP tool
  -> SourceRegistry
  -> one or more source adapters
  -> normalized Pydantic models
  -> LLM synthesis
```

## Available Tools

### `search_trials`
Search clinical trials by condition and optional filters.

Parameters:
- `condition`
- `phase`
- `status`
- `sponsor`
- `intervention`
- `max_results`

### `get_trial_details`
Return detailed data for a single ClinicalTrials.gov study.

Parameters:
- `nct_id`

### `get_trial_timelines`
Return start, completion, and enrollment timeline data.

Parameters:
- `condition`
- `sponsor`
- `max_results`

### `search_publications`
Search PubMed publications related to a disease area, intervention, or trial topic.

Parameters:
- `query`
- `max_results`
- `year_from`

Returns:
- `pmid`
- `title`
- `authors`
- `journal`
- `pub_date`
- `abstract`
- `source`

## PubMed Integration

PubMed uses the NCBI E-utilities API:

- Base URL: `https://eutils.ncbi.nlm.nih.gov/entrez/eutils`
- Step 1: `esearch.fcgi` returns PMIDs as JSON
- Step 2: `efetch.fcgi` returns publication details as XML
- default rate limit without API key: 3 requests/second
- current implementation waits `0.4s` between `esearch` and `efetch`

Supported publication filters:
- `query`
- `max_results`
- `year_from`

Optional environment variables:

```bash
PUBMED_API_KEY=
PUBMED_EMAIL=
```

## Models

Shared response models live in:
- `src/Medical_Wizard_MCP/models/trials.py`

Current publication model fields:
- `source`
- `pmid`
- `title`
- `authors`
- `journal`
- `pub_date`
- `abstract`

## Local Development

Requirements:
- Python 3.11+
- `uv` recommended

Install:

```bash
uv pip install -e ".[dev]"
```

If `uv` is not installed:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

Run the server:

```bash
python -m Medical_Wizard_MCP
```

Server endpoint:

```text
http://localhost:8000/mcp
```

## Testing

Run the PubMed test suite:

```bash
uv run pytest tests/test_pubmed.py
```

Without `uv`:

```bash
python -m pytest tests/test_pubmed.py
```

Run all tests:

```bash
uv run pytest
```

Without `uv`:

```bash
python -m pytest
```

What the PubMed tests currently cover:
- successful `esearch -> efetch` flow
- `year_from` handling
- XML normalization for authors, journal, date, and abstract
- empty search results
- HTTP failure handling
- invalid XML handling

Run the live PubMed smoke test and print the normalized output:

```bash
RUN_LIVE_PUBMED=1 python -m pytest tests/test_pubmed_live.py -s
```

Optional live-test parameters:

```bash
RUN_LIVE_PUBMED=1 \
PUBMED_LIVE_QUERY="personalized cancer vaccine melanoma" \
PUBMED_LIVE_MAX_RESULTS=5 \
PUBMED_LIVE_YEAR_FROM=2023 \
python -m pytest tests/test_pubmed_live.py -s
```

## Contributor Guidelines

When adding a new source:
- extend `BaseSource` in `sources/base.py`
- implement only the methods the source actually supports
- keep analytics and interpretation out of the source layer
- normalize responses into shared Pydantic models
- register the source in `__main__.py`
- expose new functionality through thin MCP tools only when needed

Design principles:
- prefer small, composable tools
- minimize response payloads
- include `source` metadata in returned models
- keep HTTP concerns in `sources/`
- keep orchestration out of the MCP server
