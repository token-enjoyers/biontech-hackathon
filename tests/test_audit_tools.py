from __future__ import annotations

from datetime import datetime

import pytest

from Medical_Wizard_MCP.models import ApprovedDrug, Publication, TrialDetail, TrialSummary
from Medical_Wizard_MCP.sources.registry import DetailQueryResult, ListQueryResult
from Medical_Wizard_MCP.tools._evidence_extraction import classify_claim_passage
from Medical_Wizard_MCP.tools.audit import (
    extract_structured_evidence,
    get_document_passages,
    verify_claim_evidence,
)
from Medical_Wizard_MCP.tools.drugs import search_approved_drugs
from Medical_Wizard_MCP.tools.monitoring import _since_date, track_indication_changes
from Medical_Wizard_MCP.tools.publications import search_preprints, search_publications


TRIAL = TrialSummary(
    source="clinicaltrials_gov",
    nct_id="NCT70000001",
    brief_title="mRNA vaccine plus pembrolizumab in NSCLC",
    phase="Phase 2",
    overall_status="RECRUITING",
    lead_sponsor="Company",
    interventions=["mRNA vaccine", "pembrolizumab"],
    primary_outcomes=["Objective response rate"],
    enrollment_count=120,
    start_date="2025-01-10",
    primary_completion_date="2026-06-01",
    completion_date="2026-09-01",
)

DETAIL = TrialDetail(
    **TRIAL.model_dump(),
    official_title="A randomized phase 2 study of mRNA vaccine plus pembrolizumab in NSCLC",
    eligibility_criteria="Adults 18+ with PD-L1 positive NSCLC and ECOG 0-1.",
    arms=["Combination arm", "Control arm"],
    secondary_outcomes=["Progression-free survival"],
    study_type="INTERVENTIONAL",
    conditions=["NSCLC"],
)

PUB = Publication(
    source="pubmed",
    pmid="9001",
    title="mRNA vaccine combinations improved ORR in NSCLC",
    authors=["Alice Smith"],
    journal="Nature Medicine",
    pub_date="2025-02-01",
    abstract="Objective response rate was 34% and median progression-free survival was 8.2 months in PD-L1 positive NSCLC patients treated with mRNA vaccine plus pembrolizumab (n=82, p=0.03).",
    doi="10.1000/nsclc.9001",
    mesh_terms=["Lung Neoplasms", "Vaccines, mRNA"],
)

PREPRINT = Publication(
    source="medrxiv",
    pmid=None,
    title="Early safety data for mRNA vaccine combinations",
    authors=["Bob Jones"],
    journal="medRxiv",
    pub_date="2025-03-01",
    abstract="Grade 3 adverse events occurred in 12% of patients and fatigue was manageable.",
    doi="10.1101/2025.03.01.765432",
    mesh_terms=["Cancer Biology"],
)

DRUG = ApprovedDrug(
    source="openfda",
    approval_id="BLA700001",
    brand_name="Keytruda",
    generic_name="pembrolizumab",
    indication="NSCLC",
    sponsor="Merck",
    route=["INTRAVENOUS"],
    product_type="HUMAN PRESCRIPTION DRUG",
    substance_names=["pembrolizumab"],
    mechanism_of_action="PD-1 inhibitor",
    clinical_studies_summary="Overall survival benefit was observed in PD-L1 positive NSCLC.",
    warnings="Immune-mediated pneumonitis may occur.",
    adverse_reactions="Fatigue and rash were common adverse reactions.",
)


@pytest.mark.asyncio
async def test_evidence_tools_annotate_quality(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_search_publications(**_: object) -> ListQueryResult[Publication]:
        return ListQueryResult(items=[PUB], queried_sources=["pubmed"], warnings=[])

    async def fake_search_preprints(**_: object) -> ListQueryResult[Publication]:
        return ListQueryResult(items=[PREPRINT], queried_sources=["medrxiv"], warnings=[])

    async def fake_search_approved_drugs(**_: object) -> ListQueryResult[ApprovedDrug]:
        return ListQueryResult(items=[DRUG], queried_sources=["openfda"], warnings=[])

    monkeypatch.setattr("Medical_Wizard_MCP.tools.publications.registry.search_publications", fake_search_publications)
    monkeypatch.setattr("Medical_Wizard_MCP.tools.publications.registry.search_preprints", fake_search_preprints)
    monkeypatch.setattr("Medical_Wizard_MCP.tools.drugs.registry.search_approved_drugs", fake_search_approved_drugs)

    publication_response = await search_publications(query="mRNA vaccine NSCLC")
    preprint_response = await search_preprints(query="mRNA vaccine NSCLC")
    drug_response = await search_approved_drugs(indication="NSCLC")

    assert publication_response["results"][0]["evidence_quality_tier"] in {"medium_high", "high"}
    assert publication_response["results"][0]["evidence_quality_score"] >= 0.75
    assert preprint_response["results"][0]["evidence_quality_tier"] == "low"
    assert drug_response["results"][0]["evidence_quality_tier"] == "high"


@pytest.mark.asyncio
async def test_track_indication_changes_filters_recent_records(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_search_trials(**_: object) -> ListQueryResult[TrialSummary]:
        return ListQueryResult(items=[TRIAL], queried_sources=["clinicaltrials_gov"], warnings=[])

    async def fake_search_publications(**_: object) -> ListQueryResult[Publication]:
        return ListQueryResult(items=[PUB], queried_sources=["pubmed"], warnings=[])

    async def fake_search_preprints(**_: object) -> ListQueryResult[Publication]:
        return ListQueryResult(items=[PREPRINT], queried_sources=["medrxiv"], warnings=[])

    monkeypatch.setattr("Medical_Wizard_MCP.tools.monitoring.registry.search_trials", fake_search_trials)
    monkeypatch.setattr("Medical_Wizard_MCP.tools.monitoring.registry.search_publications", fake_search_publications)
    monkeypatch.setattr("Medical_Wizard_MCP.tools.monitoring.registry.search_preprints", fake_search_preprints)

    response = await track_indication_changes(indication="NSCLC", since="2025-01-01")

    assert response["_meta"]["tool"] == "track_indication_changes"
    assert response["result"]["summary"]["new_trials_started"] == 1
    assert response["result"]["summary"]["new_publications"] == 1
    assert response["result"]["summary"]["new_preprints"] == 1
    assert response["_meta"]["evidence_trace"][-1]["step"] == "filter_recent_changes"


def test_since_date_handles_leap_day_rollover(monkeypatch: pytest.MonkeyPatch) -> None:
    class FrozenDateTime:
        @classmethod
        def now(cls, tz=None):  # noqa: ANN001
            return datetime(2024, 2, 29, tzinfo=tz)

        @classmethod
        def strptime(cls, value: str, pattern: str):  # noqa: ANN001
            return datetime.strptime(value, pattern)

    monkeypatch.setattr("Medical_Wizard_MCP.tools.monitoring.datetime", FrozenDateTime)

    assert _since_date(None, 1).date().isoformat() == "2023-02-28"


@pytest.mark.asyncio
async def test_audit_tools_bind_claims_and_extract_findings(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get_trial_details(_: str) -> DetailQueryResult[TrialDetail]:
        return DetailQueryResult(item=DETAIL, queried_sources=["clinicaltrials_gov"], warnings=[])

    async def fake_search_publications(**_: object) -> ListQueryResult[Publication]:
        return ListQueryResult(items=[PUB], queried_sources=["pubmed"], warnings=[])

    async def fake_search_preprints(**_: object) -> ListQueryResult[Publication]:
        return ListQueryResult(items=[PREPRINT], queried_sources=["medrxiv"], warnings=[])

    async def fake_search_approved_drugs(**_: object) -> ListQueryResult[ApprovedDrug]:
        return ListQueryResult(items=[DRUG], queried_sources=["openfda"], warnings=[])

    monkeypatch.setattr("Medical_Wizard_MCP.tools.audit.registry.get_trial_details", fake_get_trial_details)
    monkeypatch.setattr("Medical_Wizard_MCP.tools.audit.registry.search_publications", fake_search_publications)
    monkeypatch.setattr("Medical_Wizard_MCP.tools.audit.registry.search_preprints", fake_search_preprints)
    monkeypatch.setattr("Medical_Wizard_MCP.tools.audit.registry.search_approved_drugs", fake_search_approved_drugs)

    passage_response = await get_document_passages(
        query="objective response rate NSCLC",
        nct_id="NCT70000001",
        max_passages=5,
    )
    extraction_response = await extract_structured_evidence(
        nct_id="NCT70000001",
        indication="NSCLC",
        intervention="mRNA vaccine",
        max_documents=4,
    )
    verification_response = await verify_claim_evidence(
        claim="mRNA vaccine improved objective response rate in NSCLC",
        nct_id="NCT70000001",
        indication="NSCLC",
        intervention="mRNA vaccine",
        max_passages=6,
    )

    assert passage_response["count"] >= 1
    assert passage_response["results"][0]["document_url"].startswith("https://")
    assert extraction_response["_meta"]["tool"] == "extract_structured_evidence"
    assert extraction_response["result"]["finding_summary"]["finding_count"] >= 2
    assert any(item["endpoint_name"] == "ORR" for item in extraction_response["result"]["findings"])
    assert verification_response["result"]["verdict"] in {"supported", "mixed"}
    assert len(verification_response["result"]["supporting_evidence"]) >= 1
    assert verification_response["_meta"]["evidence_trace"][-1]["step"] == "bind_claim_to_passages"


def test_claim_classifier_does_not_treat_any_numeric_overlap_as_support() -> None:
    claim = "mRNA vaccine improved objective response rate in NSCLC"
    passage = "The median age was 64 years and 82 patients were enrolled across 12 sites."

    assert classify_claim_passage(claim, passage) == "unclear"
