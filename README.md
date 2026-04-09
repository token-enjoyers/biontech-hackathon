# Medical Wizard MCP

Python MCP server for clinical-trial, literature, conference, and label intelligence.

The project is intentionally LLM-first:
- MCP tools return structured, bounded data
- source adapters own HTTP, parsing, and normalization
- the attached LLM owns orchestration, comparison, synthesis, and narrative answers

`README.md` is the canonical human-facing setup, usage, and testing document. `AGENTS.md` contains repo-specific guidance for coding agents only.

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Setup](#setup)
4. [Running the Server](#running-the-server)
5. [Authentication](#authentication)
6. [MCP Tools](#mcp-tools)
7. [Data Sources](#data-sources)
8. [Models](#models)
9. [Testing](#testing)
10. [Contributor Guidelines](#contributor-guidelines)
11. [Current Limitations](#current-limitations)
12. [Roadmap](#roadmap)

---

## Overview

`Medical Wizard MCP` exposes a focused MCP surface for biomedical R&D workflows:
- trial discovery and drilldown
- peer-reviewed publication search
- medRxiv preprint search
- conference-style evidence search
- approved-drug / label context
- trial benchmarking and competitive landscaping
- audit-style passage extraction and claim checking

As of the current codebase, the server exposes `30` MCP tools:

- `describe_tools`
- `search_trials`
- `get_trial_details`
- `get_trial_timelines`
- `search_publications`
- `search_preprints`
- `search_conference_abstracts`
- `search_approved_drugs`
- `search_oncology_burden`
- `compare_trials`
- `get_trial_density`
- `find_whitespaces`
- `analyze_competition_gaps`
- `competitive_landscape`
- `get_recruitment_velocity`
- `suggest_trial_design`
- `suggest_patient_profile`
- `benchmark_trial_design`
- `benchmark_eligibility_criteria`
- `benchmark_endpoints`
- `link_trial_evidence`
- `analyze_patient_segments`
- `forecast_readouts`
- `track_competitor_assets`
- `summarize_safety_signals`
- `investigator_site_landscape`
- `watch_indication_signals`
- `track_indication_changes`
- `get_document_passages`
- `extract_structured_evidence`
- `verify_claim_evidence`

Three output classes are used throughout the tool catalog:
- `raw`: source-aligned retrieval
- `derived`: light aggregation over normalized records
- `heuristic`: estimations or recommendations that should be treated as drafts

---

## Architecture

```text
src/Medical_Wizard_MCP/
├── __main__.py
├── server.py
├── models/
│   ├── __init__.py
│   └── trials.py
├── sources/
│   ├── __init__.py
│   ├── _conference_utils.py
│   ├── base.py
│   ├── registry.py
│   ├── clinicaltrials.py
│   ├── europepmc.py
│   ├── medrxiv.py
│   ├── openfda.py
│   └── pubmed.py
└── tools/
    ├── __init__.py
    ├── _evidence_extraction.py
    ├── _evidence_quality.py
    ├── _inputs.py
    ├── _intelligence.py
    ├── _responses.py
    ├── _tool_catalog.py
    ├── audit.py
    ├── catalog.py
    ├── conferences.py
    ├── drugs.py
    ├── intelligence.py
    ├── monitoring.py
    ├── publications.py
    ├── search.py
    └── timelines.py

tests/
├── conftest.py
├── smoke_mcp_tool_outputs.py
├── test_all_tools_smoke.py
├── test_audit_tools.py
├── test_clinicaltrials_source.py
├── test_conference_live.py
├── test_conference_sources.py
├── test_europepmc.py
├── test_europepmc_live.py
├── test_intelligence_tools.py
├── test_medrxiv.py
├── test_model_boundaries.py
├── test_pubmed.py
├── test_pubmed_live.py
├── test_rosetta_lung_e2e.py
└── test_tool_responses.py
```

### Runtime Flow

```text
User question
  -> MCP client (Codex / LibreChat / MCP Inspector / custom client)
  -> MCP tool
  -> SourceRegistry
  -> one or more source adapters
  -> normalized Pydantic models
  -> MCP response envelope with evidence trace
  -> LLM synthesis
```

### Layer Boundaries

| Layer | Responsibility | What does not belong here |
|---|---|---|
| `sources/` | HTTP calls, payload parsing, source quirks, normalization | user-facing reasoning, narrative synthesis |
| `sources/registry.py` | fan-out, dedupe, source selection, warning collection | source-specific parsing |
| `tools/` | thin MCP wrappers, bounded aggregation, response envelopes | raw HTTP calls |
| `server.py` | shared `FastMCP` instance and auth setup | tool logic |

### Design Rules

- Keep tools thin and composable.
- Prefer adding a new source adapter over embedding source logic in a tool.
- Reuse `SourceRegistry` instead of calling sources directly from tools.
- Treat `src/Medical_Wizard_MCP/tools/` as the source of truth for what is implemented.
- Treat `_meta.evidence_trace` and `_meta.evidence_refs` as the audit trail for downstream LLMs.

---

## Setup

### Requirements

- Python `3.11+`
- `uv` recommended

### Installation with `uv`

```bash
git clone <repo-url>
cd biontech-hackathon
uv sync --dev
```

### Installation without `uv`

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

### Bootstrap helper

If your shell resolves `python` / `python3` to an unexpected interpreter, use:

```bash
./local-dev/bootstrap.sh
source .venv/bin/activate
```

### Dependencies

Runtime dependencies come from `pyproject.toml`:
- `fastmcp>=3.2.2`
- `httpx`
- `pydantic>=2.0`
- `python-dotenv`

Dev dependencies:
- `pytest`
- `pytest-asyncio`
- `ruff`

---

## Running the Server

### Preferred local runner

```bash
./local-dev/run-server.sh
```

The canonical local endpoint is:

```text
http://127.0.0.1:8000/mcp
```

### Verbose local debug loop

```bash
FASTMCP_LOG_LEVEL=DEBUG ./local-dev/run-server.sh
npx -y @modelcontextprotocol/inspector
```

### MCP client examples

Codex:

```bash
codex mcp add medical-wizard-mcp --url http://127.0.0.1:8000/mcp
codex mcp list
```

LibreChat:

```yaml
mcpServers:
  medical-wizard-mcp:
    type: streamable-http
    url: http://127.0.0.1:8000/mcp
```

### Environment variables

Commonly useful variables:

```bash
JWT_SECRET=dev-secret
PUBMED_API_KEY=       # increases PubMed rate limit from 3 to 10 req/s
PUBMED_EMAIL=         # recommended by NCBI for identification
CLINICALTRIALS_PREFER_CURL=1  # default transport for ClinicalTrials.gov; set to 0 to retry httpx first
BIGQUERY_PROJECT_ID=          # required for the BigQuery oncology burden source
BIGQUERY_DATASET=             # optional if BIGQUERY_ONCOLOGY_VIEW is fully qualified
BIGQUERY_ONCOLOGY_VIEW=       # BigQuery view or table to query; defaults to oncology_burden_search inside BIGQUERY_DATASET
BIGQUERY_LOCATION=            # optional BigQuery job location, e.g. EU or US
```

For local BigQuery development with ADC, authenticate once with:

```bash
gcloud auth application-default login
```

Notes:
- `JWT_SECRET` is effectively required because the server config uses `JWTVerifier` with `HS256`.
- `PUBMED_API_KEY` increases PubMed throughput.
- `PUBMED_EMAIL` is recommended by NCBI.
- `CLINICALTRIALS_PREFER_CURL=1` keeps the ClinicalTrials.gov adapter on its curl-first path.

---

## Authentication

The server is configured with JWT auth in [src/Medical_Wizard_MCP/server.py](/Users/jannikmuller/PhpstormProjects/biontech-hackathon/src/Medical_Wizard_MCP/server.py).

Current behavior:
- algorithm: `HS256`
- secret source: `JWT_SECRET`
- expected scope in tests: `mcp:access`

For local development, exporting any non-empty `JWT_SECRET` is enough:

```bash
export JWT_SECRET=dev-secret
./local-dev/run-server.sh
```

Tests generate bearer tokens from the same secret in [tests/conftest.py](/Users/jannikmuller/PhpstormProjects/biontech-hackathon/tests/conftest.py).

---

## MCP Tools

### Response contract

Every tool returns a standardized envelope with:
- `_meta.tool`
- `_meta.tool_category`
- `_meta.output_kind`
- `_meta.quality_note`
- `_meta.coverage`
- `_meta.evidence_sources`
- `_meta.evidence_refs`
- `_meta.evidence_trace`
- `_meta.requested_filters`
- `_meta.routing_hints`

This makes the server easier for attached LLMs to route, cite, and audit.

### Tool families

#### Meta

| Tool | Output | Purpose |
|---|---|---|
| `describe_tools` | `raw` | machine-readable routing catalog for attached LLMs |

#### Discovery and evidence retrieval

| Tool | Output | Purpose |
|---|---|---|
| `search_trials` | `raw` | candidate trial search by indication, sponsor, intervention, or free-text named-trial query |
| `get_trial_details` | `raw` | one detailed trial record by `nct_id` |
| `search_publications` | `raw` | PubMed literature retrieval |
| `search_preprints` | `raw` | medRxiv preprint retrieval |
| `search_conference_abstracts` | `raw` | conference-style evidence retrieval via Europe PMC |
| `search_approved_drugs` | `raw` | approved-drug / label context from OpenFDA |

#### Analysis and benchmarking

| Tool | Output | Purpose |
|---|---|---|
| `get_trial_timelines` | `derived` | timeline rows for trial timing analysis |
| `compare_trials` | `derived` | side-by-side comparison for known `nct_id`s |
| `get_trial_density` | `derived` | trial counts by grouped dimensions |
| `analyze_competition_gaps` | `heuristic` | whitespace / crowding hypothesis generation |
| `find_whitespaces` | `heuristic` | deprecated alias for `analyze_competition_gaps` |
| `competitive_landscape` | `derived` | sponsor, mechanism, and phase-level aggregation |
| `get_recruitment_velocity` | `derived` | recruitment speed heuristics |
| `benchmark_trial_design` | `derived` | comparable design patterns |
| `benchmark_eligibility_criteria` | `derived` | common eligibility signals |
| `benchmark_endpoints` | `derived` | endpoint category benchmarking |
| `analyze_patient_segments` | `derived` | biomarker / line-of-therapy / segment patterns |
| `forecast_readouts` | `heuristic` | readout estimates from known or inferred dates |
| `track_competitor_assets` | `derived` | sponsor/asset grouping over trial records |
| `summarize_safety_signals` | `derived` | safety signal aggregation from available evidence |
| `investigator_site_landscape` | `derived` | site / country / official landscape |
| `watch_indication_signals` | `derived` | combined signal summary across trials and literature |
| `link_trial_evidence` | `derived` | query-based bundle of publications, preprints, and approvals for one trial |

#### Recommendations

| Tool | Output | Purpose |
|---|---|---|
| `suggest_trial_design` | `heuristic` | draft protocol-design suggestions |
| `suggest_patient_profile` | `heuristic` | draft target-patient profile suggestion |

#### Monitoring

| Tool | Output | Purpose |
|---|---|---|
| `track_indication_changes` | `derived` | “what is new since X” over current retrievable records |

#### Audit

| Tool | Output | Purpose |
|---|---|---|
| `get_document_passages` | `derived` | lexical passage extraction from retrieved documents |
| `extract_structured_evidence` | `derived` | structured finding extraction from retrieved documents |
| `verify_claim_evidence` | `derived` | lightweight claim-vs-passage evidence check |

### Important behavior notes

#### `search_trials`

`search_trials` now supports two modes:
- classic indication-driven retrieval
- free-text named-trial retrieval via `query` / `term`

Named-trial retrieval applies conservative query normalization and variant expansion for forms such as:
- `ROSETTA-Lung`
- `ROSETTA Lung`
- `ROSETTALung`
- `ROSETTA Lung clinical trial`

Returned records are deduplicated by `nct_id`.

#### `link_trial_evidence`

`link_trial_evidence` is still query-based, not citation-perfect, but it now searches publications and preprints with multiple trial-derived queries, including:
- `nct_id`
- brief title
- official title
- normalized title variants
- trial-plus-condition / intervention combinations

This materially improves recall for named studies whose latest evidence is indexed under the study title rather than only the NCT ID.

#### `search_conference_abstracts`

Conference retrieval currently:
- uses `Europe PMC`
- normalizes conference series for `ASCO`, `AACR`, `ESMO`, and `SITC`
- ranks results with transparent `conference_result_score`
- filters out weak records below `minimum_conference_result_score`

This is meant for early-signal scouting, not as a substitute for full journal evidence.

#### `track_indication_changes`

This tool is intentionally snapshot-based. It filters the currently retrievable records by date and does not reconstruct historical state transitions from persisted snapshots.

---

## Data Sources

Currently registered sources in [src/Medical_Wizard_MCP/__main__.py](/Users/jannikmuller/PhpstormProjects/biontech-hackathon/src/Medical_Wizard_MCP/__main__.py):

| Source | Role | Main capabilities |
|---|---|---|
| `ClinicalTrials.gov` | trial registry | `trial_search`, `trial_details`, `trial_timelines` |
| `PubMed` | peer-reviewed literature | `publication_search` |
| `medRxiv` | preprints | `preprint_search` |
| `OpenFDA` | approved-drug / label context | `approved_drugs` |
| `Europe PMC` | conference-oriented scholarly retrieval | `conference_search` |

### SourceRegistry behavior

`SourceRegistry` is responsible for:
- source initialization
- capability-based fan-out
- warning capture on partial source failures
- record merging and deduplication

Current dedupe behavior is identifier-based where possible:
- trials: `nct_id`
- publications: `pmid`, then `doi`, then `title`
- preprints: `doi`, then `title`

---

## Models

Shared normalized models live in [src/Medical_Wizard_MCP/models/trials.py](/Users/jannikmuller/PhpstormProjects/biontech-hackathon/src/Medical_Wizard_MCP/models/trials.py).

Current public data models:

| Model | Used for |
|---|---|
| `TrialSummary` | trial search rows |
| `TrialDetail` | full trial drilldown |
| `TrialTimeline` | timing-focused trial rows |
| `Publication` | PubMed and medRxiv records |
| `ConferenceAbstract` | conference-style evidence rows |
| `ApprovedDrug` | OpenFDA label-derived drug records |

Model normalization goals:
- consistent field names across sources
- list-safe fields for downstream LLM use
- stable keys for evidence references

---

## Testing

### Fast local test commands

Core regression suite:

```bash
uv run pytest tests/test_tool_responses.py tests/test_intelligence_tools.py
```

Broader smoke coverage:

```bash
uv run pytest tests/test_all_tools_smoke.py
uv run pytest tests/test_clinicaltrials_source.py
uv run pytest tests/test_audit_tools.py
```

Conference coverage:

```bash
uv run pytest tests/test_conference_sources.py tests/test_europepmc.py
```

Named-trial end-to-end regression:

```bash
uv run pytest tests/test_rosetta_lung_e2e.py
```

### Live tests

Live tests are opt-in and skip by default.

PubMed:

```bash
RUN_LIVE_PUBMED=1 uv run pytest tests/test_pubmed_live.py
```

Europe PMC:

```bash
RUN_LIVE_EUROPEPMC=1 uv run pytest tests/test_europepmc_live.py
```

Conference sources:

```bash
RUN_LIVE_CONFERENCE=1 uv run pytest tests/test_conference_live.py
```

Useful live-test env vars:

```bash
PUBMED_LIVE_QUERY="mrna cancer vaccine"
PUBMED_LIVE_MAX_RESULTS=3
PUBMED_LIVE_YEAR_FROM=2023

EUROPEPMC_LIVE_QUERY="mRNA therapy"
EUROPEPMC_LIVE_MAX_RESULTS=3
EUROPEPMC_LIVE_YEAR_FROM=2023
EUROPEPMC_LIVE_SERIES="SITC,ASCO,AACR,ESMO"

CONFERENCE_LIVE_QUERY="neoantigen therapy melanoma"
CONFERENCE_LIVE_YEAR_FROM=2022
CONFERENCE_LIVE_SERIES="ASCO,AACR,ESMO,SITC"
```

### Auth-related test note

Because the server uses JWT auth, set `JWT_SECRET` in your environment before running tests that import the full server stack:

```bash
export JWT_SECRET=dev-secret
uv run pytest
```

---

## Contributor Guidelines

### General

- Keep the project LLM-first.
- Prefer adding data, not prose logic, at the MCP layer.
- Do not move large-scale synthesis into source adapters or tools.

### When adding a new source

1. Implement the source in `src/Medical_Wizard_MCP/sources/`.
2. Override only the capability methods the source truly supports.
3. Register the source in `src/Medical_Wizard_MCP/__main__.py`.
4. Add or update tests for normalization and failure handling.

### When adding a new tool

1. Add the MCP tool in `src/Medical_Wizard_MCP/tools/`.
2. Register the module import in `src/Medical_Wizard_MCP/tools/__init__.py`.
3. Add catalog metadata in `src/Medical_Wizard_MCP/tools/_tool_catalog.py`.
4. Return the standard response envelope with evidence trace and routing hints.

### Response design expectations

- include `_meta.coverage`
- include `_meta.quality_note`
- include `_meta.requested_filters`
- include `_meta.evidence_trace`
- include `_meta.evidence_refs` through the shared response helpers
- prefer transparent heuristics over hidden scoring

---

## Current Limitations

- `link_trial_evidence` is still query-based association, not exact citation graph resolution.
- `track_indication_changes` is based on current retrievable records and date filtering, not persisted historical snapshots.
- Audit tools only operate on directly available text such as registry fields, abstracts, and labels.
- Conference retrieval is useful but inherently noisier than PubMed literature search.
- Source coverage remains public-source-only; no internal BioNTech systems or proprietary conference feeds are integrated.
- Some heuristics in `intelligence.py` and `_intelligence.py` are oncology-focused and should be treated as lightweight assists, not decision engines.

---

## Roadmap

High-value next steps that fit the current architecture:

- stronger trial-to-publication resolution beyond query matching
- persisted historical snapshots for true change tracking
- richer ontology / alias handling for disease, asset, and comparator terms
- additional compliant conference or regulatory data sources
- more explicit live integration tests across selected workflows

Near-term regression targets already represented in the test suite:
- named-trial lookup via noisy input forms
- latest-publication recall for title-indexed trials
- conference-source ranking and minimum-score filtering
