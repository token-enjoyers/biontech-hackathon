from __future__ import annotations

import pytest

from Medical_Wizard_MCP.models import Publication, TrialDetail, TrialSummary, TrialTimeline
from Medical_Wizard_MCP.sources.registry import DetailQueryResult, ListQueryResult
from Medical_Wizard_MCP.tools.intelligence import (
    compare_trials,
    competitive_landscape,
    find_whitespaces,
    get_recruitment_velocity,
    get_trial_density,
    suggest_patient_profile,
    suggest_trial_design,
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
    primary_completion_date="2025-06-01",
    completion_date="2025-12-01",
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
    eligibility_criteria="Adults 18+; ECOG 0-1; TMB-high; measurable disease.",
    arms=["Combination arm"],
    secondary_outcomes=["Progression-free survival"],
    study_type="INTERVENTIONAL",
    conditions=["NSCLC"],
)

DETAIL_B = TrialDetail(
    **TRIAL_B.model_dump(),
    official_title="A Phase 1 study of mRNA vaccine in NSCLC",
    eligibility_criteria="Adults 18+; ECOG 0-1; measurable disease.",
    arms=["Monotherapy arm"],
    secondary_outcomes=["Overall survival"],
    study_type="INTERVENTIONAL",
    conditions=["NSCLC"],
)

DETAIL_C = TrialDetail(
    **TRIAL_C.model_dump(),
    official_title="A Phase 2 study of pembrolizumab monotherapy in NSCLC",
    eligibility_criteria="Adults 18+; ECOG 0-1.",
    arms=["Monotherapy arm"],
    secondary_outcomes=["Overall survival"],
    study_type="INTERVENTIONAL",
    conditions=["NSCLC"],
    why_stopped="Insufficient efficacy",
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
    whitespaces = await find_whitespaces(indication="NSCLC")
    landscape = await competitive_landscape(indication="NSCLC")
    velocity = await get_recruitment_velocity(indication="NSCLC")

    assert comparison["count"] == 2
    assert "TMB-high" in comparison["results"][0]["biomarkers"]
    assert density["result"]["distribution"]["mRNA vaccine"] >= 1
    assert whitespaces["result"]["terminated_trials"]["count"] == 1
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
    assert design["result"]["confidence_score"] > 0
    assert "mRNA vaccine" in design["result"]["mechanism"]
    assert patient_profile["result"]["recommended_ecog"] == "0-1"
    assert patient_profile["result"]["based_on_trials"] >= 1
    assert patient_profile["result"]["predictive_biomarkers"]
