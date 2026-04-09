from __future__ import annotations

import pytest

from Medical_Wizard_MCP.models import ApprovedDrug, Publication, TrialDetail, TrialSummary, TrialTimeline
from Medical_Wizard_MCP.sources.registry import DetailQueryResult, ListQueryResult, SourceWarning
from Medical_Wizard_MCP.tools.catalog import describe_tools
from Medical_Wizard_MCP.tools.drugs import search_approved_drugs
from Medical_Wizard_MCP.tools.publications import search_preprints, search_publications
from Medical_Wizard_MCP.tools.search import get_trial_details, search_trials
from Medical_Wizard_MCP.tools.timelines import get_trial_timelines


@pytest.mark.asyncio
async def test_search_trials_returns_list_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_search_trials(**_: object) -> ListQueryResult[TrialSummary]:
        return ListQueryResult(
            queried_sources=["clinicaltrials_gov"],
            warnings=[],
            items=[
                TrialSummary(
                    source="clinicaltrials_gov",
                    nct_id="NCT123",
                    brief_title="Example Trial",
                    phase="Phase 2",
                    overall_status="RECRUITING",
                    lead_sponsor="BioNTech",
                    interventions=["BNT111"],
                    primary_outcomes=["ORR"],
                    enrollment_count=120,
                )
            ],
        )

    monkeypatch.setattr(
        "Medical_Wizard_MCP.tools.search.registry.search_trials",
        fake_search_trials,
    )

    response = await search_trials(indication="lung cancer")

    assert response["count"] == 1
    assert response["_meta"]["tool"] == "search_trials"
    assert response["_meta"]["tool_category"] == "discovery"
    assert response["_meta"]["output_kind"] == "raw"
    assert response["_meta"]["source"] == "clinicaltrials_gov"
    assert response["_meta"]["sources"] == ["clinicaltrials_gov"]
    assert response["_meta"]["queried_sources"] == ["clinicaltrials_gov"]
    assert response["_meta"]["evidence_sources"] == ["clinicaltrials_gov"]
    assert response["_meta"]["evidence_trace"][0]["step"] == "search_trial_registry"
    assert response["_meta"]["evidence_trace"][0]["evidence_refs"][0]["url"].endswith("/NCT123")
    assert response["_meta"]["evidence_refs"][0]["id"] == "NCT123"
    assert response["_meta"]["requested_filters"]["indication"] == "lung cancer"
    assert response["results"][0]["nct_id"] == "NCT123"


@pytest.mark.asyncio
async def test_get_trial_details_returns_detail_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get_trial_details(_: str) -> DetailQueryResult[TrialDetail]:
        return DetailQueryResult(
            queried_sources=["clinicaltrials_gov"],
            warnings=[],
            item=TrialDetail(
                source="clinicaltrials_gov",
                nct_id="NCT00000123",
                brief_title="Example Trial",
                phase="Phase 2",
                overall_status="COMPLETED",
                lead_sponsor="BioNTech",
                interventions=["BNT111"],
                primary_outcomes=["ORR"],
                enrollment_count=120,
                official_title="Official Example Trial",
                eligibility_criteria="Adults only",
                arms=["Treatment"],
                secondary_outcomes=["PFS"],
                study_type="INTERVENTIONAL",
                conditions=["NSCLC"],
            ),
        )

    monkeypatch.setattr(
        "Medical_Wizard_MCP.tools.search.registry.get_trial_details",
        fake_get_trial_details,
    )

    response = await get_trial_details("NCT00000123")

    assert response["_meta"]["tool"] == "get_trial_details"
    assert response["_meta"]["routing_hints"]["requires_identifiers"] == ["nct_id"]
    assert response["_meta"]["evidence_sources"] == ["clinicaltrials_gov"]
    assert response["_meta"]["evidence_trace"][0]["step"] == "fetch_trial_detail"
    assert response["_meta"]["evidence_refs"][0]["url"].endswith("/NCT00000123")
    assert response["result"]["nct_id"] == "NCT00000123"
    assert "message" not in response


@pytest.mark.asyncio
async def test_get_trial_details_missing_returns_null_result(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get_trial_details(_: str) -> DetailQueryResult[TrialDetail]:
        return DetailQueryResult(item=None, queried_sources=["clinicaltrials_gov"], warnings=[])

    monkeypatch.setattr(
        "Medical_Wizard_MCP.tools.search.registry.get_trial_details",
        fake_get_trial_details,
    )

    response = await get_trial_details("NCT00000404")

    assert response["result"] is None
    assert response["message"] == "No trial found with ID NCT00000404"


@pytest.mark.asyncio
async def test_list_tools_use_standard_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get_trial_timelines(**_: object) -> ListQueryResult[TrialTimeline]:
        return ListQueryResult(
            queried_sources=["clinicaltrials_gov"],
            warnings=[],
            items=[
                TrialTimeline(
                    source="clinicaltrials_gov",
                    nct_id="NCT321",
                    brief_title="Timeline Trial",
                    phase="Phase 1",
                    lead_sponsor="Merck",
                    start_date="2024-01-01",
                    primary_completion_date="2025-01-01",
                    completion_date="2025-06-01",
                    enrollment_count=20,
                )
            ],
        )

    async def fake_search_publications(**_: object) -> ListQueryResult[Publication]:
        return ListQueryResult(
            queried_sources=["pubmed"],
            warnings=[],
            items=[
                Publication(
                    source="pubmed",
                    pmid="12345",
                    title="Example Publication",
                    authors=["Alice Smith"],
                    journal="Nature Medicine",
                    pub_date="2024-01-01",
                    abstract="Example abstract.",
                    doi="10.1000/example",
                    mesh_terms=["Vaccines, mRNA"],
                )
            ],
        )

    monkeypatch.setattr(
        "Medical_Wizard_MCP.tools.timelines.registry.get_trial_timelines",
        fake_get_trial_timelines,
    )
    monkeypatch.setattr(
        "Medical_Wizard_MCP.tools.publications.registry.search_publications",
        fake_search_publications,
    )

    timeline_response = await get_trial_timelines(indication="NSCLC")
    publication_response = await search_publications(query="mRNA")

    assert timeline_response["count"] == 1
    assert timeline_response["_meta"]["tool"] == "get_trial_timelines"
    assert timeline_response["_meta"]["output_kind"] == "derived"
    assert timeline_response["_meta"]["evidence_trace"][1]["step"] == "derive_duration_metrics"
    assert timeline_response["_meta"]["evidence_refs"][0]["id"] == "NCT321"
    assert timeline_response["results"][0]["nct_id"] == "NCT321"

    assert publication_response["count"] == 1
    assert publication_response["_meta"]["tool"] == "search_publications"
    assert publication_response["_meta"]["routing_hints"]["parameter_aliases"]["term"] == "query"
    assert publication_response["_meta"]["evidence_sources"] == ["pubmed"]
    assert publication_response["_meta"]["evidence_refs"][0]["url"] == "https://pubmed.ncbi.nlm.nih.gov/12345/"
    assert publication_response["results"][0]["pmid"] == "12345"
    assert publication_response["results"][0]["doi"] == "10.1000/example"


@pytest.mark.asyncio
async def test_search_publications_supports_term_and_reports_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_search_publications(**_: object) -> ListQueryResult[Publication]:
        return ListQueryResult(
            queried_sources=["pubmed"],
            warnings=[
                SourceWarning(
                    source="pubmed",
                    stage="search_publications",
                    error="temporary upstream issue",
                )
            ],
            items=[],
        )

    monkeypatch.setattr(
        "Medical_Wizard_MCP.tools.publications.registry.search_publications",
        fake_search_publications,
    )

    response = await search_publications(term="mRNA vaccine", indication="NSCLC")

    assert response["_meta"]["queried_sources"] == ["pubmed"]
    assert response["_meta"]["requested_filters"]["term"] == "mRNA vaccine"
    assert response["_meta"]["requested_filters"]["indication"] == "NSCLC"
    assert response["_meta"]["requested_filters"]["effective_query"] == "mRNA vaccine NSCLC"
    assert response["_meta"]["evidence_trace"][0]["step"] == "search_pubmed"
    assert response["_meta"]["partial_failures"][0]["error"] == "temporary upstream issue"


@pytest.mark.asyncio
async def test_get_trial_details_rejects_invalid_id() -> None:
    response = await get_trial_details("FDA:123")

    assert response["result"] is None
    assert "Invalid trial ID" in response["message"]
    assert response["_meta"]["partial_failures"][0]["source"] == "tool_validation"


@pytest.mark.asyncio
async def test_search_approved_drugs_returns_standard_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_search_approved_drugs(**_: object) -> ListQueryResult[ApprovedDrug]:
        return ListQueryResult(
            queried_sources=["openfda"],
            warnings=[],
            items=[
                ApprovedDrug(
                    source="openfda",
                    approval_id="BLA123456",
                    brand_name="ExampleDrug",
                    generic_name="example-generic",
                    indication="NSCLC",
                    sponsor="Example Pharma",
                    route=["INTRAVENOUS"],
                    product_type="HUMAN PRESCRIPTION DRUG",
                    substance_names=["example-substance"],
                    mechanism_of_action="Blocks example target.",
                )
            ],
        )

    monkeypatch.setattr(
        "Medical_Wizard_MCP.tools.drugs.registry.search_approved_drugs",
        fake_search_approved_drugs,
    )

    response = await search_approved_drugs(indication="NSCLC", sponsor="Example Pharma")

    assert response["count"] == 1
    assert response["_meta"]["tool"] == "search_approved_drugs"
    assert response["_meta"]["source"] == "openfda"
    assert response["_meta"]["requested_filters"]["indication"] == "NSCLC"
    assert response["results"][0]["approval_id"] == "BLA123456"


@pytest.mark.asyncio
async def test_search_preprints_returns_standard_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_search_preprints(**_: object) -> ListQueryResult[Publication]:
        return ListQueryResult(
            queried_sources=["medrxiv"],
            warnings=[],
            items=[
                Publication(
                    source="medrxiv",
                    pmid=None,
                    title="Early mRNA vaccine signal in GBM",
                    authors=["Alice Smith", "Bob Jones"],
                    journal="medRxiv",
                    pub_date="2024-03-01",
                    abstract="Promising early translational data.",
                    doi="10.1101/2024.03.01.123456",
                    mesh_terms=["Cancer Biology"],
                )
            ],
        )

    monkeypatch.setattr(
        "Medical_Wizard_MCP.tools.publications.registry.search_preprints",
        fake_search_preprints,
    )

    response = await search_preprints(term="mRNA vaccine", indication="GBM")

    assert response["count"] == 1
    assert response["_meta"]["tool"] == "search_preprints"
    assert response["_meta"]["source"] == "medrxiv"
    assert response["_meta"]["requested_filters"]["term"] == "mRNA vaccine"
    assert response["_meta"]["requested_filters"]["indication"] == "GBM"
    assert response["_meta"]["requested_filters"]["effective_query"] == "mRNA vaccine GBM"
    assert response["_meta"]["evidence_trace"][0]["step"] == "search_medrxiv"
    assert response["_meta"]["evidence_refs"][0]["url"] == "https://doi.org/10.1101/2024.03.01.123456"
    assert response["results"][0]["pmid"] is None
    assert response["results"][0]["doi"] == "10.1101/2024.03.01.123456"


@pytest.mark.asyncio
async def test_describe_tools_returns_structured_catalog() -> None:
    response = await describe_tools(category="discovery")

    assert response["_meta"]["tool"] == "describe_tools"
    assert response["_meta"]["source"] == "server_catalog"
    assert response["count"] >= 1
    assert any(item["tool_name"] == "search_trials" for item in response["results"])
