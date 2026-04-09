# Clinical Trial Intelligence MCP – Developer Documentation

## Table of Contents
1. [Project Overview](#project-overview)
2. [Architecture](#architecture)
3. [Setup](#setup)
4. [Data Sources & API Overview](#data-sources--api-overview)
5. [Interface Contract](#interface-contract)
6. [Data Models](#data-models)
7. [How to Build a New API Client](#how-to-build-a-new-api-client)
8. [Error Handling](#error-handling)
9. [MCP Tool Structure](#mcp-tool-structure)
10. [Data Quality & Source Metadata](#data-quality--source-metadata)
11. [Testing](#testing)

---

## Project Overview

This MCP (Model Context Protocol) server gives Claude real-time access to public clinical trial
databases. Instead of manually piecing together data from multiple sources, R&D teams can ask
natural language questions and receive structured, AI-synthesized intelligence.

**Core principle: LLM-First.**
The MCP tools return clean, structured data. Claude performs all analysis, synthesis, and
interpretation. No analytics logic lives in the MCP code.

---

## Architecture

```
LibreChat (BioNTech)
        │
        │  MCP Protocol (stdio)
        ▼
   MCP Server (server.py)
        │  registers all tools
        ▼
   tools/           ← what Claude calls
   ├── trials.py
   ├── timelines.py
   ├── publications.py
   └── design.py    (Stufe 4)
        │
        ▼
   clients/         ← raw API communication only
   ├── clinicaltrials.py
   ├── pubmed.py
   ├── openfda.py
   └── who_ictrp.py
        │
        ▼
   External APIs    ← we do not build these
   ├── ClinicalTrials.gov
   ├── PubMed E-utils
   ├── OpenFDA
   └── WHO ICTRP
```

### The Three-Layer Rule

| Layer | Responsibility | What does NOT belong here |
|-------|---------------|--------------------------|
| `clients/` | Raw HTTP requests, parsing, normalization | Business logic, filtering |
| `tools/` | MCP tool definitions, calling clients, returning structured output | HTTP requests, parsing |
| `server.py` | Registering tools with FastMCP | Any logic whatsoever |

---

## Setup

### Requirements
```bash
python >= 3.11
pip install fastmcp httpx pydantic
```

### Installation
```bash
git clone <repo-url>
cd clinical-trial-mcp
pip install -r requirements.txt
python server.py
```

### LibreChat Configuration (`librechat.yaml`)
```yaml
mcpServers:
  clinical-trial-intelligence:
    command: python
    args:
      - server.py
    type: stdio
```

---

## Data Sources & API Overview

| API | What it contains | Auth | Rate Limit | Format |
|-----|-----------------|------|-----------|--------|
| ClinicalTrials.gov v2 | All registered trials worldwide | None | 10 req/s | JSON |
| PubMed E-utils | Peer-reviewed publications | None (optional key) | 3 req/s | JSON + XML |
| OpenFDA | Approved drugs & adverse events | None | 240 req/min | JSON |
| WHO ICTRP | International trials (EU, China) | None | Best effort | JSON |

### ClinicalTrials.gov
```
Base URL: https://clinicaltrials.gov/api/v2
GET /studies               → search with filters
GET /studies/{nctId}       → single trial by NCT ID
```

### PubMed E-utils (2-step process)
```
Base URL: https://eutils.ncbi.nlm.nih.gov/entrez/eutils
Step 1: GET /esearch.fcgi  → returns list of PMIDs
Step 2: GET /efetch.fcgi   → returns full data for those PMIDs
```

### OpenFDA
```
Base URL: https://api.fda.gov/drug
GET /drugsfda.json         → approved drug applications
```

### WHO ICTRP
```
Base URL: https://trialsearch.who.int/API
GET /trials                → international trial registry
```

---

## Interface Contract

Every client MUST conform to the `DataSourceProtocol`.
We use Python `Protocol` for structural typing – no inheritance required.
If your client has these method signatures, it conforms automatically.

```python
# clients/base.py

from typing import Protocol, runtime_checkable

@runtime_checkable
class DataSourceProtocol(Protocol):

    async def search(
        self,
        query: str,
        **kwargs
    ) -> list[dict]:
        """
        Search the data source with a primary query string.
        Additional source-specific filters passed as kwargs.
        Always returns a list of raw dicts before Pydantic validation.
        Returns empty list [] if nothing found – never raises on empty.
        """
        ...

    async def fetch_by_id(
        self,
        id: str
    ) -> dict:
        """
        Fetch a single record by its source-specific ID.
        NCT ID for ClinicalTrials.gov, PMID for PubMed, etc.
        Raises DataSourceError if not found.
        """
        ...

    async def get_metadata(self) -> dict:
        """
        Returns static metadata about this data source.
        Used to populate _meta in every tool response.
        See: Data Quality & Source Metadata section.
        """
        ...
```

### What kwargs are allowed per client

Each client decides its own kwargs inside `search()`.
Document them clearly in your client file. Example:

```python
# ClinicalTrials client
await ct_client.search(
    query="lung cancer",
    phase="PHASE3",          # CT.gov specific
    status="RECRUITING",     # CT.gov specific
    sponsor="BioNTech",      # CT.gov specific
    max_results=20
)

# PubMed client
await pubmed_client.search(
    query="mRNA vaccine lung cancer",
    year_from=2022,           # PubMed specific
    max_results=20
)
```

---

## Data Models

All clients return data that gets validated against these Pydantic models.
Defined in `models/schemas.py`. Do not create your own models in client files.

```python
# models/schemas.py

from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class Trial(BaseModel):
    # --- Always present ---
    id: str                              # NCT ID, WHO ID, etc.
    title: str
    source: str                          # "clinicaltrials" | "who_ictrp"

    # --- Usually present ---
    status: Optional[str] = None         # RECRUITING, COMPLETED, TERMINATED, ...
    phase: Optional[str] = None          # PHASE1, PHASE2, PHASE3, PHASE4
    sponsor: Optional[str] = None
    condition: Optional[str] = None      # e.g. "Non-Small Cell Lung Cancer"
    intervention: Optional[str] = None   # e.g. "mRNA Vaccine + PD-1 Inhibitor"
    start_date: Optional[str] = None
    completion_date: Optional[str] = None
    enrollment: Optional[int] = None     # planned patient count

    # --- Sometimes present ---
    primary_endpoint: Optional[str] = None
    biomarkers: Optional[list[str]] = None
    why_stopped: Optional[str] = None    # only for TERMINATED trials – CT.gov only
    country: Optional[str] = None        # WHO ICTRP only


class Publication(BaseModel):
    # --- Always present ---
    pmid: str
    title: str
    source: str                          # "pubmed"

    # --- Usually present ---
    abstract: Optional[str] = None
    journal: Optional[str] = None
    year: Optional[str] = None
    authors: list[str] = []

    # --- Sometimes present ---
    doi: Optional[str] = None
    mesh_terms: Optional[list[str]] = None   # structured MeSH keywords from PubMed


class ApprovedDrug(BaseModel):
    # --- Always present ---
    brand_name: str
    generic_name: str
    source: str                          # "openfda"

    # --- Usually present ---
    indication: Optional[str] = None
    approval_date: Optional[str] = None
    sponsor: Optional[str] = None
    application_number: Optional[str] = None
```

### The `source` field is mandatory

Every model has a `source` field. This tells Claude exactly where the data came from
so it can reason about data quality, coverage gaps, and confidence levels.

```python
# Always set this explicitly in your client
trial = Trial(
    id="NCT04179552",
    title="...",
    source="clinicaltrials",   # ← never omit this
    ...
)
```

---

## How to Build a New API Client

Follow this structure exactly. Every client file looks the same from the outside.

### File structure

```python
# clients/your_source.py

import httpx
import asyncio
from typing import Optional
from models.schemas import Trial  # or Publication, ApprovedDrug
from clients.base import DataSourceError

# ── Constants ────────────────────────────────────────────────────────────────

BASE_URL = "https://your-api.example.com"
SOURCE_NAME = "your_source"          # used in all model.source fields
RATE_LIMIT_DELAY = 0.4               # seconds between requests

# ── Protocol implementation ───────────────────────────────────────────────────

async def search(query: str, **kwargs) -> list[dict]:
    """
    Search your_source for records matching query.

    kwargs:
        max_results (int): Maximum records to return. Default: 20.
        year_from (int): Filter results from this year onwards. Optional.
        [add your source-specific params here]
    """
    max_results = kwargs.get("max_results", 20)

    params = _build_params(query, max_results, **kwargs)

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{BASE_URL}/endpoint", params=params)
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise DataSourceError(
                source=SOURCE_NAME,
                message=f"Search failed: {e.response.status_code}",
                status_code=e.response.status_code
            )

    raw = response.json()
    return _normalize(raw)


async def fetch_by_id(id: str) -> dict:
    """
    Fetch a single record by ID from your_source.
    Raises DataSourceError if not found.
    """
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{BASE_URL}/endpoint/{id}")
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise DataSourceError(
                source=SOURCE_NAME,
                message=f"Record {id} not found",
                status_code=e.response.status_code
            )

    return _normalize_single(response.json())


async def get_metadata() -> dict:
    """
    Static metadata about this source.
    Returned in every tool response under _meta.
    """
    return {
        "source": SOURCE_NAME,
        "base_url": BASE_URL,
        "data_type": "trial_registry",    # or "publication", "drug_approval"
        "quality_note": "Describe what this source covers and what it misses.",
        "coverage": "Describe geographic or temporal coverage.",
        "update_frequency": "Daily / Weekly / Real-time",
        "auth_required": False
    }

# ── Private helpers ───────────────────────────────────────────────────────────

def _build_params(query: str, max_results: int, **kwargs) -> dict:
    """Build the query parameter dict for this API."""
    params = {
        "query": query,
        "pageSize": max_results,
    }
    # add source-specific params from kwargs here
    return params


def _normalize(raw: dict) -> list[dict]:
    """
    Transform raw API response into list of normalized dicts.
    Must match Trial or Publication schema fields.
    Never raises – log and skip malformed records.
    """
    results = []
    for item in raw.get("studies", []):
        try:
            results.append(_normalize_single(item))
        except Exception:
            continue    # skip malformed records silently
    return results


def _normalize_single(item: dict) -> dict:
    """Transform one raw API record into a normalized dict."""
    return {
        "id": item.get("your_id_field"),
        "title": item.get("your_title_field"),
        "source": SOURCE_NAME,
        # map remaining fields to schema fields
        # use None for fields this API does not provide
    }
```

### Checklist before submitting your client

- [ ] `search()` returns `list[dict]` matching the schema
- [ ] `fetch_by_id()` raises `DataSourceError` if not found
- [ ] `get_metadata()` returns complete metadata dict
- [ ] `source` field is set to your `SOURCE_NAME` constant on every record
- [ ] Fields this API does not provide are explicitly set to `None`
- [ ] `DataSourceError` is raised (not raw exceptions) on HTTP failures
- [ ] Rate limit delay is respected (`asyncio.sleep(RATE_LIMIT_DELAY)`)
- [ ] Tested in isolation with the test pattern below

---

## Error Handling

One central exception type. Every client raises this, nothing else.

```python
# clients/base.py

class DataSourceError(Exception):
    """
    Raised by any client when an API call fails.
    Tools catch this and return a structured error to Claude
    so Claude can reason about what went wrong.
    """
    def __init__(
        self,
        source: str,
        message: str,
        status_code: Optional[int] = None
    ):
        self.source = source
        self.message = message
        self.status_code = status_code
        super().__init__(f"[{source}] {message}")
```

### How tools handle DataSourceError

```python
# tools/trials.py

@mcp.tool()
async def search_trials(condition: str, phase: str = None) -> dict:
    try:
        raw = await clinicaltrials.search(condition, phase=phase)
        trials = [Trial(**r) for r in raw]
        return _wrap_response(trials, await clinicaltrials.get_metadata())
    except DataSourceError as e:
        return {
            "error": True,
            "source": e.source,
            "message": e.message,
            "status_code": e.status_code,
            "results": []
        }
```

Claude receives the error dict and can tell the user what went wrong
instead of silently failing.

---

## MCP Tool Structure

Every tool returns the same envelope. This is how Claude always knows
what source the data came from and how to weigh it.

```python
def _wrap_response(results: list, metadata: dict) -> dict:
    return {
        "_meta": metadata,      # from client.get_metadata()
        "count": len(results),
        "results": [r.model_dump() for r in results]
    }
```

### Tool description template

The docstring of every `@mcp.tool()` function is what Claude reads to decide
when to call it. Follow this pattern:

```python
@mcp.tool()
async def search_trials(
    condition: str,
    phase: Optional[str] = None,
    status: Optional[str] = None,
    sponsor: Optional[str] = None,
    max_results: int = 20
) -> dict:
    """
    [ONE LINE: what this tool does]
    Search ClinicalTrials.gov for clinical trials matching the given condition.

    [WHEN TO USE: exact trigger phrases Claude should recognize]
    Use this tool when the user asks about:
    - Active or recruiting trials for a specific cancer type
    - What competitors are running in a given indication
    - How many trials exist for a condition and phase

    [PARAMETERS: what each one means clinically]
    Args:
        condition: Cancer type or disease (e.g. "lung cancer", "NSCLC", "glioblastoma")
        phase: Trial phase – PHASE1, PHASE2, PHASE3, PHASE4. Optional.
        status: Trial status – RECRUITING, COMPLETED, TERMINATED. Optional.
        sponsor: Company or institution name. Optional.
        max_results: Number of results to return. Default 20.

    [OUTPUT: what Claude gets back]
    Returns a list of trials with id, title, sponsor, phase, status, and dates.
    Does NOT return full trial details – use get_trial_details() for that.
    """
```

---

## Data Quality & Source Metadata

This is how Claude understands the limitations of each data source.
Every `get_metadata()` must return these fields:

```python
# Example: ClinicalTrials.gov
{
    "source": "clinicaltrials",
    "data_type": "trial_registry",
    "quality_note": (
        "Sponsor-reported data. Results section only populated for completed "
        "trials that chose to report outcomes. Data is updated daily."
    ),
    "coverage": (
        "US-focused registry. International trials may be missing. "
        "Strongest for Phase 2+ industry-sponsored trials."
    ),
    "update_frequency": "Daily",
    "auth_required": False
}

# Example: PubMed
{
    "source": "pubmed",
    "data_type": "published_research",
    "quality_note": (
        "Peer-reviewed publications only. Significant publication bias: "
        "negative results are underrepresented. Full text not available via API. "
        "Expect 6-18 month lag after trial completion before results appear."
    ),
    "coverage": (
        "Covers most major medical journals. Preprints excluded. "
        "International coverage is strong but abstracts may be English-only."
    ),
    "update_frequency": "Daily",
    "auth_required": False
}

# Example: WHO ICTRP
{
    "source": "who_ictrp",
    "data_type": "trial_registry",
    "quality_note": (
        "Aggregates registries from EU, China, Japan and others. "
        "Data quality varies by contributing registry. "
        "Less structured than ClinicalTrials.gov."
    ),
    "coverage": (
        "Essential for non-US trials. Chinese trials (ChiCTR) largely invisible "
        "on ClinicalTrials.gov but present here."
    ),
    "update_frequency": "Weekly",
    "auth_required": False
}
```

### Why this matters for Claude

With `_meta` attached to every response, Claude can say:

> "I found 3 trials on ClinicalTrials.gov, but this registry is US-focused.
>  Let me also check WHO ICTRP for Chinese and European competitors."

Without `_meta`, Claude has no basis to reason about coverage gaps.

---

## Testing

### Test each client in isolation

```python
# Run from repo root
import asyncio
from clients.pubmed import search, fetch_by_id

async def test_pubmed():
    # Test search
    pmids = await search("mRNA vaccine lung cancer", max_results=3)
    assert isinstance(pmids, list)
    assert len(pmids) <= 3
    print(f"Search OK: {len(pmids)} results")

    # Test fetch
    if pmids:
        paper = await fetch_by_id(pmids[0])
        assert paper.get("source") == "pubmed"
        assert paper.get("title") is not None
        print(f"Fetch OK: {paper['title'][:60]}...")

asyncio.run(test_pubmed())
```

### Test the full tool response envelope

```python
from tools.publications import search_publications

async def test_tool():
    result = await search_publications(term="mRNA vaccine lung cancer")
    assert "_meta" in result
    assert "results" in result
    assert "count" in result
    assert result["_meta"]["source"] == "pubmed"
    print(f"Tool OK: {result['count']} results from {result['_meta']['source']}")

asyncio.run(test_tool())
```

### Before you open a PR

1. Run your client test in isolation
2. Run the tool test end-to-end
3. Confirm `source` field is set on every result
4. Confirm `DataSourceError` is raised on HTTP errors (test with wrong URL)
5. Confirm `get_metadata()` returns all required fields