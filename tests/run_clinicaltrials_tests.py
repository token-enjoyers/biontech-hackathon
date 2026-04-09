"""
Standalone test runner for ClinicalTrialsSource.
Run with:  python tests/run_clinicaltrials_tests.py
"""
from __future__ import annotations

import asyncio
import json
import sys
import traceback
from pathlib import Path

# Make sure the src package is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import httpx

from Medical_Wizard_MCP.sources.clinicaltrials import BASE_URL, ClinicalTrialsSource

# ---------------------------------------------------------------------------
# Shared fixture data – mirrors the real ClinicalTrials.gov API v2 structure
# ---------------------------------------------------------------------------

STUDY_1 = {
    "protocolSection": {
        "identificationModule": {
            "nctId": "NCT12345678",
            "briefTitle": "BNT111 Phase 2 Lung Cancer Study",
            "officialTitle": "A Phase 2 Study of BNT111 in Advanced Lung Cancer",
        },
        "statusModule": {
            "overallStatus": "RECRUITING",
            "startDateStruct": {"date": "2022-03-01"},
            "primaryCompletionDateStruct": {"date": "2024-06-01"},
            "completionDateStruct": {"date": "2024-12-01"},
        },
        "conditionsModule": {"conditions": ["Lung Cancer", "NSCLC"]},
        "sponsorCollaboratorsModule": {
            "leadSponsor": {"name": "BioNTech SE", "class": "INDUSTRY"}
        },
        "interventionsModule": {
            "interventions": [{"type": "BIOLOGICAL", "name": "BNT111"}]
        },
        "designModule": {
            "studyType": "INTERVENTIONAL",
            "phases": ["PHASE2"],
            "enrollmentInfo": {"count": 120, "type": "ESTIMATED"},
        },
        "eligibilityModule": {
            "eligibilityCriteria": "Inclusion: adults 18+\nExclusion: prior immunotherapy"
        },
        "armsInterventionsModule": {
            "armGroups": [{"label": "BNT111 Treatment", "type": "EXPERIMENTAL"}]
        },
        "outcomesModule": {
            "primaryOutcomes": [{"measure": "Overall Response Rate"}],
            "secondaryOutcomes": [{"measure": "Progression-Free Survival"}],
        },
    }
}

STUDY_2 = {
    "protocolSection": {
        "identificationModule": {
            "nctId": "NCT87654321",
            "briefTitle": "BNT122 Colorectal Cancer Vaccine",
        },
        "statusModule": {
            "overallStatus": "ACTIVE_NOT_RECRUITING",
            "startDateStruct": {"date": "2021-06-15"},
            "primaryCompletionDateStruct": {"date": "2025-01-01"},
            "completionDateStruct": {"date": "2025-06-01"},
        },
        "conditionsModule": {"conditions": ["Colorectal Cancer"]},
        "sponsorCollaboratorsModule": {
            "leadSponsor": {"name": "BioNTech SE", "class": "INDUSTRY"}
        },
        "interventionsModule": {
            "interventions": [{"type": "BIOLOGICAL", "name": "BNT122"}]
        },
        "designModule": {
            "studyType": "INTERVENTIONAL",
            "phases": ["PHASE1", "PHASE2"],
            "enrollmentInfo": {"count": 200, "type": "ACTUAL"},
        },
        "eligibilityModule": {},
        "armsInterventionsModule": {"armGroups": []},
        "outcomesModule": {"primaryOutcomes": [], "secondaryOutcomes": []},
    }
}

LIST_RESPONSE = {"studies": [STUDY_1, STUDY_2]}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_source(handler) -> ClinicalTrialsSource:
    source = ClinicalTrialsSource()
    source._client = httpx.AsyncClient(
        base_url=BASE_URL, transport=httpx.MockTransport(handler)
    )
    return source


PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
results: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    status = PASS if condition else FAIL
    marker = "  [OK]" if condition else "  [!!]"
    print(f"{marker} {name}" + (f": {detail}" if detail else ""))
    results.append((name, condition, detail))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_search_trials_maps_response() -> None:
    print("\n── search_trials ──────────────────────────────────────────────")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=LIST_RESPONSE)

    source = _make_source(handler)
    trials = await source.search_trials("lung cancer")
    await source.close()

    print("Results:")
    for t in trials:
        print(json.dumps(t.model_dump(), indent=2))

    check("returns 2 trials", len(trials) == 2)
    check("source field", trials[0].source == "clinicaltrials_gov")
    check("nct_id", trials[0].nct_id == "NCT12345678")
    check("brief_title", trials[0].brief_title == "BNT111 Phase 2 Lung Cancer Study")
    check("phase PHASE2 → 'Phase 2'", trials[0].phase == "Phase 2")
    check("phase multi-phase → 'Phase 1/Phase 2'", trials[1].phase == "Phase 1/Phase 2")
    check("overall_status", trials[0].overall_status == "RECRUITING")
    check("lead_sponsor", trials[0].lead_sponsor == "BioNTech SE")
    check("interventions list", trials[0].interventions == ["BNT111"])
    check("primary_outcomes", trials[0].primary_outcomes == ["Overall Response Rate"])
    check("enrollment_count", trials[0].enrollment_count == 120)


async def test_search_trials_optional_filters() -> None:
    print("\n── search_trials optional filters ────────────────────────────")

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(dict(request.url.params))
        return httpx.Response(200, json={"studies": []})

    source = _make_source(handler)
    await source.search_trials(
        "melanoma",
        phase="phase 2",
        status="recruiting",
        sponsor="BioNTech",
        intervention="BNT111",
    )
    await source.close()

    print("Query params sent to API:")
    print(json.dumps(captured, indent=2))

    check("filter.phase uppercased + no spaces", captured.get("filter.phase") == "PHASE2")
    check("filter.overallStatus uppercased", captured.get("filter.overallStatus") == "RECRUITING")
    check("query.term for sponsor", captured.get("query.term") == "BioNTech")
    check("query.intr for intervention", captured.get("query.intr") == "BNT111")


async def test_get_trial_details() -> None:
    print("\n── get_trial_details ──────────────────────────────────────────")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=STUDY_1)

    source = _make_source(handler)
    detail = await source.get_trial_details("NCT12345678")
    await source.close()

    print("Result:")
    print(json.dumps(detail.model_dump(), indent=2))

    check("not None", detail is not None)
    check("nct_id", detail.nct_id == "NCT12345678")
    check("official_title", detail.official_title == "A Phase 2 Study of BNT111 in Advanced Lung Cancer")
    check("study_type", detail.study_type == "INTERVENTIONAL")
    check("conditions", detail.conditions == ["Lung Cancer", "NSCLC"])
    check("arms", detail.arms == ["BNT111 Treatment"])
    check("secondary_outcomes", detail.secondary_outcomes == ["Progression-Free Survival"])
    check("eligibility_criteria contains text", "adults 18+" in (detail.eligibility_criteria or ""))


async def test_get_trial_details_404() -> None:
    print("\n── get_trial_details (404) ────────────────────────────────────")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    source = _make_source(handler)
    result = await source.get_trial_details("NCT00000000")
    await source.close()

    print(f"Result for unknown NCT ID: {result}")
    check("returns None on 404", result is None)


async def test_get_trial_timelines() -> None:
    print("\n── get_trial_timelines ────────────────────────────────────────")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=LIST_RESPONSE)

    source = _make_source(handler)
    timelines = await source.get_trial_timelines("colorectal cancer")
    await source.close()

    print("Results:")
    for t in timelines:
        print(json.dumps(t.model_dump(), indent=2))

    check("returns 2 timelines", len(timelines) == 2)
    check("source field", timelines[0].source == "clinicaltrials_gov")
    check("nct_id", timelines[0].nct_id == "NCT12345678")
    check("start_date", timelines[0].start_date == "2022-03-01")
    check("primary_completion_date", timelines[0].primary_completion_date == "2024-06-01")
    check("completion_date", timelines[0].completion_date == "2024-12-01")
    check("second trial start_date", timelines[1].start_date == "2021-06-15")


async def test_get_trial_timelines_sponsor_filter() -> None:
    print("\n── get_trial_timelines sponsor filter ─────────────────────────")

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(dict(request.url.params))
        return httpx.Response(200, json={"studies": []})

    source = _make_source(handler)
    await source.get_trial_timelines("lung cancer", sponsor="BioNTech")
    await source.close()

    print("Query params sent to API:")
    print(json.dumps(captured, indent=2))

    check("query.term for sponsor", captured.get("query.term") == "BioNTech")


async def test_missing_fields_graceful() -> None:
    print("\n── search_trials (minimal/incomplete study) ───────────────────")

    minimal = {"protocolSection": {"identificationModule": {"nctId": "NCT99999999"}}}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"studies": [minimal]})

    source = _make_source(handler)
    trials = await source.search_trials("anything")
    await source.close()

    print("Result:")
    print(json.dumps(trials[0].model_dump(), indent=2))

    t = trials[0]
    check("nct_id present", t.nct_id == "NCT99999999")
    check("brief_title defaults to ''", t.brief_title == "")
    check("phase defaults to None", t.phase is None)
    check("overall_status defaults to ''", t.overall_status == "")
    check("lead_sponsor defaults to ''", t.lead_sponsor == "")
    check("interventions defaults to []", t.interventions == [])
    check("enrollment_count defaults to None", t.enrollment_count is None)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

async def main() -> None:
    tests = [
        test_search_trials_maps_response,
        test_search_trials_optional_filters,
        test_get_trial_details,
        test_get_trial_details_404,
        test_get_trial_timelines,
        test_get_trial_timelines_sponsor_filter,
        test_missing_fields_graceful,
    ]

    failed_tests: list[str] = []
    for test_fn in tests:
        try:
            await test_fn()
        except Exception:
            name = test_fn.__name__
            print(f"\n\033[31mERROR in {name}:\033[0m")
            traceback.print_exc()
            failed_tests.append(name)

    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    failed_checks = [name for name, ok, _ in results if not ok]

    print("\n" + "=" * 60)
    print(f"Checks:  {passed}/{total} passed")
    if failed_checks:
        print(f"\033[31mFailed checks:\033[0m")
        for name in failed_checks:
            print(f"  - {name}")
    if failed_tests:
        print(f"\033[31mCrashed tests:\033[0m")
        for name in failed_tests:
            print(f"  - {name}")
    if not failed_checks and not failed_tests:
        print("\033[32mAll tests passed.\033[0m")
    print("=" * 60)

    if failed_checks or failed_tests:
        sys.exit(1)


asyncio.run(main())
