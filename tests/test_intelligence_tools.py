from __future__ import annotations

import pytest

from Medical_Wizard_MCP.models import (
    ApprovedDrug,
    ConferenceAbstract,
    OncologyBurdenRecord,
    Publication,
    TrialDetail,
    TrialSummary,
    TrialTimeline,
)
from Medical_Wizard_MCP.sources.registry import DetailQueryResult, ListQueryResult
from Medical_Wizard_MCP.tools.intelligence import (
    analyze_competition_gaps,
    analyze_patient_segments,
    asset_dossier,
    benchmark_eligibility_criteria,
    benchmark_endpoints,
    benchmark_trial_design,
    burden_vs_trial_footprint,
    compare_trials,
    competitive_landscape,
    estimate_commercial_opportunity_proxy,
    forecast_readouts,
    find_whitespaces,
    get_recruitment_velocity,
    get_trial_density,
    investigator_site_landscape,
    link_trial_evidence,
    screen_trial_candidates,
    suggest_patient_profile,
    suggest_trial_design,
    summarize_safety_signals,
    track_competitor_assets,
    watch_indication_signals,
)
from Medical_Wizard_MCP.tools.timelines import get_trial_timelines


TRIAL_A = TrialSummary(
    source="clinicaltrials_gov",
    nct_id="NCT00000111",
    brief_title="mRNA vaccine plus pembrolizumab in NSCLC",
    phase="Phase 2",
    overall_status="RECRUITING",
    lead_sponsor="Merck",
    interventions=["mRNA vaccine", "pembrolizumab"],
    primary_outcomes=["Objective response rate"],
    enrollment_count=120,
    start_date="2024-01-01",
    primary_completion_date="2027-06-01",
    completion_date="2027-12-01",
)

TRIAL_B = TrialSummary(
    source="clinicaltrials_gov",
    nct_id="NCT00000222",
    brief_title="mRNA vaccine monotherapy in NSCLC",
    phase="Phase 1",
    overall_status="COMPLETED",
    lead_sponsor="BioNTech",
    interventions=["mRNA vaccine"],
    primary_outcomes=["Safety and tolerability"],
    enrollment_count=60,
    start_date="2022-01-01",
    primary_completion_date="2023-06-01",
    completion_date="2023-09-01",
)

TRIAL_C = TrialSummary(
    source="clinicaltrials_gov",
    nct_id="NCT00000333",
    brief_title="PD-1 monotherapy in NSCLC",
    phase="Phase 2",
    overall_status="TERMINATED",
    lead_sponsor="Pfizer",
    interventions=["pembrolizumab"],
    primary_outcomes=["Progression-free survival"],
    enrollment_count=180,
    start_date="2021-01-01",
    primary_completion_date="2022-01-01",
    completion_date="2022-02-01",
)

DETAIL_A = TrialDetail(
    **TRIAL_A.model_dump(),
    official_title="A randomized Phase 2 study of mRNA vaccine plus pembrolizumab in NSCLC",
    eligibility_criteria="Adults 18+; ECOG 0-1; TMB-high; measurable disease; adequate organ function. Exclusion: active autoimmune disease; untreated CNS metastases.",
    arms=["Combination arm", "Standard of care arm"],
    secondary_outcomes=["Progression-free survival"],
    study_type="INTERVENTIONAL",
    conditions=["NSCLC"],
    facility_names=["Charite", "Mayo Clinic"],
    facility_cities=["Berlin", "Rochester"],
    facility_states=["Berlin", "Minnesota"],
    location_countries=["Germany", "United States"],
    overall_officials=["Dr. Alice Smith"],
)

DETAIL_B = TrialDetail(
    **TRIAL_B.model_dump(),
    official_title="A Phase 1 study of mRNA vaccine in NSCLC",
    eligibility_criteria="Adults 18+; ECOG 0-1; measurable disease; relapsed or refractory disease after prior therapy.",
    arms=["Monotherapy arm"],
    secondary_outcomes=["Overall survival"],
    study_type="INTERVENTIONAL",
    conditions=["NSCLC"],
    facility_names=["University Hospital Cologne"],
    facility_cities=["Cologne"],
    facility_states=["North Rhine-Westphalia"],
    location_countries=["Germany"],
    overall_officials=["Dr. Bob Jones"],
)

DETAIL_C = TrialDetail(
    **TRIAL_C.model_dump(),
    official_title="A Phase 2 study of pembrolizumab monotherapy in NSCLC",
    eligibility_criteria="Adults 18+; ECOG 0-1; PD-L1 positive disease. Exclusion: prior checkpoint therapy.",
    arms=["Monotherapy arm"],
    secondary_outcomes=["Overall survival"],
    study_type="INTERVENTIONAL",
    conditions=["NSCLC"],
    why_stopped="Insufficient efficacy",
    facility_names=["Mass General"],
    facility_cities=["Boston"],
    facility_states=["Massachusetts"],
    location_countries=["United States"],
    overall_officials=["Dr. Carol Lee"],
)

ROSETTA_DETAIL = TrialDetail(
    source="clinicaltrials_gov",
    nct_id="NCT09990001",
    brief_title="ROSETTA-Lung",
    official_title="A phase 3 study of ROSETTA-Lung in advanced NSCLC",
    phase="Phase 3",
    overall_status="COMPLETED",
    lead_sponsor="BioNTech",
    interventions=["BNT327"],
    primary_outcomes=["Overall survival"],
    enrollment_count=420,
    arms=["ROSETTA-Lung arm", "Pembrolizumab comparator arm"],
    secondary_outcomes=["Progression-free survival"],
    study_type="INTERVENTIONAL",
    conditions=["NSCLC"],
)

TIMELINE_A = TrialTimeline(
    source="clinicaltrials_gov",
    nct_id="NCT00000111",
    brief_title=TRIAL_A.brief_title,
    phase=TRIAL_A.phase,
    lead_sponsor=TRIAL_A.lead_sponsor,
    overall_status=TRIAL_A.overall_status,
    start_date=TRIAL_A.start_date,
    primary_completion_date=TRIAL_A.primary_completion_date,
    completion_date=TRIAL_A.completion_date,
    enrollment_count=TRIAL_A.enrollment_count,
)

TIMELINE_B = TrialTimeline(
    source="clinicaltrials_gov",
    nct_id="NCT00000222",
    brief_title=TRIAL_B.brief_title,
    phase=TRIAL_B.phase,
    lead_sponsor=TRIAL_B.lead_sponsor,
    overall_status=TRIAL_B.overall_status,
    start_date=TRIAL_B.start_date,
    primary_completion_date=TRIAL_B.primary_completion_date,
    completion_date=TRIAL_B.completion_date,
    enrollment_count=TRIAL_B.enrollment_count,
)

TIMELINE_C = TrialTimeline(
    source="clinicaltrials_gov",
    nct_id="NCT00000333",
    brief_title=TRIAL_C.brief_title,
    phase=TRIAL_C.phase,
    lead_sponsor=TRIAL_C.lead_sponsor,
    overall_status=TRIAL_C.overall_status,
    start_date=TRIAL_C.start_date,
    primary_completion_date=TRIAL_C.primary_completion_date,
    completion_date=TRIAL_C.completion_date,
    enrollment_count=TRIAL_C.enrollment_count,
)

PUB_1 = Publication(
    source="pubmed",
    pmid="1001",
    title="mRNA vaccine strategy in NSCLC",
    authors=["Alice Smith"],
    journal="Nature Medicine",
    pub_date="2024-01-01",
    abstract="TMB-high and PD-L1 positive NSCLC patients showed promising responses to mRNA vaccine combinations.",
    doi="10.1000/pub1",
    mesh_terms=["Lung Neoplasms", "mRNA Vaccines", "Tumor Mutational Burden"],
)

PREPRINT_1 = Publication(
    source="medrxiv",
    pmid=None,
    title="Early safety signal for mRNA vaccine combinations in NSCLC",
    authors=["Bob Miller"],
    journal="medRxiv",
    pub_date="2025-02-01",
    abstract="Immune-related adverse events and fatigue were manageable in advanced NSCLC patients.",
    doi="10.1101/2025.02.01.123456",
    mesh_terms=["Cancer Biology"],
)

CONFERENCE_1 = ConferenceAbstract(
    source="europe_pmc",
    source_id="CONF-1",
    title="ASCO update for mRNA vaccine plus pembrolizumab in NSCLC",
    authors=["Example Author"],
    conference_name="ASCO Annual Meeting",
    conference_series="ASCO",
    presentation_type="oral presentation",
    abstract_number="LBA1001",
    publication_year=2025,
    publication_date="2025-06-01",
    abstract="Updated translational and clinical efficacy signal.",
    doi="10.1200/JCO.2025.LBA1001",
    url="https://doi.org/10.1200/JCO.2025.LBA1001",
    journal="Journal of Clinical Oncology",
)

BURDEN_DE = OncologyBurdenRecord(
    source="bigquery_oncology",
    dataset="oncology_burden_search",
    study="Burden dataset",
    registry="German Registry",
    country="Germany",
    sex="All",
    site="Lung",
    indicator="Mortality",
    geo_code="DE",
    year=2024,
    age_min=0,
    age_max=120,
    cases=10000.0,
    population=83000000.0,
)

BURDEN_FR = OncologyBurdenRecord(
    source="bigquery_oncology",
    dataset="oncology_burden_search",
    study="Burden dataset",
    registry="French Registry",
    country="France",
    sex="All",
    site="Lung",
    indicator="Mortality",
    geo_code="FR",
    year=2024,
    age_min=0,
    age_max=120,
    cases=9000.0,
    population=68000000.0,
)

BURDEN_ES = OncologyBurdenRecord(
    source="bigquery_oncology",
    dataset="oncology_burden_search",
    study="Burden dataset",
    registry="Spanish Registry",
    country="Spain",
    sex="All",
    site="Lung",
    indicator="Mortality",
    geo_code="ES",
    year=2024,
    age_min=0,
    age_max=120,
    cases=7000.0,
    population=48000000.0,
)

BURDEN_USA = OncologyBurdenRecord(
    source="bigquery_oncology",
    dataset="oncology_burden_search",
    study="Burden dataset",
    registry="US Registry",
    country="United States of America",
    sex="All",
    site="Lung",
    indicator="Mortality",
    geo_code="US",
    year=2024,
    age_min=0,
    age_max=120,
    cases=11000.0,
    population=333000000.0,
)

APPROVED_DRUG_1 = ApprovedDrug(
    source="openfda",
    approval_id="BLA123456",
    brand_name="Keytruda",
    generic_name="pembrolizumab",
    indication="NSCLC",
    sponsor="Merck",
    route=["INTRAVENOUS"],
    product_type="HUMAN PRESCRIPTION DRUG",
    substance_names=["pembrolizumab"],
    mechanism_of_action="PD-1 inhibitor",
    warnings="Immune-mediated pneumonitis and colitis may occur.",
    adverse_reactions="Fatigue, rash, infusion-related reactions.",
)


def _filter_trials(status: str | None = None, phase: str | None = None, intervention: str | None = None) -> list[TrialSummary]:
    trials = [TRIAL_A, TRIAL_B, TRIAL_C]
    if status:
        trials = [trial for trial in trials if trial.overall_status == status]
    if phase:
        phase_lower = phase.lower().replace(" ", "")
        trials = [trial for trial in trials if trial.phase and trial.phase.lower().replace(" ", "") == phase_lower]
    if intervention:
        needle = intervention.lower()
        trials = [
            trial
            for trial in trials
            if needle in trial.brief_title.lower() or any(needle in item.lower() for item in trial.interventions)
        ]
    return trials


@pytest.mark.asyncio
async def test_get_trial_timelines_adds_duration_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get_trial_timelines(**_: object) -> ListQueryResult[TrialTimeline]:
        return ListQueryResult(
            queried_sources=["clinicaltrials_gov"],
            warnings=[],
            items=[TIMELINE_A],
        )

    monkeypatch.setattr(
        "Medical_Wizard_MCP.tools.timelines.registry.get_trial_timelines",
        fake_get_trial_timelines,
    )

    response = await get_trial_timelines(condition="NSCLC", phase="PHASE2", status="RECRUITING")

    assert response["_meta"]["requested_filters"]["phase"] == "PHASE2"
    assert response["_meta"]["requested_filters"]["status"] == "RECRUITING"
    assert response["results"][0]["months_to_primary_completion"] is not None
    assert response["results"][0]["months_since_start"] is not None


@pytest.mark.asyncio
async def test_analysis_tools_return_expected_shapes(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_search_trials(**kwargs: object) -> ListQueryResult[TrialSummary]:
        return ListQueryResult(
            queried_sources=["clinicaltrials_gov"],
            warnings=[],
            items=_filter_trials(
                status=kwargs.get("status") if isinstance(kwargs.get("status"), str) else None,
                phase=kwargs.get("phase") if isinstance(kwargs.get("phase"), str) else None,
                intervention=kwargs.get("intervention") if isinstance(kwargs.get("intervention"), str) else None,
            ),
        )

    async def fake_get_trial_details(nct_id: str) -> DetailQueryResult[TrialDetail]:
        detail_map = {
            DETAIL_A.nct_id: DETAIL_A,
            DETAIL_B.nct_id: DETAIL_B,
            DETAIL_C.nct_id: DETAIL_C,
        }
        return DetailQueryResult(
            item=detail_map.get(nct_id),
            queried_sources=["clinicaltrials_gov"],
            warnings=[],
        )

    async def fake_get_trial_timelines(**kwargs: object) -> ListQueryResult[TrialTimeline]:
        items = [TIMELINE_A, TIMELINE_B, TIMELINE_C]
        sponsor = kwargs.get("sponsor")
        if isinstance(sponsor, str):
            items = [item for item in items if item.lead_sponsor == sponsor]
        return ListQueryResult(queried_sources=["clinicaltrials_gov"], warnings=[], items=items)

    monkeypatch.setattr("Medical_Wizard_MCP.tools.intelligence.registry.search_trials", fake_search_trials)
    monkeypatch.setattr("Medical_Wizard_MCP.tools.intelligence.registry.get_trial_details", fake_get_trial_details)
    monkeypatch.setattr("Medical_Wizard_MCP.tools.intelligence.registry.get_trial_timelines", fake_get_trial_timelines)

    comparison = await compare_trials(["NCT00000111", "NCT00000222"])
    density = await get_trial_density(indication="NSCLC", group_by="intervention_type")
    gaps = await analyze_competition_gaps(indication="NSCLC")
    whitespaces = await find_whitespaces(indication="NSCLC")
    landscape = await competitive_landscape(indication="NSCLC")
    velocity = await get_recruitment_velocity(indication="NSCLC")

    assert comparison["count"] == 2
    assert "TMB-high" in comparison["results"][0]["biomarkers"]
    assert density["result"]["distribution"]["mRNA vaccine"] >= 1
    assert gaps["_meta"]["output_kind"] == "heuristic"
    assert gaps["_meta"]["evidence_trace"][-1]["step"] == "score_competition_gaps"
    assert gaps["result"]["gap_signals"]
    assert whitespaces["result"]["terminated_trials"]["count"] == 1
    assert whitespaces["_meta"]["deprecation"]["replacement_tool"] == "analyze_competition_gaps"
    assert landscape["result"]["market_saturation"]["total_active_trials"] == 1
    assert velocity["result"]["indication_average_per_month"] is not None
    assert velocity["result"]["results"][0]["enrollment_per_month"] is not None


@pytest.mark.asyncio
async def test_design_tools_return_recommendations(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_search_trials(**kwargs: object) -> ListQueryResult[TrialSummary]:
        return ListQueryResult(
            queried_sources=["clinicaltrials_gov"],
            warnings=[],
            items=_filter_trials(
                status=kwargs.get("status") if isinstance(kwargs.get("status"), str) else None,
                intervention=kwargs.get("intervention") if isinstance(kwargs.get("intervention"), str) else None,
            ),
        )

    async def fake_get_trial_details(nct_id: str) -> DetailQueryResult[TrialDetail]:
        detail_map = {
            DETAIL_A.nct_id: DETAIL_A,
            DETAIL_B.nct_id: DETAIL_B,
            DETAIL_C.nct_id: DETAIL_C,
        }
        return DetailQueryResult(item=detail_map.get(nct_id), queried_sources=["clinicaltrials_gov"], warnings=[])

    async def fake_search_publications(**_: object) -> ListQueryResult[Publication]:
        return ListQueryResult(queried_sources=["pubmed"], warnings=[], items=[PUB_1])

    monkeypatch.setattr("Medical_Wizard_MCP.tools.intelligence.registry.search_trials", fake_search_trials)
    monkeypatch.setattr("Medical_Wizard_MCP.tools.intelligence.registry.get_trial_details", fake_get_trial_details)
    monkeypatch.setattr("Medical_Wizard_MCP.tools.intelligence.registry.search_publications", fake_search_publications)

    design = await suggest_trial_design(indication="NSCLC", mechanism="mRNA vaccine")
    patient_profile = await suggest_patient_profile(indication="NSCLC", mechanism="mRNA vaccine")

    assert design["result"]["recommended_phase"] in {"PHASE1", "PHASE2"}
    assert design["result"]["recommendation_type"] == "heuristic_draft"
    assert design["_meta"]["evidence_trace"][-1]["step"] == "generate_design_recommendation"
    assert design["result"]["confidence_score"] > 0
    assert "mRNA vaccine" in design["result"]["mechanism"]
    assert patient_profile["result"]["recommended_ecog"] == "0-1"
    assert patient_profile["result"]["recommendation_type"] == "heuristic_draft"
    assert patient_profile["_meta"]["evidence_trace"][-1]["step"] == "generate_patient_profile"
    assert patient_profile["result"]["based_on_trials"] >= 1
    assert patient_profile["result"]["predictive_biomarkers"]


@pytest.mark.asyncio
async def test_extended_intelligence_tools_return_expected_shapes(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_search_trials(**kwargs: object) -> ListQueryResult[TrialSummary]:
        sponsor = kwargs.get("sponsor")
        items = _filter_trials(
            status=kwargs.get("status") if isinstance(kwargs.get("status"), str) else None,
            phase=kwargs.get("phase") if isinstance(kwargs.get("phase"), str) else None,
            intervention=kwargs.get("intervention") if isinstance(kwargs.get("intervention"), str) else None,
        )
        if isinstance(sponsor, str):
            items = [trial for trial in items if sponsor.lower() in trial.lead_sponsor.lower()]
        return ListQueryResult(queried_sources=["clinicaltrials_gov"], warnings=[], items=items)

    async def fake_get_trial_details(nct_id: str) -> DetailQueryResult[TrialDetail]:
        detail_map = {
            DETAIL_A.nct_id: DETAIL_A,
            DETAIL_B.nct_id: DETAIL_B,
            DETAIL_C.nct_id: DETAIL_C,
        }
        return DetailQueryResult(item=detail_map.get(nct_id), queried_sources=["clinicaltrials_gov"], warnings=[])

    async def fake_search_publications(**_: object) -> ListQueryResult[Publication]:
        return ListQueryResult(queried_sources=["pubmed"], warnings=[], items=[PUB_1])

    async def fake_search_preprints(**_: object) -> ListQueryResult[Publication]:
        return ListQueryResult(queried_sources=["medrxiv"], warnings=[], items=[PREPRINT_1])

    async def fake_search_conference_abstracts(**_: object) -> ListQueryResult[ConferenceAbstract]:
        return ListQueryResult(queried_sources=["europe_pmc"], warnings=[], items=[CONFERENCE_1])

    async def fake_search_approved_drugs(**_: object) -> ListQueryResult[ApprovedDrug]:
        return ListQueryResult(queried_sources=["openfda"], warnings=[], items=[APPROVED_DRUG_1])

    async def fake_search_oncology_burden(**_: object) -> ListQueryResult[OncologyBurdenRecord]:
        return ListQueryResult(
            queried_sources=["bigquery_oncology"],
            warnings=[],
            items=[BURDEN_DE, BURDEN_FR, BURDEN_ES],
        )

    monkeypatch.setattr("Medical_Wizard_MCP.tools.intelligence.registry.search_trials", fake_search_trials)
    monkeypatch.setattr("Medical_Wizard_MCP.tools.intelligence.registry.get_trial_details", fake_get_trial_details)
    monkeypatch.setattr("Medical_Wizard_MCP.tools.intelligence.registry.search_publications", fake_search_publications)
    monkeypatch.setattr("Medical_Wizard_MCP.tools.intelligence.registry.search_preprints", fake_search_preprints)
    monkeypatch.setattr("Medical_Wizard_MCP.tools.intelligence.registry.search_conference_abstracts", fake_search_conference_abstracts)
    monkeypatch.setattr("Medical_Wizard_MCP.tools.intelligence.registry.search_approved_drugs", fake_search_approved_drugs)
    monkeypatch.setattr("Medical_Wizard_MCP.tools.intelligence.registry.search_oncology_burden", fake_search_oncology_burden)

    design_benchmark = await benchmark_trial_design(indication="NSCLC", mechanism="mRNA vaccine")
    eligibility = await benchmark_eligibility_criteria(indication="NSCLC")
    endpoints = await benchmark_endpoints(indication="NSCLC")
    evidence = await link_trial_evidence(nct_id="NCT00000111")
    segments = await analyze_patient_segments(indication="NSCLC")
    readouts = await forecast_readouts(indication="NSCLC", months_ahead=60)
    assets = await track_competitor_assets(indication="NSCLC")
    asset_brief = await asset_dossier(indication="NSCLC", asset="mRNA vaccine")
    burden_gap = await burden_vs_trial_footprint(indication="NSCLC")
    commercial_proxy = await estimate_commercial_opportunity_proxy(indication="NSCLC")
    safety = await summarize_safety_signals(indication="NSCLC", mechanism="mRNA vaccine")
    sites = await investigator_site_landscape(indication="NSCLC")
    signals = await watch_indication_signals(indication="NSCLC", mechanism="mRNA vaccine")

    assert design_benchmark["result"]["sample_size"] >= 1
    assert design_benchmark["result"]["primary_endpoint_categories"]
    assert eligibility["result"]["common_inclusion_criteria"]
    assert endpoints["result"]["primary_endpoint_categories"]
    assert evidence["result"]["link_type"] == "query_based_association"
    assert evidence["_meta"]["evidence_trace"][-1]["step"] == "assemble_evidence_links"
    evidence_urls = {ref["url"] for ref in evidence["_meta"]["evidence_refs"]}
    assert "https://clinicaltrials.gov/study/NCT00000111" in evidence_urls
    assert "https://pubmed.ncbi.nlm.nih.gov/1001/" in evidence_urls
    assert "https://doi.org/10.1101/2025.02.01.123456" in evidence_urls
    assert evidence["result"]["evidence_summary"]["publication_count"] == 1
    assert segments["result"]["biomarker_segments"]
    assert readouts["result"]["forecast_type"] == "known_dates_plus_phase_benchmarks"
    assert readouts["_meta"]["evidence_trace"][-1]["step"] == "forecast_readout_dates"
    assert readouts["result"]["forecast"]
    assert assets["result"]["assets"]
    assert asset_brief["result"]["dossier_type"] == "cross_source_asset_dossier"
    assert asset_brief["result"]["conference_signals"]
    assert asset_brief["_meta"]["evidence_trace"][-1]["step"] == "assemble_asset_dossier"
    assert burden_gap["result"]["analysis_type"] == "cross_source_burden_vs_trial_footprint"
    assert burden_gap["result"]["country_rankings"]
    assert burden_gap["_meta"]["evidence_trace"][-1]["step"] == "compare_burden_to_trial_footprint"
    assert commercial_proxy["result"]["proxy_type"] == "commercial_opportunity_proxy"
    assert commercial_proxy["result"]["economic_proxy_limits"]["includes_pricing_data"] is False
    assert commercial_proxy["_meta"]["output_kind"] == "heuristic"
    assert commercial_proxy["_meta"]["evidence_trace"][-1]["step"] == "score_commercial_opportunity_proxy"
    assert safety["result"]["signals"]
    assert sites["result"]["countries"]
    assert signals["result"]["trial_activity"]["upcoming_readouts"]


@pytest.mark.asyncio
async def test_link_trial_evidence_uses_trial_titles_for_publication_and_preprint_queries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publication_queries: list[str] = []
    preprint_queries: list[str] = []

    async def fake_get_trial_details(nct_id: str) -> DetailQueryResult[TrialDetail]:
        assert nct_id == "NCT09990001"
        return DetailQueryResult(item=ROSETTA_DETAIL, queried_sources=["clinicaltrials_gov"], warnings=[])

    async def fake_search_publications(**kwargs: object) -> ListQueryResult[Publication]:
        query = str(kwargs.get("query"))
        publication_queries.append(query)
        items = []
        if query == "ROSETTA-Lung":
            items = [
                Publication(
                    source="pubmed",
                    pmid="424242",
                    title="Latest ROSETTA-Lung efficacy update",
                    authors=["Example Author"],
                    journal="Journal of Thoracic Oncology",
                    pub_date="2026-02-10",
                    abstract="Updated phase 3 efficacy results.",
                    doi="10.1000/rosetta.latest",
                    mesh_terms=["NSCLC"],
                )
            ]
        return ListQueryResult(queried_sources=["pubmed"], warnings=[], items=items)

    async def fake_search_preprints(**kwargs: object) -> ListQueryResult[Publication]:
        query = str(kwargs.get("query"))
        preprint_queries.append(query)
        items = []
        if query == "ROSETTA-Lung":
            items = [
                Publication(
                    source="medrxiv",
                    title="ROSETTA-Lung translational biomarker preprint",
                    authors=["Example Author"],
                    journal="medRxiv",
                    pub_date="2026-01-01",
                    abstract="Biomarker analysis for ROSETTA-Lung.",
                    doi="10.1101/2026.01.01.999999",
                    mesh_terms=["NSCLC"],
                )
            ]
        return ListQueryResult(queried_sources=["medrxiv"], warnings=[], items=items)

    async def fake_search_approved_drugs(**_: object) -> ListQueryResult[ApprovedDrug]:
        return ListQueryResult(queried_sources=["openfda"], warnings=[], items=[])

    monkeypatch.setattr("Medical_Wizard_MCP.tools.intelligence.registry.get_trial_details", fake_get_trial_details)
    monkeypatch.setattr("Medical_Wizard_MCP.tools.intelligence.registry.search_publications", fake_search_publications)
    monkeypatch.setattr("Medical_Wizard_MCP.tools.intelligence.registry.search_preprints", fake_search_preprints)
    monkeypatch.setattr("Medical_Wizard_MCP.tools.intelligence.registry.search_approved_drugs", fake_search_approved_drugs)

    response = await link_trial_evidence(nct_id="NCT09990001")

    assert "ROSETTA-Lung" in publication_queries
    assert "ROSETTA-Lung" in preprint_queries
    assert response["result"]["evidence_summary"]["publication_count"] == 1
    assert response["result"]["evidence_summary"]["preprint_count"] == 1
    assert response["result"]["queries_used"]["publication_queries"][0] == "ROSETTA-Lung"
    assert response["result"]["queries_used"]["preprint_queries"][0] == "ROSETTA-Lung"


@pytest.mark.asyncio
async def test_screen_trial_candidates_returns_included_and_excluded_sets_with_reasons(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    included_trial = TrialSummary(
        source="clinicaltrials_gov",
        nct_id="NCT10000001",
        brief_title="Amivantamab in advanced metastatic NSCLC",
        phase="Phase 3",
        overall_status="RECRUITING",
        lead_sponsor="Janssen",
        interventions=["amivantamab", "lazertinib"],
        primary_outcomes=["Overall survival"],
        enrollment_count=500,
    )
    observational_trial = TrialSummary(
        source="clinicaltrials_gov",
        nct_id="NCT10000002",
        brief_title="Observational bispecific registry in advanced NSCLC",
        phase="Phase 3",
        overall_status="RECRUITING",
        lead_sponsor="Example Sponsor",
        interventions=["bispecific antibody"],
        primary_outcomes=["Real-world outcomes"],
        enrollment_count=200,
    )
    terminated_trial = TrialSummary(
        source="clinicaltrials_gov",
        nct_id="NCT10000003",
        brief_title="Bispecific antibody in advanced NSCLC",
        phase="Phase 3",
        overall_status="TERMINATED",
        lead_sponsor="Example Sponsor",
        interventions=["bispecific antibody"],
        primary_outcomes=["Progression-free survival"],
        enrollment_count=180,
    )
    phase_mismatch_trial = TrialSummary(
        source="clinicaltrials_gov",
        nct_id="NCT10000004",
        brief_title="Bispecific antibody in advanced NSCLC",
        phase="Phase 2/Phase 3",
        overall_status="RECRUITING",
        lead_sponsor="Example Sponsor",
        interventions=["bispecific antibody"],
        primary_outcomes=["Objective response rate"],
        enrollment_count=220,
    )
    non_bispecific_trial = TrialSummary(
        source="clinicaltrials_gov",
        nct_id="NCT10000005",
        brief_title="Pembrolizumab in advanced NSCLC",
        phase="Phase 3",
        overall_status="RECRUITING",
        lead_sponsor="Merck",
        interventions=["pembrolizumab"],
        primary_outcomes=["Overall survival"],
        enrollment_count=450,
    )

    detail_map = {
        "NCT10000001": TrialDetail(
            **included_trial.model_dump(),
            official_title="A phase 3 study of amivantamab in advanced or metastatic NSCLC",
            eligibility_criteria="Adults with advanced or metastatic NSCLC.",
            arms=["Amivantamab arm", "Standard of care arm"],
            secondary_outcomes=["Progression-free survival"],
            study_type="INTERVENTIONAL",
            conditions=["NSCLC"],
        ),
        "NCT10000002": TrialDetail(
            **observational_trial.model_dump(),
            official_title="An observational study of bispecific antibody use in advanced NSCLC",
            eligibility_criteria="Adults with advanced NSCLC.",
            arms=["Observational cohort"],
            secondary_outcomes=["Treatment patterns"],
            study_type="OBSERVATIONAL",
            conditions=["NSCLC"],
        ),
        "NCT10000003": TrialDetail(
            **terminated_trial.model_dump(),
            official_title="A phase 3 study of a bispecific antibody in advanced NSCLC",
            eligibility_criteria="Adults with advanced or metastatic NSCLC.",
            arms=["Bispecific arm", "Chemotherapy arm"],
            secondary_outcomes=["Overall survival"],
            study_type="INTERVENTIONAL",
            conditions=["NSCLC"],
        ),
        "NCT10000004": TrialDetail(
            **phase_mismatch_trial.model_dump(),
            official_title="A phase 2/3 study of a bispecific antibody in advanced NSCLC",
            eligibility_criteria="Adults with advanced or metastatic NSCLC.",
            arms=["Bispecific arm", "Standard of care arm"],
            secondary_outcomes=["Overall survival"],
            study_type="INTERVENTIONAL",
            conditions=["NSCLC"],
        ),
        "NCT10000005": TrialDetail(
            **non_bispecific_trial.model_dump(),
            official_title="A phase 3 study of pembrolizumab in advanced NSCLC",
            eligibility_criteria="Adults with advanced or metastatic NSCLC.",
            arms=["Pembrolizumab arm", "Chemotherapy arm"],
            secondary_outcomes=["Progression-free survival"],
            study_type="INTERVENTIONAL",
            conditions=["NSCLC"],
        ),
    }

    async def fake_search_trials(**_: object) -> ListQueryResult[TrialSummary]:
        return ListQueryResult(
            queried_sources=["clinicaltrials_gov"],
            warnings=[],
            items=[
                included_trial,
                observational_trial,
                terminated_trial,
                phase_mismatch_trial,
                non_bispecific_trial,
            ],
        )

    async def fake_get_trial_details(nct_id: str) -> DetailQueryResult[TrialDetail]:
        return DetailQueryResult(
            item=detail_map.get(nct_id),
            queried_sources=["clinicaltrials_gov"],
            warnings=[],
        )

    monkeypatch.setattr("Medical_Wizard_MCP.tools.intelligence.registry.search_trials", fake_search_trials)
    monkeypatch.setattr("Medical_Wizard_MCP.tools.intelligence.registry.get_trial_details", fake_get_trial_details)

    response = await screen_trial_candidates(
        indication="NSCLC",
        phase="PHASE3",
        mechanism="bispecific antibody",
        patient_segment="advanced metastatic NSCLC",
    )

    assert response["result"]["summary"]["candidate_count"] == 5
    assert response["result"]["summary"]["included_count"] == 1
    assert response["result"]["summary"]["excluded_count"] == 4
    assert response["result"]["included_trials"][0]["nct_id"] == "NCT10000001"
    assert response["result"]["included_trials"][0]["matched_mechanism_labels"] == ["bispecific antibody"]
    assert response["result"]["included_trials"][0]["source_refs"][0]["id"] == "NCT10000001"
    excluded_by_id = {item["nct_id"]: item for item in response["result"]["excluded_trials"]}
    assert "not interventional" in " ".join(excluded_by_id["NCT10000002"]["decision_reasons"]).lower()
    assert "terminal status" in " ".join(excluded_by_id["NCT10000003"]["decision_reasons"]).lower()
    assert "phase" in " ".join(excluded_by_id["NCT10000004"]["decision_reasons"]).lower()
    assert "mechanism" in " ".join(excluded_by_id["NCT10000005"]["decision_reasons"]).lower()
    assert response["_meta"]["evidence_trace"][-1]["step"] == "screen_trial_candidates"
    assert any(ref["id"] == "NCT10000001" for ref in response["_meta"]["evidence_refs"])


@pytest.mark.asyncio
async def test_asset_dossier_surfaces_cross_source_queries_and_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_publication_queries: list[str] = []
    captured_conference_queries: list[str] = []

    async def fake_search_trials(**_: object) -> ListQueryResult[TrialSummary]:
        return ListQueryResult(queried_sources=["clinicaltrials_gov"], warnings=[], items=[TRIAL_A, TRIAL_B])

    async def fake_get_trial_details(nct_id: str) -> DetailQueryResult[TrialDetail]:
        detail_map = {
            DETAIL_A.nct_id: DETAIL_A,
            DETAIL_B.nct_id: DETAIL_B,
        }
        return DetailQueryResult(item=detail_map.get(nct_id), queried_sources=["clinicaltrials_gov"], warnings=[])

    async def fake_search_publications(**kwargs: object) -> ListQueryResult[Publication]:
        captured_publication_queries.append(str(kwargs.get("query")))
        return ListQueryResult(queried_sources=["pubmed"], warnings=[], items=[PUB_1])

    async def fake_search_preprints(**_: object) -> ListQueryResult[Publication]:
        return ListQueryResult(queried_sources=["medrxiv"], warnings=[], items=[PREPRINT_1])

    async def fake_search_conference_abstracts(**kwargs: object) -> ListQueryResult[ConferenceAbstract]:
        captured_conference_queries.append(str(kwargs.get("query")))
        return ListQueryResult(queried_sources=["europe_pmc"], warnings=[], items=[CONFERENCE_1])

    async def fake_search_approved_drugs(**_: object) -> ListQueryResult[ApprovedDrug]:
        return ListQueryResult(queried_sources=["openfda"], warnings=[], items=[APPROVED_DRUG_1])

    monkeypatch.setattr("Medical_Wizard_MCP.tools.intelligence.registry.search_trials", fake_search_trials)
    monkeypatch.setattr("Medical_Wizard_MCP.tools.intelligence.registry.get_trial_details", fake_get_trial_details)
    monkeypatch.setattr("Medical_Wizard_MCP.tools.intelligence.registry.search_publications", fake_search_publications)
    monkeypatch.setattr("Medical_Wizard_MCP.tools.intelligence.registry.search_preprints", fake_search_preprints)
    monkeypatch.setattr("Medical_Wizard_MCP.tools.intelligence.registry.search_conference_abstracts", fake_search_conference_abstracts)
    monkeypatch.setattr("Medical_Wizard_MCP.tools.intelligence.registry.search_approved_drugs", fake_search_approved_drugs)

    response = await asset_dossier(asset="mRNA vaccine", indication="NSCLC", sponsor="BioNTech")

    assert "mRNA vaccine NSCLC" in response["result"]["queries_used"]["publication_queries"]
    assert "mRNA vaccine NSCLC" in captured_publication_queries
    assert response["result"]["evidence_summary"]["conference_signal_count"] == 1
    assert response["result"]["evidence_summary"]["approved_context_count"] == 1
    assert "mRNA vaccine NSCLC" in captured_conference_queries
    assert response["_meta"]["evidence_trace"][-1]["step"] == "assemble_asset_dossier"


@pytest.mark.asyncio
async def test_burden_vs_trial_footprint_maps_subtype_to_parent_site(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_burden_filters: dict[str, object] = {}

    async def fake_search_oncology_burden(**kwargs: object) -> ListQueryResult[OncologyBurdenRecord]:
        captured_burden_filters.update(kwargs)
        return ListQueryResult(
            queried_sources=["bigquery_oncology"],
            warnings=[],
            items=[BURDEN_DE, BURDEN_FR, BURDEN_ES],
        )

    async def fake_search_trials(**_: object) -> ListQueryResult[TrialSummary]:
        return ListQueryResult(queried_sources=["clinicaltrials_gov"], warnings=[], items=[TRIAL_A, TRIAL_B])

    async def fake_get_trial_details(nct_id: str) -> DetailQueryResult[TrialDetail]:
        detail_map = {
            DETAIL_A.nct_id: DETAIL_A,
            DETAIL_B.nct_id: DETAIL_B,
        }
        return DetailQueryResult(item=detail_map.get(nct_id), queried_sources=["clinicaltrials_gov"], warnings=[])

    monkeypatch.setattr("Medical_Wizard_MCP.tools.intelligence.registry.search_oncology_burden", fake_search_oncology_burden)
    monkeypatch.setattr("Medical_Wizard_MCP.tools.intelligence.registry.search_trials", fake_search_trials)
    monkeypatch.setattr("Medical_Wizard_MCP.tools.intelligence.registry.get_trial_details", fake_get_trial_details)

    response = await burden_vs_trial_footprint(indication="NSCLC", sponsor="BioNTech")

    assert captured_burden_filters["site"] == "Lung"
    assert response["result"]["burden_site_used"] == "Lung"
    assert response["result"]["country_rankings"][0]["country"] in {"France", "Spain"}
    assert response["result"]["country_rankings"][0]["footprint_gap_score"] >= response["result"]["country_rankings"][-1]["footprint_gap_score"]


@pytest.mark.asyncio
async def test_burden_vs_trial_footprint_normalizes_country_aliases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_search_oncology_burden(**_: object) -> ListQueryResult[OncologyBurdenRecord]:
        return ListQueryResult(
            queried_sources=["bigquery_oncology"],
            warnings=[],
            items=[BURDEN_USA],
        )

    async def fake_search_trials(**_: object) -> ListQueryResult[TrialSummary]:
        return ListQueryResult(queried_sources=["clinicaltrials_gov"], warnings=[], items=[TRIAL_A, TRIAL_C])

    async def fake_get_trial_details(nct_id: str) -> DetailQueryResult[TrialDetail]:
        detail_map = {
            DETAIL_A.nct_id: DETAIL_A,
            DETAIL_C.nct_id: DETAIL_C,
        }
        return DetailQueryResult(item=detail_map.get(nct_id), queried_sources=["clinicaltrials_gov"], warnings=[])

    monkeypatch.setattr("Medical_Wizard_MCP.tools.intelligence.registry.search_oncology_burden", fake_search_oncology_burden)
    monkeypatch.setattr("Medical_Wizard_MCP.tools.intelligence.registry.search_trials", fake_search_trials)
    monkeypatch.setattr("Medical_Wizard_MCP.tools.intelligence.registry.get_trial_details", fake_get_trial_details)

    response = await burden_vs_trial_footprint(indication="NSCLC")
    usa_row = response["result"]["country_rankings"][0]

    assert usa_row["country"] == "United States of America"
    assert usa_row["visible_trial_count"] == 2
    assert usa_row["visible_site_mentions"] == 2


@pytest.mark.asyncio
async def test_estimate_commercial_opportunity_proxy_surfaces_limits_and_scores(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_search_oncology_burden(**_: object) -> ListQueryResult[OncologyBurdenRecord]:
        return ListQueryResult(
            queried_sources=["bigquery_oncology"],
            warnings=[],
            items=[BURDEN_DE, BURDEN_FR, BURDEN_ES],
        )

    async def fake_search_trials(**_: object) -> ListQueryResult[TrialSummary]:
        return ListQueryResult(queried_sources=["clinicaltrials_gov"], warnings=[], items=[TRIAL_A, TRIAL_B, TRIAL_C])

    async def fake_get_trial_details(nct_id: str) -> DetailQueryResult[TrialDetail]:
        detail_map = {
            DETAIL_A.nct_id: DETAIL_A,
            DETAIL_B.nct_id: DETAIL_B,
            DETAIL_C.nct_id: DETAIL_C,
        }
        return DetailQueryResult(item=detail_map.get(nct_id), queried_sources=["clinicaltrials_gov"], warnings=[])

    async def fake_search_approved_drugs(**_: object) -> ListQueryResult[ApprovedDrug]:
        return ListQueryResult(queried_sources=["openfda"], warnings=[], items=[APPROVED_DRUG_1])

    monkeypatch.setattr("Medical_Wizard_MCP.tools.intelligence.registry.search_oncology_burden", fake_search_oncology_burden)
    monkeypatch.setattr("Medical_Wizard_MCP.tools.intelligence.registry.search_trials", fake_search_trials)
    monkeypatch.setattr("Medical_Wizard_MCP.tools.intelligence.registry.get_trial_details", fake_get_trial_details)
    monkeypatch.setattr("Medical_Wizard_MCP.tools.intelligence.registry.search_approved_drugs", fake_search_approved_drugs)

    response = await estimate_commercial_opportunity_proxy(indication="NSCLC")

    assert response["result"]["proxy_type"] == "commercial_opportunity_proxy"
    assert response["result"]["overall_proxy_score"] > 0
    assert response["result"]["proxy_components"]["medication_gap_score"] > 0
    assert response["result"]["economic_proxy_limits"]["includes_sales_data"] is False
    assert response["result"]["country_opportunity_rankings"]
    assert response["_meta"]["output_kind"] == "heuristic"
