# Medical Wizard MCP

Python MCP server for clinical trial and publication intelligence.

The project follows an LLM-first design:
- MCP tools return structured, minimal data
- source adapters handle HTTP, parsing, and normalization
- the LLM performs synthesis, reasoning, and interpretation

`README.md` is the canonical human-facing setup and usage document. `AGENTS.md` contains only repo-specific guidance for coding agents.

## Table of Contents

1. [Architecture](#architecture)
2. [Setup](#setup)
3. [MCP Tools](#mcp-tools)
4. [Data Sources](#data-sources)
5. [Models](#models)
6. [Testing](#testing)
7. [Contributor Guidelines](#contributor-guidelines)
8. [Roadmap](#roadmap)

---

Implemented MCP tools today:
- `describe_tools`
- `search_trials`
- `get_trial_details`
- `get_trial_timelines`
- `search_publications`
- `search_preprints`
- `search_approved_drugs`
- `compare_trials`
- `get_trial_density`
- `analyze_competition_gaps`
- `find_whitespaces`
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

## Architecture

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
│   ├── pubmed.py
│   ├── medrxiv.py
│   └── openfda.py
└── tools/
    ├── __init__.py
    ├── search.py
    ├── timelines.py
    ├── publications.py
    ├── drugs.py
    ├── intelligence.py
    ├── _intelligence.py
    └── _responses.py

tests/
├── conftest.py
├── test_intelligence_tools.py
├── test_pubmed.py
├── test_pubmed_live.py
└── test_tool_responses.py
```

### Runtime Flow

```text
User question
  -> LibreChat / Codex / MCP Inspector
  -> MCP protocol (streamable-http)
  -> MCP tool
  -> SourceRegistry
  -> one or more source adapters
  -> normalized Pydantic models
  -> LLM synthesis and interpretation
```

### Three-Layer Rule

| Layer | Responsibility | What does NOT belong here |
|-------|---------------|--------------------------|
| `sources/` | Raw HTTP requests, parsing, normalization | Business logic, filtering |
| `tools/` | MCP tool definitions, calling sources, returning structured output | HTTP requests, parsing |
| `server.py` | Registering tools with FastMCP | Any logic whatsoever |

---

## Endpoint Notes

The detailed catalog below mixes currently implemented tools with roadmap ideas from the original hackathon scope. Treat the code in `src/Medical_Wizard_MCP/tools/` as the source of truth for what is available right now.

## Setup

### Requirements

- Python 3.11+
- `uv` recommended

### Installation

```bash
git clone <repo-url>
cd medical-wizard-mcp
uv sync --dev
```

Without `uv`:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

If macOS resolves `python` or `python3` to the Xcode system Python, use the bootstrap script instead:

```bash
./local-dev/bootstrap.sh
source .venv/bin/activate
```

### Run the Server

```bash
./local-dev/run-server.sh
```

Run the server with verbose MCP logs:

```bash
FASTMCP_LOG_LEVEL=DEBUG ./local-dev/run-server.sh
```

### Server Endpoint

```text
http://127.0.0.1:8000/mcp
```

### Codex Configuration

```bash
codex mcp add medical-wizard-mcp --url http://127.0.0.1:8000/mcp
codex mcp list
```

### LibreChat Configuration

Add to your `librechat.yaml`:

```yaml
mcpServers:
  medical-wizard-mcp:
    type: streamable-http
    url: http://127.0.0.1:8000/mcp
```

### Optional Environment Variables

```bash
PUBMED_API_KEY=       # increases PubMed rate limit from 3 to 10 req/s
PUBMED_EMAIL=         # recommended by NCBI for identification
```

---

## MCP Tools

### Design Principle

Tools return structured data. The LLM performs all analysis, comparison,
and strategic interpretation. No analytics logic lives in the tool layer.

In practice, the server now exposes three tool classes:

- `raw`: source-aligned discovery or evidence retrieval
- `derived`: server-side aggregation over raw records
- `heuristic`: server-side estimation or recommendation that should be treated as a draft

If an attached LLM is unsure which tool to use, call `describe_tools` first.

For domain filters, prefer the canonical parameter name `indication`.
Some tools still accept backward-compatible aliases such as `condition`.

Every tool response follows this envelope:

```json
{
  "_meta": {
    "tool": "search_trials",
    "tool_category": "discovery",
    "output_kind": "raw",
    "source": "clinicaltrials_gov",
    "data_type": "trial_search_results",
    "quality_note": "...",
    "coverage": "...",
    "evidence_sources": ["clinicaltrials_gov"],
    "evidence_trace": [
      {
        "step": "search_trial_registry",
        "sources": ["clinicaltrials_gov"],
        "note": "Fetched candidate trials matching the requested filters.",
        "output_kind": "raw"
      }
    ],
    "requested_filters": {},
    "partial_failures": [],
    "routing_hints": {
      "canonical_parameters": ["indication", "phase", "status", "sponsor", "intervention", "max_results"],
      "parameter_aliases": {"condition": "indication"},
      "requires_identifiers": [],
      "typical_next_tools": ["get_trial_details", "get_trial_timelines"]
    }
  },
  "count": 42,
  "results": []
}
```

`evidence_sources` is the high-level provenance field to inspect first.
`evidence_trace` shows which source(s) mattered at each internal processing step so an attached LLM or human reviewer can audit how the result was assembled and decide where to drill deeper.

---

### Stufe 0 – MVP

#### `search_trials`

Search for clinical trials by indication, phase, status, or sponsor.

**Input:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `condition` | str | ✓ | Cancer type, e.g. "lung cancer", "NSCLC" |
| `phase` | str | | PHASE1, PHASE2, PHASE3, PHASE4 |
| `status` | str | | RECRUITING, COMPLETED, TERMINATED |
| `sponsor` | str | | Company or institution name |
| `max_results` | int | | Default: 20 |

**Output:** `Trial[]` → `id`, `title`, `sponsor`, `phase`, `status`, `start_date`, `completion_date`

**Source:** `clinicaltrials.py`

**Example questions:**
- "What are the main Phase 3 trials in melanoma and which sponsors are conducting them?"
- "Which NSCLC trials is Merck currently running?"

---

#### `get_trial_details`

Retrieve complete information for a single trial by NCT ID.

**Input:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `nct_id` | str | ✓ | ClinicalTrials.gov identifier, e.g. "NCT04179552" |

**Output:** Full trial object → `endpoints`, `biomarkers`, `eligibility`,
`interventions`, `enrollment`, `why_stopped`

**Source:** `clinicaltrials.py`

**Example questions:**
- "Show me everything about NCT04179552"
- "What are the inclusion criteria for this trial?"
- "Why was this trial terminated?"

---

#### `get_trial_timeline`

Retrieve temporal data for velocity analysis and market authorization timing.
Use this tool to estimate which therapies may reach market by a target year.

**Input:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `condition` | str | ✓ | Cancer type |
| `sponsor` | str | | Filter by sponsor |
| `phase` | str | | Filter by phase |

**Output:** `Trial[]` → `nct_id`, `sponsor`, `phase`, `start_date`,
`primary_completion_date`, `status`

**Source:** `clinicaltrials.py`

**Example questions:**
- "Which lung cancer therapies in clinical development are likely to obtain
  market authorization by 2030?"
- "How long do Phase 2 trials in GBM typically take?"
- "How quickly is Merck progressing through phases in NSCLC?"

---

#### `search_publications`

Search PubMed for peer-reviewed publications on a therapy or indication.

**Input:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `term` | str | ✓ | Search term, e.g. "mRNA vaccine NSCLC" |
| `indication` | str | | Narrow by cancer type |
| `year_from` | int | | Only publications from this year onwards |
| `max_results` | int | | Default: 20 |

**Output:** `Publication[]` → `pmid`, `title`, `abstract`, `journal`,
`year`, `authors`, `doi`, `mesh_terms`

**Source:** `pubmed.py`

**Example questions:**
- "What has been published about mRNA vaccines in lung cancer?"
- "What are the published outcomes for PD-1 inhibitors in GBM?"
- "What key findings exist for this trial?"

---

#### `compare_trials`

Compare multiple trials side by side, normalized across the same fields.
Designed to answer design, endpoint, and outcome comparison questions.

**Input:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `nct_ids` | list[str] | ✓ | 2–5 NCT IDs to compare |

**Output:** Normalized comparison table with one entry per trial:

```json
{
  "_meta": {},
  "count": 3,
  "results": [
    {
      "nct_id": "NCT04179552",
      "sponsor": "BioNTech",
      "phase": "PHASE2",
      "condition": "NSCLC",
      "intervention": "mRNA vaccine + PD-1",
      "enrollment": 120,
      "primary_endpoint": "PFS at 6 months",
      "biomarkers": ["TMB-high"],
      "status": "RECRUITING",
      "start_date": "2021-03",
      "completion_date": "2025-06"
    }
  ]
}
```

**Source:** `clinicaltrials.py` (calls `get_trial_details` per NCT ID)

**Example questions:**
- "How do breast cancer trials from BioNTech, Merck, and Roche compare in
  terms of design, endpoints, and outcomes?"
- "Compare these three NSCLC trials"
- "What are the differences in eligibility criteria between these trials?"

---

#### `get_trial_density`

Count trials for an indication grouped by phase, intervention type, or sponsor.
Foundational data source for `find_whitespaces` and `competitive_landscape`.

**Input:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `indication` | str | ✓ | Cancer type |
| `group_by` | str | | "phase", "intervention_type", or "sponsor". Default: "phase" |
| `status` | str | | Optional status filter |

**Output:**

```json
{
  "_meta": {},
  "indication": "pancreatic cancer",
  "group_by": "phase",
  "status_filter": null,
  "distribution": {
    "PHASE1": 89,
    "PHASE2": 54,
    "PHASE3": 12,
    "PHASE4": 3
  },
  "total": 158
}
```

**Source:** `clinicaltrials.py` (`countTotal=true`, parallel calls via `asyncio.gather`)

**Example questions:**
- "How many trials exist per phase in pancreatic cancer?"
- "Which therapy mechanisms dominate in NSCLC?"

---

#### `find_whitespaces`

Identify underserved areas in a cancer indication by analyzing trial density
across phases and intervention mechanisms. Returns structured signals for
the LLM to evaluate as strategic whitespaces for a sponsor's pipeline.

**Input:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `indication` | str | ✓ | Cancer type |
| `include_terminated` | bool | | Include terminated trial analysis. Default: true |

**Output:**

```json
{
  "_meta": {},
  "indication": "pancreatic cancer",
  "active_trial_density": {
    "by_phase": {
      "PHASE1": 89, "PHASE2": 54, "PHASE3": 12, "PHASE4": 3
    },
    "by_mechanism": {
      "PD-1 inhibitor": 34,
      "chemotherapy": 28,
      "mRNA vaccine": 3,
      "CAR-T": 1,
      "bispecific antibody": 2
    }
  },
  "terminated_trials": {
    "count": 23,
    "trials": [
      {
        "nct_id": "NCT03214...",
        "sponsor": "Pfizer",
        "phase": "PHASE2",
        "why_stopped": "Insufficient Efficacy",
        "intervention": "PD-1 Monotherapy"
      }
    ]
  },
  "whitespace_signals": [
    {
      "mechanism": "mRNA vaccine",
      "active_trial_count": 3,
      "signal_strength": "HIGH",
      "terminated_in_this_space": 0
    }
  ]
}
```

**Source:** `clinicaltrials.py` (internally: `get_trial_density` + `search_trials TERMINATED`)

**Example questions:**
- "Are there white spaces or underserved segments in pancreatic cancer?"
- "Where could an mRNA platform enter without heavy competition?"

---

#### `competitive_landscape`

Generate a full competitive picture of an indication: who is active,
in which phases, with which mechanisms, and how saturated the market is.

**Input:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `indication` | str | ✓ | Cancer type |
| `phase` | str | | Optional phase filter |
| `status` | str | | Default: "RECRUITING" |

**Output:**

```json
{
  "_meta": {},
  "indication": "NSCLC",
  "market_saturation": {
    "score": "HIGH",
    "total_active_trials": 312,
    "unique_sponsors": 47
  },
  "dominant_mechanisms": [
    { "mechanism": "PD-1 inhibitor", "trial_count": 89 },
    { "mechanism": "chemotherapy combo", "trial_count": 67 }
  ],
  "sponsors": [
    {
      "name": "Merck",
      "active_trials": 14,
      "phases": ["PHASE2", "PHASE3"],
      "mechanisms": ["PD-1", "bispecific"],
      "furthest_phase": "PHASE3"
    }
  ]
}
```

**Source:** `clinicaltrials.py` (internally: `search_trials` + `get_trial_density`)

**Example questions:**
- "Who is active in NSCLC and at what phase?"
- "How saturated is the breast cancer market?"
- "Compare two sponsors in NSCLC"

---

#### `get_recruitment_velocity`

Analyze how quickly sponsors are enrolling patients into trials for an indication.
Use this to assess feasibility of similar study designs and realistic timelines.

**Input:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `indication` | str | ✓ | Cancer type |
| `phase` | str | | Optional phase filter |
| `sponsor` | str | | Optional sponsor filter |

**Output:**

```json
{
  "_meta": {},
  "indication": "NSCLC",
  "indication_average_per_month": 18.4,
  "results": [
    {
      "nct_id": "NCT04179552",
      "sponsor": "Merck",
      "enrollment_target": 450,
      "months_recruiting": 18,
      "enrollment_per_month": 25.0,
      "velocity_vs_indication_avg": "ABOVE"
    }
  ]
}
```

**Source:** `clinicaltrials.py` (enrollment + start_date + status from `search_trials`)

**Example questions:**
- "How quickly are sponsors recruiting patients in NSCLC?"
- "Is our planned enrollment of 300 patients in 18 months feasible?"
- "What does recruitment velocity in GBM indicate about study feasibility?"

---

### Stufe 3 – Extended Data Sources

#### `search_approved_drugs`

Retrieve already approved therapies per indication from OpenFDA.

**Input:** `indication`, `year_from?`

**Output:** `ApprovedDrug[]` → `brand_name`, `generic_name`, `indication`,
`approval_date`, `sponsor`

**Source:** `openfda.py`

**Example questions:**
- "What is already approved in NSCLC?"
- "Which therapies would a new sponsor need to outperform in breast cancer?"

---

`search_international_trials` remains a roadmap item. It is not implemented in
the current codebase yet.

---

#### `search_preprints`

Find research that has not yet passed peer review. Early indicator for
emerging approaches before they appear in PubMed.

**Input:** `term`, `indication?`, `year_from?`

**Output:** `Publication[]` (same schema as `search_publications`)

**Source:** `medrxiv.py`

**Example questions:**
- "What is being researched in GBM that hasn't been published yet?"
- "Are there early signals for new mRNA approaches in solid tumors?"

---

### Stufe 4 – Trial Design Intelligence

#### `suggest_trial_design`

Generate a data-driven trial blueprint based on whitespace analysis,
failure patterns from terminated trials, and competitor velocity.

**Input:** `indication`, `mechanism`

**Output:**

```json
{
  "_meta": {},
  "indication": "glioblastoma",
  "mechanism": "mRNA neoantigen vaccine",
  "recommended_phase": "PHASE2",
  "enrollment": 120,
  "primary_endpoint": "PFS at 6 months",
  "biomarkers": ["TMB-high"],
  "combination_therapy": "mRNA vaccine + anti-PD-1",
  "rationale": {
    "whitespace_basis": ["Only 2 active trials in GBM x mRNA"],
    "failure_learnings": ["PD-1 mono failed 5x – tumor microenvironment too immunosuppressive"],
    "velocity_window": "No competitor in Phase 2 before 2027 – 36 month window"
  },
  "reference_trials": ["NCT03899857", "NCT04161755"],
  "confidence_score": 0.81
}
```

**Source:** internally combines `search_trials`, `get_trial_details`,
`search_publications`, `find_whitespaces`

**Example questions:**
- "How should a GBM mRNA vaccine trial be designed?"
- "What do you recommend for a Phase 2 pancreatic cancer trial?"

---

#### `suggest_patient_profile`

Derive the optimal patient profile based on what has worked in similar
completed trials. Identifies predictive biomarkers and realistic response rates.

**Input:** `indication`, `mechanism`, `biomarker?`

**Output:**

```json
{
  "_meta": {},
  "inclusion_criteria": [
    "Age 18-70",
    "ECOG Performance Status 0-1",
    "TMB-high (>10 mut/Mb)",
    "Measurable disease per RECIST"
  ],
  "exclusion_criteria": [
    "Active autoimmune disease",
    "Systemic corticosteroids"
  ],
  "predictive_biomarkers": [
    {
      "marker": "TMB-high",
      "response_rate": 0.34,
      "vs_unselected": 0.12,
      "evidence_trials": 8
    }
  ],
  "recommended_ecog": "0-1",
  "estimated_response_rate": 0.34,
  "based_on_trials": 12
}
```

**Source:** internally combines `get_trial_details` (completed trials)
and `search_publications`

**Example questions:**
- "Who should we recruit for the GBM mRNA vaccine trial?"
- "Which patients respond best to this mechanism?"

---

### Stufe 5 – Portfolio and Evidence Intelligence

#### `benchmark_trial_design`

Benchmark common design archetypes for similar trials.

**Input:** `indication`, `phase?`, `mechanism?`, `sponsor?`

**Output:** sample size, enrollment benchmark, study types, design archetypes,
therapy models, primary and secondary endpoint categories, biomarker segments,
comparator signals, reference trials.

**Example questions:**
- "How are Phase 2 NSCLC mRNA studies typically designed?"
- "What does competitor trial design look like for Merck in NSCLC?"

---

#### `benchmark_eligibility_criteria`

Extract recurring inclusion, exclusion, and biomarker rules from comparable trials.

**Input:** `indication`, `phase?`, `mechanism?`

**Output:** common inclusion criteria, exclusion criteria, biomarker criteria,
CNS policy patterns, reference trials.

**Example questions:**
- "Which eligibility criteria are common in Phase 2 NSCLC trials?"
- "How restrictive are competitor trials around autoimmune disease or CNS mets?"

---

#### `benchmark_endpoints`

Benchmark which endpoints are most often used in similar trials.

**Input:** `indication`, `phase?`, `mechanism?`

**Output:** categorized primary and secondary endpoints plus representative examples.

**Example questions:**
- "Which primary endpoints are most common in Phase 2 GBM?"
- "How often do NSCLC studies use ORR versus PFS?"

---

#### `link_trial_evidence`

Link one NCT trial to supporting publications, preprints, and approved-drug context.

**Input:** `nct_id`, `include_preprints?`, `include_approvals?`

**Output:** trial context, queries used, linked PubMed papers, linked medRxiv preprints,
related approved therapies, evidence counts.

**Example questions:**
- "Show me the evidence chain around NCT04179552"
- "Which publications or labels are relevant to this trial?"

---

#### `analyze_patient_segments`

Identify biomarker, line-of-therapy, and stage-defined patient segments in an indication.

**Input:** `indication`, `phase?`, `mechanism?`

**Output:** crowded segments, underserved segments, biomarker segments,
line-of-therapy segments, disease-stage segments, reference trials.

**Example questions:**
- "Which patient segments in NSCLC look crowded or underserved?"
- "Where are biomarker-defined whitespace opportunities?"

---

#### `forecast_readouts`

Forecast upcoming known and estimated readouts from timeline signals.

**Input:** `indication`, `phase?`, `sponsor?`, `months_ahead?`

**Output:** phase-duration benchmarks and a forecast table with known or estimated
readout dates, confidence, and basis.

**Example questions:**
- "Which NSCLC trials may read out in the next 18 months?"
- "What is the likely readout window for Merck's Phase 2 activity?"

---

#### `track_competitor_assets`

Group interventions into sponsor-level asset views for pipeline tracking.

**Input:** `indication`, `sponsors?`, `mechanism?`

**Output:** sponsor, asset, trial count, phases, furthest phase, statuses,
mechanism tags, NCT IDs.

**Example questions:**
- "Which assets are Merck and Pfizer advancing in NSCLC?"
- "What does the competitor asset map look like in lung cancer?"

---

#### `summarize_safety_signals`

Surface recurring safety terms from publications, preprints, and approved labels.

**Input:** `indication`, `mechanism?`, `year_from?`

**Output:** recurring safety signals, example evidence, counts by source.

**Example questions:**
- "What safety themes recur around mRNA combinations in NSCLC?"
- "Which adverse events should we watch for in this space?"

---

#### `investigator_site_landscape`

Summarize visible site geography and study-official metadata for active trials.

**Input:** `indication`, `phase?`, `sponsor?`

**Output:** countries, facilities, visible study officials, reference trials.

**Example questions:**
- "Where are recruiting NSCLC trials concentrated geographically?"
- "Which visible officials and sites show up repeatedly in this indication?"

---

#### `watch_indication_signals`

Create a watchlist snapshot across trials, publications, preprints, approvals,
and upcoming readouts.

**Input:** `indication`, `mechanism?`, `sponsor?`, `recent_years?`, `months_ahead?`

**Output:** trial activity, recent starts, upcoming readouts, publication activity,
preprint activity, approved landscape.

**Example questions:**
- "Give me a current watchlist for NSCLC mRNA activity"
- "What fresh signals should BioNTech R&D monitor in this indication?"

---

### Complete Tool Overview

| Tool | Stufe | Source | Key Question Addressed |
|------|-------|--------|----------------------|
| `search_trials` | 0 | clinicaltrials | Q1: Phase 3 trials per indication |
| `get_trial_details` | 0 | clinicaltrials | Q3: Trial design details |
| `get_trial_timelines` | 0 | clinicaltrials | Q2: Market authorization by 2030 |
| `search_publications` | 0 | pubmed | Q3: Outcomes and results |
| `search_preprints` | 3 | medrxiv | Q2: Emerging research signals |
| `search_approved_drugs` | 3 | openfda | Q2: Existing approved therapies |
| `compare_trials` | 0 | clinicaltrials | Q3: Side-by-side comparison |
| `get_trial_density` | 0 | clinicaltrials | Q4: Foundation for whitespace |
| `find_whitespaces` | 0 | clinicaltrials | Q4: Underserved segments |
| `competitive_landscape` | 0 | clinicaltrials | Q1, Q4: Who is active where |
| `get_recruitment_velocity` | 0 | clinicaltrials | Q5: Enrollment feasibility |
| `suggest_trial_design` | 4 | multi-source | Design intelligence |
| `suggest_patient_profile` | 4 | multi-source | Recruitment intelligence |
| `benchmark_trial_design` | 5 | clinicaltrials | Benchmark protocol archetypes |
| `benchmark_eligibility_criteria` | 5 | clinicaltrials | Benchmark inclusion and exclusion logic |
| `benchmark_endpoints` | 5 | clinicaltrials | Benchmark endpoint strategy |
| `link_trial_evidence` | 5 | multi-source | Connect trial to literature and labels |
| `analyze_patient_segments` | 5 | clinicaltrials | Segment-level crowding and whitespace |
| `forecast_readouts` | 5 | clinicaltrials | Estimate near-term readout windows |
| `track_competitor_assets` | 5 | clinicaltrials | Track sponsor assets and phases |
| `summarize_safety_signals` | 5 | multi-source | Summarize recurring safety themes |
| `investigator_site_landscape` | 5 | clinicaltrials | Inspect site and official footprint |
| `watch_indication_signals` | 5 | multi-source | Watchlist snapshot for recurring monitoring |

---

## Data Sources

### Source Metadata

Every tool response includes a `_meta` block that tells the LLM
how to weigh and contextualize the data:

```json
{
  "_meta": {
    "source": "clinicaltrials",
    "data_type": "trial_registry",
    "quality_note": "Sponsor-reported. Results only for trials that chose to report outcomes.",
    "coverage": "US-focused. International trials may be missing.",
    "update_frequency": "Daily",
    "auth_required": false
  }
}
```

### Source Reference

| Source | Base URL | Auth | Rate Limit | Format |
|--------|----------|------|-----------|--------|
| ClinicalTrials.gov v2 | `https://clinicaltrials.gov/api/v2` | None | 10 req/s | JSON |
| PubMed E-utils | `https://eutils.ncbi.nlm.nih.gov/entrez/eutils` | Optional | 3–10 req/s | JSON + XML |
| OpenFDA | `https://api.fda.gov/drug` | None | 240 req/min | JSON |
| WHO ICTRP | `https://trialsearch.who.int/API` | None | Best effort | JSON |
| medRxiv | `https://api.medrxiv.org` | None | Best effort | JSON |

### PubMed Integration

PubMed uses the NCBI E-utilities API with a mandatory two-step process:

```text
Step 1: esearch.fcgi  →  returns list of PMIDs (JSON)
Step 2: efetch.fcgi   →  returns full records for those PMIDs (XML)
```

Rate limit without API key: 3 requests/second.
Current implementation waits 0.4s between esearch and efetch calls.

Supported search parameters: `query`, `max_results`, `year_from`

---

## Models

All source adapters normalize responses into shared Pydantic models
defined in `src/Medical_Wizard_MCP/models/trials.py`.

### Trial

| Field | Type | Source |
|-------|------|--------|
| `id` | str | all |
| `title` | str | all |
| `source` | str | all |
| `status` | str | CT.gov, WHO |
| `phase` | str | CT.gov, WHO |
| `sponsor` | str | CT.gov, WHO |
| `condition` | str | CT.gov, WHO |
| `intervention` | str | CT.gov |
| `start_date` | str | CT.gov, WHO |
| `completion_date` | str | CT.gov |
| `enrollment` | int | CT.gov |
| `primary_endpoint` | str | CT.gov |
| `biomarkers` | list[str] | CT.gov |
| `why_stopped` | str | CT.gov only |
| `country` | str | WHO only |

### Publication

| Field | Type | Source |
|-------|------|--------|
| `pmid` | str | PubMed |
| `title` | str | PubMed, medRxiv |
| `source` | str | all |
| `abstract` | str | PubMed, medRxiv |
| `journal` | str | PubMed |
| `year` | str | PubMed, medRxiv |
| `authors` | list[str] | PubMed, medRxiv |
| `doi` | str | PubMed |
| `mesh_terms` | list[str] | PubMed only |

### ApprovedDrug

| Field | Type | Source |
|-------|------|--------|
| `brand_name` | str | OpenFDA |
| `generic_name` | str | OpenFDA |
| `source` | str | all |
| `indication` | str | OpenFDA |
| `approval_date` | str | OpenFDA |
| `sponsor` | str | OpenFDA |
| `application_number` | str | OpenFDA |

---

## Debugging MCP Locally

The most effective local debugging flow is:

1. Run the server with debug logging in one terminal:

```bash
FASTMCP_LOG_LEVEL=DEBUG ./local-dev/run-server.sh
```

2. Launch MCP Inspector in a second terminal:

```bash
npx -y @modelcontextprotocol/inspector
```

3. In the Inspector UI, connect with:
- Transport: `Streamable HTTP`
- URL: `http://127.0.0.1:8000/mcp`

Use Inspector to:
- verify tool discovery
- inspect tool input schemas
- execute tools manually with small test inputs
- inspect raw outputs
- watch notifications and logs while requests run

Recommended first checks:
- `search_publications(query="mrna cancer vaccine", max_results=2)`
- `search_trials(condition="glioblastoma", max_results=2)`
- `get_trial_timelines(condition="NSCLC", max_results=2)`

Notes:
- `GET /` returning `404 Not Found` is expected. The MCP endpoint is `/mcp`, not `/`.
- Inspector is the best tool for protocol and tool debugging.
- Codex is better as a second step, once the server already works correctly in Inspector.

## Testing

### Run all tests

```bash
uv run pytest
```

Without `uv`:

```bash
python -m pytest
```

### Run PubMed unit tests

```bash
uv run pytest tests/test_pubmed.py
```

Without `uv`:

```bash
.venv/bin/python -m pytest tests/test_pubmed.py
```

Current PubMed test coverage:
- successful `esearch → efetch` flow
- `year_from` date filtering
- XML normalization for authors, journal, date, abstract
- empty search results
- HTTP failure handling
- invalid XML handling

### Run live smoke test

```bash
RUN_LIVE_PUBMED=1 python -m pytest tests/test_pubmed_live.py -s
```

Optional parameters:

```bash
RUN_LIVE_PUBMED=1 \
PUBMED_LIVE_QUERY="personalized cancer vaccine melanoma" \
PUBMED_LIVE_MAX_RESULTS=5 \
PUBMED_LIVE_YEAR_FROM=2023 \
python -m pytest tests/test_pubmed_live.py -s
```

---

## Contributor Guidelines

### Adding a new source

1. Extend `BaseSource` in `sources/base.py`
2. Implement `search()`, `fetch_by_id()`, `get_metadata()`
3. Keep all HTTP and parsing logic inside the source
4. Normalize into shared Pydantic models only
5. Set `source` field on every returned record
6. Use `DataSourceError` for all HTTP failures
7. Register the source in `__main__.py`
8. Add a thin MCP tool in `tools/` only if a new capability is needed

### Adding a new tool

1. Define the tool in the appropriate file under `tools/`
2. Follow the `_wrap_response` envelope pattern
3. Write a docstring that tells the LLM exactly when to call this tool
4. Handle `DataSourceError` and return a structured error dict
5. Test the tool in isolation before integration

### Design rules

- prefer small, composable tools over large multi-purpose ones
- no analytics or interpretation logic in `sources/` or `tools/`
- always include `_meta` in tool responses
- fields not provided by a source are explicitly `None`, never omitted
- `source` field is mandatory on every model instance

---

## Roadmap

### Stufe 0 – Hackathon MVP (current)

The current server exposes 23 MCP tools across trial search, publications,
benchmarking, evidence linking, competitive tracking, and watchlist workflows.
The architecture remains LLM-first with no database, frontend, or caching layer.

### Stufe 1 – Visualization Layer

Claude generates visual artifacts on-the-fly from tool output:
competitive landscape maps, trial timelines, pipeline comparisons,
enrollment heatmaps. No predefined templates – Claude chooses
the right visualization for the question.

### Stufe 2 – Semantic Retrieval via Vector Store

Trial descriptions, outcomes, abstracts, and failure reasons indexed
as embeddings in Qdrant. Enables questions impossible with keyword
search alone:

- "Find trials with a similar mechanism of action to our approach"
- "Which trials failed at comparable endpoints?"
- "What publications describe mechanisms complementary to mRNA?"

Architecture: Qdrant vector store populated from existing tool responses.
No new source clients needed. The MCP tools retain identical signatures –
only the source layer is swapped from live API to vector lookup.

### Stufe 3 – Extended Data Sources

Each new source adds one client and one tool:
- `openfda.py` → `search_approved_drugs`
- `who_ictrp.py` → `search_international_trials`
- `medrxiv.py` → `search_preprints`

### Stufe 4 – Analysis Templates and Trial Design Intelligence

Pre-built MCP prompts for recurring analyses:
- "Competitive landscape for [indication]"
- "Trial design recommendation based on failure patterns"
- "White space analysis: where are there no active trials?"

Standardized JSON output schemas for versioning and export.
Plus `suggest_trial_design` and `suggest_patient_profile` tools
that combine multiple sources into actionable recommendations.
