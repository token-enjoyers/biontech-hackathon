# Clinical Trial Intelligence MCP – Developer Documentation

## Table of Contents
1. [Project Overview](#project-overview)
2. [Architecture](#architecture)
3. [Setup](#setup)
4. [Data Sources & API Overview](#data-sources--api-overview)
5. [The `BaseSource` Contract](#the-basesource-contract)
6. [The `SourceRegistry`](#the-sourceregistry)
7. [Data Models](#data-models)
8. [How to Add a New Data Source](#how-to-add-a-new-data-source)
9. [How to Add a New Tool](#how-to-add-a-new-tool)
10. [Error Handling](#error-handling)
11. [Testing](#testing)

---

## Project Overview

This MCP (Model Context Protocol) server gives Claude real-time access to public clinical
trial databases. Instead of manually piecing together data from multiple sources, R&D teams
can ask natural language questions and receive structured, AI-synthesized intelligence.

**Core principle: LLM-First.**
The MCP tools return clean, structured data. Claude performs all analysis, synthesis, and
interpretation. No analytics logic lives in the server.

```
User question
   │
   ▼
LLM picks tools
   │
   ▼
MCP tool (tools/*.py)
   │
   ▼
SourceRegistry  ── fans out in parallel ──▶  [Source A, Source B, ...]
   │                                              │
   ▼                                              ▼
merged list of Pydantic models          each source hits its own API
   │
   ▼
LLM synthesises answer with citations
```

The server runs over **streamable HTTP** and integrates with LibreChat at BioNTech.

---

## Architecture

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
    ├── __init__.py          # Imports all tool modules → triggers registration
    ├── search.py            # search_trials, get_trial_details
    ├── timelines.py         # get_trial_timelines
    └── publications.py      # search_publications
```

### The Three-Layer Rule

| Layer | Responsibility | What does NOT belong here |
|-------|---------------|--------------------------|
| `sources/` | Raw HTTP requests, parsing, normalization to Pydantic models | Business logic, cross-source merging |
| `tools/` | MCP tool definitions; thin wrappers around `registry` | HTTP requests, parsing, source-specific logic |
| `server.py` / `__main__.py` | FastMCP instance, source registration, transport setup | Any business logic |

**Key invariants:**
- Tools never know which sources exist. They call `registry.<method>()` and get a merged result.
- Sources never know about tools. They implement `BaseSource` and answer questions about their own API.
- Adding a new source = implement `BaseSource` + one line in `__main__.py`. Zero tool changes.

---

## Setup

### Requirements
- Python ≥ 3.11
- [uv](https://github.com/astral-sh/uv) (recommended) or pip

### Installation
```bash
git clone <repo-url>
cd biontech-hackathon
uv pip install -e ".[dev]"
```

### Running
```bash
python -m clinical_trials_mcp
# Server endpoint: http://localhost:8000/mcp
```

### LibreChat Configuration (`librechat.yaml`)
```yaml
mcpServers:
  clinical-trial-intelligence:
    type: streamable-http
    url: http://localhost:8000/mcp
```

### Environment Variables (optional, loaded from `.env`)
```
PUBMED_API_KEY=    # Higher PubMed rate limit (10 req/sec vs 3)
PUBMED_EMAIL=      # Required by PubMed API policy
```

### Development Commands
```bash
ruff check src/      # Lint
ruff format src/     # Format
pytest               # Test
```

---

## Data Sources & API Overview

| Source | API | Auth | Rate Limit | Status |
|-----|-----|------|-----------|--------|
| ClinicalTrials.gov v2 | `https://clinicaltrials.gov/api/v2` | None | 10 req/s | implemented (stub) |
| PubMed E-utils | `https://eutils.ncbi.nlm.nih.gov/entrez/eutils` | Optional API key | 3 req/s (10 with key) | implemented (stub) |

> Both sources are currently scaffolded as `BaseSource` subclasses with `NotImplementedError`
> bodies. The next implementation step is filling in the API calls and response normalization.

### ClinicalTrials.gov
```
GET /studies              → search with filters
GET /studies/{nctId}      → single trial by NCT ID
```

### PubMed E-utils (2-step process)
```
GET /esearch.fcgi         → returns list of PMIDs
GET /efetch.fcgi          → returns full data for those PMIDs
```

### Future candidates (not yet built)
- **OpenFDA** — approved drugs & adverse events
- **WHO ICTRP** — international trial registry (EU, China, Japan)

Each would slot in as another `BaseSource` subclass without any tool changes.

---

## The `BaseSource` Contract

Every data source subclasses `BaseSource` (`sources/base.py`). It is an ABC with two
abstract methods (lifecycle) and four concrete default no-op methods (capabilities).

```python
# sources/base.py

class BaseSource(ABC):
    name: str  # short identifier, e.g. "clinicaltrials_gov", "pubmed"

    # ── Lifecycle (must implement) ──────────────────────────────────────────
    @abstractmethod
    async def initialize(self) -> None:
        """Set up HTTP client and validate connectivity."""

    @abstractmethod
    async def close(self) -> None:
        """Clean up resources (e.g. close HTTP client)."""

    # ── Capabilities (override only what you support) ───────────────────────
    async def search_trials(
        self,
        condition: str,
        phase: str | None = None,
        status: str | None = None,
        sponsor: str | None = None,
        intervention: str | None = None,
        max_results: int = 10,
    ) -> list[TrialSummary]:
        return []

    async def get_trial_details(self, nct_id: str) -> TrialDetail | None:
        return None

    async def get_trial_timelines(
        self,
        condition: str,
        sponsor: str | None = None,
        max_results: int = 15,
    ) -> list[TrialTimeline]:
        return []

    async def search_publications(
        self,
        query: str,
        max_results: int = 10,
    ) -> list[Publication]:
        return []
```

### Why default no-ops instead of `NotImplementedError`?

Because the registry fans out **every** capability to **every** source. A PubMed source
should silently return `[]` for `search_trials()`, not crash the request. Sources only
override the methods they actually support.

---

## The `SourceRegistry`

`sources/registry.py` is the central fan-out point. Tools never talk to sources directly —
they call `registry.<method>()` and get a merged result.

```python
# Simplified
class SourceRegistry:
    def __init__(self) -> None:
        self._sources: list[BaseSource] = []
        self._initialized = False

    def register(self, source: BaseSource) -> None:
        self._sources.append(source)

    async def initialize_all(self) -> None:
        # Lazy: runs once on first request
        ...

    async def search_trials(self, ...) -> list[TrialSummary]:
        await self.initialize_all()
        tasks = [s.search_trials(...) for s in self._sources]
        results = []
        for coro in asyncio.as_completed(tasks):
            try:
                results.extend(await coro)
            except Exception:
                logger.exception("Source failed during search_trials")
        return results[:max_results]
```

**Key behaviors:**
- **Parallel fan-out** via `asyncio.as_completed` — slow sources don't block fast ones.
- **Per-source error isolation** — one source crashing never breaks the whole tool call.
- **Lazy init** — `initialize_all()` runs the first time any tool is called.
- **Singleton** — `registry` is imported as a global from `sources/registry.py`.

For single-record lookups (`get_trial_details`), the registry queries sources in
registration order and returns the first non-`None` hit.

---

## Data Models

All models live in `models/trials.py`. Sources return these directly — never raw dicts.

```python
class TrialSummary(BaseModel):
    source: str                            # "clinicaltrials_gov", "who_ictrp", ...
    nct_id: str
    brief_title: str
    phase: str | None = None
    overall_status: str
    lead_sponsor: str
    interventions: list[str] = []
    primary_outcomes: list[str] = []
    enrollment_count: int | None = None


class TrialDetail(TrialSummary):
    official_title: str | None = None
    eligibility_criteria: str | None = None
    arms: list[str] = []
    secondary_outcomes: list[str] = []
    study_type: str | None = None
    conditions: list[str] = []


class TrialTimeline(BaseModel):
    source: str
    nct_id: str
    brief_title: str
    phase: str | None = None
    lead_sponsor: str
    start_date: str | None = None
    primary_completion_date: str | None = None
    completion_date: str | None = None
    enrollment_count: int | None = None


class Publication(BaseModel):
    source: str
    pmid: str
    title: str
    authors: list[str] = []
    journal: str
    pub_date: str
    abstract: str = ""
```

### The `source` field is mandatory

Every model carries a `source` field so Claude can cite where each piece of evidence came
from and reason about coverage gaps ("I only checked ClinicalTrials.gov, Chinese trials may
be missing"). Always set it explicitly in your source class:

```python
TrialSummary(
    source=self.name,   # never hardcode — use the class attribute
    nct_id="NCT04179552",
    brief_title="...",
    ...
)
```

### Field naming convention

Field names mirror ClinicalTrials.gov v2 terminology (`nct_id`, `brief_title`,
`overall_status`, `lead_sponsor`) because it is the dominant source. New sources should
**map their fields onto this schema**, not introduce parallel naming.

---

## How to Add a New Data Source

Follow this recipe. The whole change should be one new file plus one line in `__main__.py`.

### 1. Create `sources/your_source.py`

```python
from __future__ import annotations

import httpx

from clinical_trials_mcp.models import TrialSummary
from clinical_trials_mcp.sources.base import BaseSource

BASE_URL = "https://your-api.example.com"


class YourSource(BaseSource):
    """One-line description of what this source provides."""

    name = "your_source"

    async def initialize(self) -> None:
        self._client = httpx.AsyncClient(base_url=BASE_URL, timeout=30.0)

    async def close(self) -> None:
        await self._client.aclose()

    async def search_trials(
        self,
        condition: str,
        phase: str | None = None,
        status: str | None = None,
        sponsor: str | None = None,
        intervention: str | None = None,
        max_results: int = 10,
    ) -> list[TrialSummary]:
        params = self._build_params(condition, phase, status, sponsor, max_results)
        response = await self._client.get("/endpoint", params=params)
        response.raise_for_status()
        return self._normalize(response.json())

    # Override only the capabilities your API supports.
    # Everything else inherits the no-op default from BaseSource.

    # ── Private helpers ─────────────────────────────────────────────────────
    def _build_params(self, condition, phase, status, sponsor, max_results) -> dict:
        ...

    def _normalize(self, raw: dict) -> list[TrialSummary]:
        results = []
        for item in raw.get("studies", []):
            try:
                results.append(TrialSummary(
                    source=self.name,
                    nct_id=item["id"],
                    brief_title=item["title"],
                    overall_status=item.get("status", "UNKNOWN"),
                    lead_sponsor=item.get("sponsor", ""),
                    # map remaining fields; leave Optional fields as None if absent
                ))
            except Exception:
                continue   # skip malformed records silently
        return results
```

### 2. Register in `__main__.py`

```python
from clinical_trials_mcp.sources.your_source import YourSource
...
registry.register(YourSource())
```

### 3. That's it

No tool changes. The next call to `search_trials` will automatically include results from
your source, merged with whatever the other sources return.

### Checklist

- [ ] Subclasses `BaseSource`
- [ ] `name` attribute set
- [ ] `initialize()` and `close()` implemented
- [ ] Only overrides capabilities the API actually supports
- [ ] Returns Pydantic models (not raw dicts)
- [ ] Sets `source=self.name` on every model
- [ ] Fields the API does not provide are explicitly `None`
- [ ] Malformed records are skipped, not raised
- [ ] Registered in `__main__.py`

---

## How to Add a New Tool

Tools are thin wrappers around the registry. They handle parameter validation and
docstring-based prompting; everything else goes through the registry.

### 1. Add a new method to `BaseSource` (with a no-op default)

```python
# sources/base.py
async def search_adverse_events(
    self,
    drug: str,
    max_results: int = 10,
) -> list[AdverseEvent]:
    return []
```

### 2. Add a fan-out method to `SourceRegistry`

```python
# sources/registry.py
async def search_adverse_events(self, drug: str, max_results: int = 10) -> list[AdverseEvent]:
    await self.initialize_all()
    tasks = [s.search_adverse_events(drug=drug, max_results=max_results) for s in self._sources]
    results: list[AdverseEvent] = []
    for coro in asyncio.as_completed(tasks):
        try:
            results.extend(await coro)
        except Exception:
            logger.exception("Source failed during search_adverse_events")
    return results[:max_results]
```

### 3. Create the tool file

```python
# tools/adverse_events.py
from clinical_trials_mcp.server import mcp
from clinical_trials_mcp.sources import registry


@mcp.tool()
async def search_adverse_events(drug: str, max_results: int = 10) -> list[dict]:
    """Search for reported adverse events for a given drug.

    Use this when the user asks about side effects, safety signals, or post-market
    surveillance data for an approved drug.

    Returns for each event: drug, reaction, severity, source.

    Args:
        drug: Generic or brand name (e.g. "pembrolizumab", "Keytruda")
        max_results: Number of results (default 10, max 20)
    """
    max_results = min(max_results, 20)
    results = await registry.search_adverse_events(drug=drug, max_results=max_results)
    return [r.model_dump() for r in results]
```

### 4. Register the tool module

```python
# tools/__init__.py
from . import adverse_events, publications, search, timelines  # noqa: F401
```

### Tool docstring conventions

The docstring is what Claude reads to decide when to call the tool. Follow this pattern:

1. **One-line summary** of what the tool does.
2. **When to use it** — concrete trigger phrases the user might say.
3. **What it returns** — flat list of fields, no marketing fluff.
4. **`Args:` block** with clinical context for each parameter (valid values, examples).

---

## Error Handling

The registry catches exceptions per source and logs them; one failing source never breaks
a tool call. Tools themselves currently let exceptions propagate to FastMCP, which
serializes them into MCP protocol errors.

```python
# sources/registry.py — already implemented
for coro in asyncio.as_completed(tasks):
    try:
        results.extend(await coro)
    except Exception:
        logger.exception("Source failed during search_trials")
```

**Inside a source** — let `httpx` raise. The registry will catch it. Don't wrap every call
in try/except for its own sake; only catch where you can do something meaningful (e.g.
skipping a malformed record in `_normalize`).

**For "not found" results** — return `None` (single-record methods) or `[]` (list methods).
Do not raise.

---

## Testing

### Test a source in isolation

```python
import asyncio
from clinical_trials_mcp.sources.clinicaltrials import ClinicalTrialsSource


async def test_clinicaltrials():
    source = ClinicalTrialsSource()
    await source.initialize()
    try:
        results = await source.search_trials(condition="lung cancer", max_results=3)
        assert len(results) <= 3
        assert all(r.source == "clinicaltrials_gov" for r in results)
        print(f"OK: {len(results)} results")
    finally:
        await source.close()


asyncio.run(test_clinicaltrials())
```

### Test a tool end-to-end (via the registry)

```python
import asyncio
from clinical_trials_mcp.sources import registry
from clinical_trials_mcp.sources.clinicaltrials import ClinicalTrialsSource
from clinical_trials_mcp.tools.search import search_trials


async def test_search_trials():
    registry.register(ClinicalTrialsSource())
    result = await search_trials(condition="NSCLC", phase="PHASE3", max_results=5)
    assert isinstance(result, list)
    assert all("nct_id" in r and "source" in r for r in result)
    print(f"OK: {len(result)} trials")


asyncio.run(test_search_trials())
```

### Before you open a PR

1. Run the source test in isolation against the real API.
2. Run the tool test end-to-end through the registry.
3. Confirm `source` is set on every returned model.
4. Confirm the source returns `[]` / `None` for capabilities it does not support.
5. Confirm `ruff check src/` passes.
