from __future__ import annotations

import pytest

from Medical_Wizard_MCP.models import (
    ApprovedDrug,
    ConferenceAbstract,
    Publication,
    TrialDetail,
    TrialSummary,
    TrialTimeline,
)
from Medical_Wizard_MCP.sources import registry
from Medical_Wizard_MCP.sources.registry import DetailQueryResult, ListQueryResult
from Medical_Wizard_MCP.tools.conferences import search_conference_abstracts
from Medical_Wizard_MCP.tools.drugs import search_approved_drugs
from Medical_Wizard_MCP.tools.intelligence import (
    compare_trials,
    competitive_landscape,
    find_whitespaces,
    get_recruitment_velocity,
    get_trial_density,
    suggest_patient_profile,
    suggest_trial_design,
)
from Medical_Wizard_MCP.tools.publications import search_preprints, search_publications
from Medical_Wizard_MCP.tools.search import get_trial_details, search_trials
from Medical_Wizard_MCP.tools.timelines import get_trial_timelines


TRIAL_ACTIVE = TrialSummary(
    source="clinicaltrials_gov",
    nct_id="NCT10000001",
    brief_title="mRNA vaccine plus pembrolizumab in NSCLC",
    phase="Phase 2",
    overall_status="RECRUITING",
    lead_sponsor="BioNTech",
    interventions=["mRNA vaccine", "pembrolizumab"],
    primary_outcomes=["Objective response rate"],
    enrollment_count=120,
    start_date="2024-01-01",
    primary_completion_date="2025-06-01",
    completion_date="2025-12-01",
)

TRIAL_COMPLETED = TrialSummary(
    source="clinicaltrials_gov",
    nct_id="NCT10000002",
    brief_title="mRNA vaccine monotherapy in NSCLC",
    phase="Phase 1",
    overall_status="COMPLETED",
    lead_sponsor="Merck",
    interventions=["mRNA vaccine"],
    primary_outcomes=["Safety and tolerability"],
    enrollment_count=60,
    start_date="2022-01-01",
    primary_completion_date="2023-06-01",
    completion_date="2023-09-01",
)

TRIAL_TERMINATED = TrialSummary(
    source="clinicaltrials_gov",
    nct_id="NCT10000003",
    brief_title="PD-1 inhibitor monotherapy in NSCLC",
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

DETAIL_ACTIVE = TrialDetail(
    **TRIAL_ACTIVE.model_dump(),
    official_title="A randomized Phase 2 study of mRNA vaccine plus pembrolizumab in NSCLC",
    eligibility_criteria="Adults 18+; ECOG 0-1; TMB-high; measurable disease.",
    arms=["Combination arm"],
    secondary_outcomes=["Progression-free survival"],
    study_type="INTERVENTIONAL",
    conditions=["NSCLC"],
)

DETAIL_COMPLETED = TrialDetail(
    **TRIAL_COMPLETED.model_dump(),
    official_title="A Phase 1 study of mRNA vaccine in NSCLC",
    eligibility_criteria="Adults 18+; ECOG 0-1; measurable disease.",
    arms=["Monotherapy arm"],
    secondary_outcomes=["Overall survival"],
    study_type="INTERVENTIONAL",
    conditions=["NSCLC"],
)

DETAIL_TERMINATED = TrialDetail(
    **TRIAL_TERMINATED.model_dump(),
    official_title="A Phase 2 study of pembrolizumab monotherapy in NSCLC",
    eligibility_criteria="Adults 18+; ECOG 0-1.",
    arms=["Monotherapy arm"],
    secondary_outcomes=["Overall survival"],
    study_type="INTERVENTIONAL",
    conditions=["NSCLC"],
    why_stopped="Insufficient efficacy",
)

TIMELINE_ACTIVE = TrialTimeline(
    source="clinicaltrials_gov",
    nct_id=TRIAL_ACTIVE.nct_id,
    brief_title=TRIAL_ACTIVE.brief_title,
    phase=TRIAL_ACTIVE.phase,
    lead_sponsor=TRIAL_ACTIVE.lead_sponsor,
    overall_status=TRIAL_ACTIVE.overall_status,
    start_date=TRIAL_ACTIVE.start_date,
    primary_completion_date=TRIAL_ACTIVE.primary_completion_date,
    completion_date=TRIAL_ACTIVE.completion_date,
    enrollment_count=TRIAL_ACTIVE.enrollment_count,
)

TIMELINE_COMPLETED = TrialTimeline(
    source="clinicaltrials_gov",
    nct_id=TRIAL_COMPLETED.nct_id,
    brief_title=TRIAL_COMPLETED.brief_title,
    phase=TRIAL_COMPLETED.phase,
    lead_sponsor=TRIAL_COMPLETED.lead_sponsor,
    overall_status=TRIAL_COMPLETED.overall_status,
    start_date=TRIAL_COMPLETED.start_date,
    primary_completion_date=TRIAL_COMPLETED.primary_completion_date,
    completion_date=TRIAL_COMPLETED.completion_date,
    enrollment_count=TRIAL_COMPLETED.enrollment_count,
)

TIMELINE_TERMINATED = TrialTimeline(
    source="clinicaltrials_gov",
    nct_id=TRIAL_TERMINATED.nct_id,
    brief_title=TRIAL_TERMINATED.brief_title,
    phase=TRIAL_TERMINATED.phase,
    lead_sponsor=TRIAL_TERMINATED.lead_sponsor,
    overall_status=TRIAL_TERMINATED.overall_status,
    start_date=TRIAL_TERMINATED.start_date,
    primary_completion_date=TRIAL_TERMINATED.primary_completion_date,
    completion_date=TRIAL_TERMINATED.completion_date,
    enrollment_count=TRIAL_TERMINATED.enrollment_count,
)

PUBLICATION = Publication(
    source="pubmed",
    pmid="1001",
    title="mRNA vaccine strategy in NSCLC",
    authors=["Alice Smith"],
    journal="Nature Medicine",
    pub_date="2024-01-01",
    abstract="TMB-high NSCLC patients showed promising responses to mRNA vaccine combinations.",
    doi="10.1000/pub1",
    mesh_terms=["Lung Neoplasms", "mRNA Vaccines", "Tumor Mutational Burden"],
)

PREPRINT = Publication(
    source="medrxiv",
    pmid=None,
    title="Early mRNA vaccine signal in GBM and thoracic tumors",
    authors=["Alice Smith", "Bob Jones"],
    journal="medRxiv",
    pub_date="2024-03-01",
    abstract="Promising early translational data for biomarker-selected cohorts.",
    doi="10.1101/2024.03.01.123456",
    mesh_terms=["Cancer Biology"],
)

APPROVED_DRUG = ApprovedDrug(
    source="openfda",
    approval_id="BLA123456",
    brand_name="ExampleDrug",
    generic_name="example-generic",
    indication="NSCLC",
    sponsor="Merck",
    route=["INTRAVENOUS"],
    product_type="HUMAN PRESCRIPTION DRUG",
    substance_names=["pembrolizumab"],
    mechanism_of_action="Blocks PD-1 signaling.",
)

CONFERENCE_ABSTRACT = ConferenceAbstract(
    source="europe_pmc",
    source_id="PPR1234",
    title="ASCO abstract of personalized mRNA vaccine in NSCLC",
    authors=["Alice Smith"],
    conference_name="ASCO Annual Meeting",
    conference_series="ASCO",
    presentation_type="abstract",
    abstract_number="TPS9101",
    publication_year=2024,
    publication_date="2024-06-01",
    abstract="Encouraging early translational signal in TMB-high NSCLC.",
    doi="10.1200/JCO.2024.TPS9101",
    url="https://europepmc.org/article/MED/40000001",
    journal="Journal of Clinical Oncology",
)


def _normalize_phase(value: str | None) -> str | None:
    if value is None:
        return None
    return value.lower().replace(" ", "").replace("_", "")


def _filter_trials(
    *,
    status: str | None = None,
    phase: str | None = None,
    sponsor: str | None = None,
    intervention: str | None = None,
) -> list[TrialSummary]:
    trials = [TRIAL_ACTIVE, TRIAL_COMPLETED, TRIAL_TERMINATED]
    if status:
        trials = [trial for trial in trials if trial.overall_status == status]
    if phase:
        normalized = _normalize_phase(phase)
        trials = [trial for trial in trials if _normalize_phase(trial.phase) == normalized]
    if sponsor:
        needle = sponsor.lower()
        trials = [
            trial
            for trial in trials
            if trial.lead_sponsor and needle in trial.lead_sponsor.lower()
        ]
    if intervention:
        needle = intervention.lower()
        trials = [
            trial
            for trial in trials
            if needle in trial.brief_title.lower()
            or any(needle in item.lower() for item in trial.interventions)
        ]
    return trials


def _patch_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_search_trials(**kwargs: object) -> ListQueryResult[TrialSummary]:
        items = _filter_trials(
            status=kwargs.get("status") if isinstance(kwargs.get("status"), str) else None,
            phase=kwargs.get("phase") if isinstance(kwargs.get("phase"), str) else None,
            sponsor=kwargs.get("sponsor") if isinstance(kwargs.get("sponsor"), str) else None,
            intervention=(
                kwargs.get("intervention")
                if isinstance(kwargs.get("intervention"), str)
                else None
            ),
        )
        max_results = kwargs.get("max_results")
        if isinstance(max_results, int):
            items = items[:max_results]
        return ListQueryResult(items=items, queried_sources=["clinicaltrials_gov"], warnings=[])

    async def fake_get_trial_details(nct_id: str) -> DetailQueryResult[TrialDetail]:
        details = {
            DETAIL_ACTIVE.nct_id: DETAIL_ACTIVE,
            DETAIL_COMPLETED.nct_id: DETAIL_COMPLETED,
            DETAIL_TERMINATED.nct_id: DETAIL_TERMINATED,
        }
        return DetailQueryResult(
            item=details.get(nct_id),
            queried_sources=["clinicaltrials_gov"],
            warnings=[],
        )

    async def fake_get_trial_timelines(**kwargs: object) -> ListQueryResult[TrialTimeline]:
        items = [TIMELINE_ACTIVE, TIMELINE_COMPLETED, TIMELINE_TERMINATED]
        sponsor = kwargs.get("sponsor")
        if isinstance(sponsor, str):
            items = [
                item
                for item in items
                if item.lead_sponsor and sponsor.lower() in item.lead_sponsor.lower()
            ]
        phase = kwargs.get("phase")
        if isinstance(phase, str):
            items = [
                item
                for item in items
                if _normalize_phase(item.phase) == _normalize_phase(phase)
            ]
        status = kwargs.get("status")
        if isinstance(status, str):
            items = [item for item in items if item.overall_status == status]
        max_results = kwargs.get("max_results")
        if isinstance(max_results, int):
            items = items[:max_results]
        return ListQueryResult(items=items, queried_sources=["clinicaltrials_gov"], warnings=[])

    async def fake_search_publications(**_: object) -> ListQueryResult[Publication]:
        return ListQueryResult(items=[PUBLICATION], queried_sources=["pubmed"], warnings=[])

    async def fake_search_preprints(**_: object) -> ListQueryResult[Publication]:
        return ListQueryResult(items=[PREPRINT], queried_sources=["medrxiv"], warnings=[])

    async def fake_search_conference_abstracts(**_: object) -> ListQueryResult[ConferenceAbstract]:
        return ListQueryResult(items=[CONFERENCE_ABSTRACT], queried_sources=["europe_pmc"], warnings=[])

    async def fake_search_approved_drugs(**kwargs: object) -> ListQueryResult[ApprovedDrug]:
        items = [APPROVED_DRUG]
        sponsor = kwargs.get("sponsor")
        if isinstance(sponsor, str):
            items = [item for item in items if sponsor.lower() in item.sponsor.lower()]
        intervention = kwargs.get("intervention")
        if isinstance(intervention, str):
            items = [
                item
                for item in items
                if any(
                    intervention.lower() in substance.lower()
                    for substance in item.substance_names
                )
            ]
        return ListQueryResult(items=items, queried_sources=["openfda"], warnings=[])

    monkeypatch.setattr(registry, "search_trials", fake_search_trials)
    monkeypatch.setattr(registry, "get_trial_details", fake_get_trial_details)
    monkeypatch.setattr(registry, "get_trial_timelines", fake_get_trial_timelines)
    monkeypatch.setattr(registry, "search_publications", fake_search_publications)
    monkeypatch.setattr(registry, "search_preprints", fake_search_preprints)
    monkeypatch.setattr(registry, "search_conference_abstracts", fake_search_conference_abstracts)
    monkeypatch.setattr(registry, "search_approved_drugs", fake_search_approved_drugs)


TOOL_CASES = [
    ("search_trials", lambda: search_trials(condition="NSCLC", sponsor="BioNTech"), "results"),
    ("get_trial_details", lambda: get_trial_details("NCT10000001"), "result"),
    (
        "get_trial_timelines",
        lambda: get_trial_timelines(condition="NSCLC", phase="PHASE2"),
        "results",
    ),
    (
        "search_publications",
        lambda: search_publications(term="mRNA vaccine", indication="NSCLC"),
        "results",
    ),
    (
        "search_preprints",
        lambda: search_preprints(term="mRNA vaccine", indication="GBM"),
        "results",
    ),
    (
        "search_conference_abstracts",
        lambda: search_conference_abstracts(term="mRNA vaccine", indication="NSCLC"),
        "results",
    ),
    (
        "search_approved_drugs",
        lambda: search_approved_drugs(indication="NSCLC", sponsor="Merck"),
        "results",
    ),
    ("compare_trials", lambda: compare_trials(["NCT10000001", "NCT10000002"]), "results"),
    (
        "get_trial_density",
        lambda: get_trial_density(indication="NSCLC", group_by="phase"),
        "result",
    ),
    ("find_whitespaces", lambda: find_whitespaces(indication="NSCLC"), "result"),
    ("competitive_landscape", lambda: competitive_landscape(indication="NSCLC"), "result"),
    ("get_recruitment_velocity", lambda: get_recruitment_velocity(indication="NSCLC"), "result"),
    (
        "suggest_trial_design",
        lambda: suggest_trial_design(indication="NSCLC", mechanism="mRNA vaccine"),
        "result",
    ),
    (
        "suggest_patient_profile",
        lambda: suggest_patient_profile(
            indication="NSCLC",
            mechanism="mRNA vaccine",
            biomarker="TMB-high",
        ),
        "result",
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "invoke", "payload_key"),
    TOOL_CASES,
    ids=[case[0] for case in TOOL_CASES],
)
async def test_every_tool_returns_non_empty_payload(
    monkeypatch: pytest.MonkeyPatch,
    tool_name: str,
    invoke,
    payload_key: str,
) -> None:
    _patch_registry(monkeypatch)

    response = await invoke()

    assert response["_meta"]["tool"] == tool_name
    assert response["_meta"]["queried_sources"]

    if payload_key == "results":
        assert response["count"] >= 1
        assert response["results"]
    else:
        assert response["result"] is not None
