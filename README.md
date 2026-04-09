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

## Alle MCP Endpoints - Vollstaendige Uebersicht

### Stufe 0 - MVP

#### `search_trials`
**Zweck:** Trials nach Indikation, Phase, Status, Sponsor finden

**Input:** `condition`, `phase?`, `status?`, `sponsor?`, `max_results?`

**Output:** `Trial[]` -> `id`, `title`, `sponsor`, `phase`, `status`, `dates`

**Source:** `clinicaltrials.py`

**Wann:**
- "Welche Phase-3 NSCLC Trials rekrutieren gerade?"
- "Was hat Merck aktuell in der Pipeline?"

#### `get_trial_details`
**Zweck:** Vollstaendige Informationen zu einem spezifischen Trial

**Input:** `nct_id`

**Output:** Trial komplett -> `endpoints`, `biomarker`, `eligibility`, `interventions`, `enrollment`, `why_stopped`

**Source:** `clinicaltrials.py`

**Wann:**
- "Zeig mir alles zu NCT04179552"
- "Was sind die Einschlusskriterien dieses Trials?"

#### `get_trial_timeline`
**Zweck:** Zeitliche Daten fuer Velocity- und Market-Timing-Analyse

**Input:** `condition`, `sponsor?`, `phase?`

**Output:** `Trial[]` -> `nct_id`, `sponsor`, `phase`, `start_date`, `primary_completion_date`, `status`

**Source:** `clinicaltrials.py`

**Wann:**
- "Wie schnell ist Merck durch die Phasen in NSCLC?"
- "Welche Trials koennten bis 2028 zugelassen werden?"
- "Wie lange dauern Phase-2-Trials in GBM durchschnittlich?"

#### `search_publications`
**Zweck:** Peer-reviewed Ergebnisse und Outcomes aus PubMed

**Input:** `term`, `indication?`, `year_from?`, `max_results?`

**Output:** `Publication[]` -> `pmid`, `title`, `abstract`, `journal`, `year`, `authors`, `doi`, `mesh_terms`

**Source:** `pubmed.py`

**Wann:**
- "Was wurde ueber mRNA Vakzine in Lungenkrebs publiziert?"
- "Welche Outcomes gibt es zu PD-1 Inhibitoren in GBM?"
- "Was sind die publizierten Ergebnisse dieses Trials?"

#### `get_trial_density`
**Zweck:** Aggregierte Zaehlungen fuer Verteilungsanalyse als Basis fuer `find_whitespaces` und `competitive_landscape`

**Input:** `indication`, `group_by` (`"phase"` | `"intervention_type"` | `"sponsor"`)

**Output:**

```json
{
  "indication": "str",
  "group_by": "str",
  "distribution": {
    "PHASE1": 89,
    "PHASE2": 54
  },
  "total": 143
}
```

**Source:** `clinicaltrials.py` (`countTotal=true`, mehrere Calls)

**Wann:**
- "Wie viele Trials gibt es pro Phase in Pankreaskrebs?"
- "Welche Mechanismen dominieren in NSCLC?"

#### `find_whitespaces`
**Zweck:** Identifiziert unterbesetzte Felder im Indikation x Phase x Mechanismus Raum

**Input:** `indication`, `compare_mechanism?` (default: `true`)

**Output:**

```json
{
  "indication": "str",
  "density_by_phase": {},
  "density_by_mechanism": {
    "PD-1 Inhibitor": 34,
    "mRNA Vaccine": 3,
    "CAR-T": 1
  },
  "terminated_count": 0,
  "whitespace_signals": [
    {
      "mechanism": "mRNA Vaccine",
      "phase": "PHASE3",
      "trial_count": 1,
      "signal_strength": "HIGH"
    }
  ]
}
```

**Source:** `clinicaltrials.py` (intern: `get_trial_density` + `search_trials` `TERMINATED`)

**Wann:**
- "Wo gibt es noch keine Konkurrenz in Pankreaskrebs?"
- "Wo koennte BioNTechs mRNA Plattform noch eingesetzt werden?"

#### `competitive_landscape`
**Zweck:** Vollstaendiges Wettbewerbsbild einer Indikation - wer macht was, in welcher Phase, mit welchem Ansatz

**Input:** `indication`, `phase?`

**Output:**

```json
{
  "indication": "str",
  "sponsors": [
    {
      "name": "Merck",
      "active_trials": 6,
      "phases": ["PHASE2", "PHASE3"],
      "mechanisms": ["PD-1", "Bispecific"],
      "furthest_phase": "PHASE3"
    }
  ],
  "dominant_mechanisms": [],
  "saturation_score": "HIGH",
  "total_active_trials": 6
}
```

**Source:** `clinicaltrials.py` (intern: `search_trials` + `get_trial_density`)

**Wann:**
- "Wer ist aktiv in NSCLC und in welcher Phase?"
- "Wie gesaettigt ist der Brustkrebs Markt?"
- "Vergleiche BioNTech vs Merck in NSCLC"

### Stufe 3 - Erweiterte Datenquellen

#### `search_approved_drugs`
**Zweck:** Bereits zugelassene Therapien pro Indikation

**Input:** `indication`, `year_from?`

**Output:** `ApprovedDrug[]` -> `brand_name`, `generic_name`, `indication`, `approval_date`, `sponsor`

**Source:** `openfda.py`

**Wann:**
- "Was ist bereits zugelassen in NSCLC?"
- "Gegen welche Therapien muss BioNTech sich behaupten?"

#### `search_international_trials`
**Zweck:** Internationale Trials, die auf CT.gov unsichtbar sind, besonders China (ChiCTR) und EU-Registries

**Input:** `condition`, `country?`

**Output:** `Trial[]` (gleiches Schema wie `search_trials`)

**Source:** `who_ictrp.py`

**Wann:**
- "Was machen chinesische Firmen in GBM?"
- "Gibt es EU-Trials die wir noch nicht kennen?"

#### `search_preprints`
**Zweck:** Noch nicht peer-reviewte Forschung als Fruehindikator

**Input:** `term`, `indication?`, `year_from?`

**Output:** `Publication[]` (gleiches Schema wie `search_publications`)

**Source:** `medrxiv.py`

**Wann:**
- "Was wird gerade erforscht aber noch nicht publiziert?"
- "Gibt es fruehe Signale fuer neue Ansaetze in GBM?"

### Stufe 4 - Trial Design Intelligence

#### `suggest_trial_design`
**Zweck:** Datengetriebener Trial Blueprint basierend auf Whitespace-Analyse + Failure Patterns + Velocity

**Input:** `indication`, `mechanism`

**Output:**

```json
{
  "indication": "str",
  "mechanism": "str",
  "recommended_phase": "str",
  "enrollment": 0,
  "primary_endpoint": "str",
  "biomarkers": [],
  "combination_therapy": "str",
  "rationale": {
    "whitespace_basis": [],
    "failure_learnings": [],
    "velocity_window": "str"
  },
  "reference_trials": [],
  "confidence_score": 0.0
}
```

**Source:** intern: `search_trials` + `get_trial_details` + `search_publications` + `find_whitespaces`

**Wann:**
- "Wie sollte das Trial designed sein?"
- "Was empfiehlst du fuer einen GBM mRNA Trial?"

#### `suggest_patient_profile`
**Zweck:** Optimales Patientenprofil basierend auf dem, was in aehnlichen Trials funktioniert hat

**Input:** `indication`, `mechanism`, `biomarker?`

**Output:**

```json
{
  "inclusion_criteria": [],
  "exclusion_criteria": [],
  "predictive_biomarkers": [
    {
      "marker": "TMB-high",
      "response_rate": 0.34,
      "vs_unselected": 0.12,
      "evidence_trials": 8
    }
  ],
  "recommended_ecog": "str",
  "estimated_response_rate": 0.0,
  "based_on_trials": 0
}
```

**Source:** intern: `get_trial_details` (completed) + `search_publications`

**Wann:**
- "Wen sollen wir fuer die Studie rekrutieren?"
- "Welche Patienten sprechen am besten an?"

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
