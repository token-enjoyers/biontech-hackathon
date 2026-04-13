from __future__ import annotations

import pytest

from Medical_Wizard_MCP.models import Publication, TrialDetail, TrialSummary
from Medical_Wizard_MCP.sources.registry import DetailQueryResult, ListQueryResult
from Medical_Wizard_MCP.tools.intelligence import link_trial_evidence
from Medical_Wizard_MCP.tools.search import get_trial_details, search_trials


ROSETTA_TRIAL = TrialSummary(
    source="clinicaltrials_gov",
    nct_id="NCT09990001",
    brief_title="ROSETTA-Lung",
    phase="Phase 3",
    overall_status="COMPLETED",
    lead_sponsor="Company",
    interventions=["BNT327"],
    primary_outcomes=["Overall survival"],
    enrollment_count=420,
)

ROSETTA_DETAIL = TrialDetail(
    **ROSETTA_TRIAL.model_dump(),
    official_title="A phase 3 study of ROSETTA-Lung in advanced NSCLC",
    eligibility_criteria="Adults with advanced NSCLC and measurable disease.",
    arms=[
        "ROSETTA-Lung investigational arm",
        "Pembrolizumab comparator arm",
        "Platinum-doublet chemotherapy comparator arm",
    ],
    secondary_outcomes=["Progression-free survival"],
    study_type="INTERVENTIONAL",
    conditions=["NSCLC"],
)

LATEST_PUBLICATION = Publication(
    source="pubmed",
    pmid="424242",
    title="Latest ROSETTA-Lung efficacy update in advanced NSCLC",
    authors=["Alice Example", "Bob Example"],
    journal="Journal of Thoracic Oncology",
    pub_date="2026-02-10",
    abstract="Updated phase 3 efficacy results for ROSETTA-Lung.",
    doi="10.1000/rosetta.latest",
    mesh_terms=["NSCLC"],
)

LATEST_PREPRINT = Publication(
    source="medrxiv",
    title="ROSETTA-Lung translational biomarker update",
    authors=["Alice Example"],
    journal="medRxiv",
    pub_date="2026-01-18",
    abstract="Biomarker findings associated with ROSETTA-Lung.",
    doi="10.1101/2026.01.18.999999",
    mesh_terms=["NSCLC"],
)


@pytest.mark.asyncio
async def test_rosetta_lung_end_to_end_workflow_finds_title_only_latest_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trial_queries: list[str] = []
    publication_queries: list[str] = []
    preprint_queries: list[str] = []

    async def fake_search_trials(**kwargs: object) -> ListQueryResult[TrialSummary]:
        query = str(kwargs["query"])
        trial_queries.append(query)
        items = [ROSETTA_TRIAL] if query.lower() in {"rosetta-lung", "rosetta lung", "rosettalung"} else []
        return ListQueryResult(
            queried_sources=["clinicaltrials_gov"],
            warnings=[],
            items=items,
        )

    async def fake_get_trial_details(nct_id: str) -> DetailQueryResult[TrialDetail]:
        assert nct_id == ROSETTA_TRIAL.nct_id
        return DetailQueryResult(
            item=ROSETTA_DETAIL,
            queried_sources=["clinicaltrials_gov"],
            warnings=[],
        )

    async def fake_search_publications(**kwargs: object) -> ListQueryResult[Publication]:
        query = str(kwargs["query"])
        publication_queries.append(query)
        items = [LATEST_PUBLICATION] if query == "ROSETTA-Lung" else []
        return ListQueryResult(queried_sources=["pubmed"], warnings=[], items=items)

    async def fake_search_preprints(**kwargs: object) -> ListQueryResult[Publication]:
        query = str(kwargs["query"])
        preprint_queries.append(query)
        items = [LATEST_PREPRINT] if query == "ROSETTA-Lung" else []
        return ListQueryResult(queried_sources=["medrxiv"], warnings=[], items=items)

    monkeypatch.setattr("Medical_Wizard_MCP.tools.search.registry.search_trials", fake_search_trials)
    monkeypatch.setattr("Medical_Wizard_MCP.tools.search.registry.get_trial_details", fake_get_trial_details)
    monkeypatch.setattr("Medical_Wizard_MCP.tools.intelligence.registry.get_trial_details", fake_get_trial_details)
    monkeypatch.setattr("Medical_Wizard_MCP.tools.intelligence.registry.search_publications", fake_search_publications)
    monkeypatch.setattr("Medical_Wizard_MCP.tools.intelligence.registry.search_preprints", fake_search_preprints)

    trial_response = await search_trials(query="Rosetta Lung clinical trial")
    nct_id = trial_response["results"][0]["nct_id"]
    detail_response = await get_trial_details(nct_id)
    evidence_response = await link_trial_evidence(nct_id=nct_id, include_approvals=False)

    assert nct_id == "NCT09990001"
    assert any(query.lower() == "rosetta-lung" for query in trial_queries)
    assert detail_response["result"]["arms"] == [
        "ROSETTA-Lung investigational arm",
        "Pembrolizumab comparator arm",
        "Platinum-doublet chemotherapy comparator arm",
    ]
    assert "ROSETTA-Lung" in publication_queries
    assert "ROSETTA-Lung" in preprint_queries
    assert evidence_response["result"]["queries_used"]["publication_queries"][0] == "ROSETTA-Lung"
    assert evidence_response["result"]["queries_used"]["preprint_queries"][0] == "ROSETTA-Lung"
    assert evidence_response["result"]["evidence_summary"]["publication_count"] == 1
    assert evidence_response["result"]["evidence_summary"]["preprint_count"] == 1
    assert evidence_response["result"]["linked_publications"][0]["title"] == LATEST_PUBLICATION.title
    assert evidence_response["result"]["linked_preprints"][0]["title"] == LATEST_PREPRINT.title
    trace_steps = [step["step"] for step in evidence_response["_meta"]["evidence_trace"]]
    assert trace_steps == [
        "fetch_trial_detail",
        "search_publications",
        "search_preprints",
        "assemble_evidence_links",
    ]
