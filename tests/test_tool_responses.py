from __future__ import annotations

import pytest

from Medical_Wizard_MCP.models import ApprovedDrug, ConferenceAbstract, Publication, TrialDetail, TrialSummary, TrialTimeline
from Medical_Wizard_MCP.sources.registry import DetailQueryResult, ListQueryResult, SourceWarning
from Medical_Wizard_MCP.tools.catalog import describe_tools
from Medical_Wizard_MCP.tools.conferences import search_conference_abstracts
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
    assert response["_meta"]["attribution_guidance"]["result_ref_field"] == "source_refs"
    assert response["results"][0]["source_refs"][0]["id"] == "NCT123"
    assert response["_meta"]["requested_filters"]["indication"] == "lung cancer"
    assert response["results"][0]["nct_id"] == "NCT123"


@pytest.mark.asyncio
async def test_search_trials_accepts_named_trial_query(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_calls: list[dict[str, object]] = []

    async def fake_search_trials(**kwargs: object) -> ListQueryResult[TrialSummary]:
        captured_calls.append(dict(kwargs))
        query = str(kwargs.get("query"))
        items = []
        if query.lower() in {"rosetta-lung", "rosetta lung", "rosettalung"}:
            items = [
                TrialSummary(
                    source="clinicaltrials_gov",
                    nct_id="NCT99999999",
                    brief_title="ROSETTA-Lung",
                    phase="Phase 3",
                    overall_status="COMPLETED",
                    lead_sponsor="BioNTech",
                    interventions=["Investigational arm"],
                    primary_outcomes=["OS"],
                    enrollment_count=300,
                )
            ]
        return ListQueryResult(
            queried_sources=["clinicaltrials_gov"],
            warnings=[],
            items=items,
        )

    monkeypatch.setattr(
        "Medical_Wizard_MCP.tools.search.registry.search_trials",
        fake_search_trials,
    )

    response = await search_trials(query="ROSETTA Lung clinical trial")

    queried_variants = [str(call["query"]) for call in captured_calls]
    assert "ROSETTA Lung clinical trial" in queried_variants
    assert any(variant.lower() == "rosetta-lung" for variant in queried_variants)
    assert response["count"] == 1
    assert response["_meta"]["requested_filters"]["effective_query"] == "ROSETTA Lung clinical trial"
    assert response["_meta"]["evidence_trace"][0]["filters"]["query_variants"]
    assert response["results"][0]["brief_title"] == "ROSETTA-Lung"


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
    assert response["result"]["source_refs"][0]["id"] == "NCT00000123"
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
    assert publication_response["results"][0]["source_refs"][0]["id"] == "12345"
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
async def test_search_conference_abstracts_returns_standard_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_search_conference_abstracts(**_: object) -> ListQueryResult[ConferenceAbstract]:
        return ListQueryResult(
            queried_sources=["openalex", "crossref"],
            warnings=[],
            items=[
                ConferenceAbstract(
                    source="crossref",
                    source_id="10.0000/meeting-tips",
                    title="ASCO Annual Meeting Tips",
                    authors=["Editorial Team"],
                    conference_name="ASCO Annual Meeting",
                    conference_series="ASCO",
                    presentation_type=None,
                    abstract_number=None,
                    publication_year=2025,
                    publication_date="2025-06-01",
                    abstract="",
                    doi="10.0000/meeting-tips",
                    url="https://doi.org/10.0000/meeting-tips",
                    journal="Oncology News",
                ),
                ConferenceAbstract(
                    source="openalex",
                    source_id="https://openalex.org/W123",
                    title="Late-breaking ASCO abstract for individualized neoantigen therapy in melanoma",
                    authors=["Alice Smith", "Bob Jones"],
                    conference_name="ASCO Annual Meeting",
                    conference_series="ASCO",
                    presentation_type="late-breaking abstract",
                    abstract_number="2501",
                    publication_year=2025,
                    publication_date="2025-06-01",
                    abstract="Encouraging translational signal in biomarker-enriched cohorts.",
                    doi="10.1200/JCO.2025.2501",
                    url="https://doi.org/10.1200/JCO.2025.2501",
                    journal="Journal of Clinical Oncology",
                )
            ],
        )

    monkeypatch.setattr(
        "Medical_Wizard_MCP.tools.conferences.registry.search_conference_abstracts",
        fake_search_conference_abstracts,
    )

    response = await search_conference_abstracts(
        term="neoantigen therapy",
        indication="melanoma",
        conference_series=["ASCO", "AACR"],
    )

    assert response["count"] == 1
    assert response["_meta"]["tool"] == "search_conference_abstracts"
    assert response["_meta"]["tool_family"] == "conferences"
    assert response["_meta"]["output_kind"] == "raw"
    assert response["_meta"]["queried_sources"] == ["crossref", "openalex"]
    assert response["_meta"]["requested_filters"]["effective_query"] == "neoantigen therapy melanoma"
    assert response["_meta"]["requested_filters"]["conference_series"] == ["ASCO", "AACR"]
    assert response["_meta"]["requested_filters"]["minimum_conference_result_score"] == 0.55
    assert response["_meta"]["evidence_trace"][0]["step"] == "search_conference_sources"
    assert response["_meta"]["evidence_trace"][1]["step"] == "rank_conference_results"
    assert any(
        ref["url"] == "https://doi.org/10.1200/JCO.2025.2501"
        for ref in response["_meta"]["evidence_refs"]
    )
    assert response["results"][0]["title"].startswith("Late-breaking ASCO abstract")
    assert response["results"][0]["conference_series"] == "ASCO"
    assert response["results"][0]["conference_result_score"] >= 0.55
    assert response["results"][0]["source_refs"][0]["id"] == "https://openalex.org/W123"


@pytest.mark.asyncio
async def test_describe_tools_returns_structured_catalog() -> None:
    response = await describe_tools(category="discovery")

    assert response["_meta"]["tool"] == "describe_tools"
    assert response["_meta"]["source"] == "server_catalog"
    assert response["count"] >= 1
    assert any(item["tool_name"] == "search_trials" for item in response["results"])
