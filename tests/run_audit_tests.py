"""
Standalone test runner for the audit tools (get_document_passages,
extract_structured_evidence, verify_claim_evidence).

Run with:  python tests/run_audit_tests.py
"""
from __future__ import annotations

import asyncio
import json
import sys
import traceback
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from Medical_Wizard_MCP.models import ApprovedDrug, Publication, TrialDetail, TrialSummary
from Medical_Wizard_MCP.sources.registry import DetailQueryResult, ListQueryResult
from Medical_Wizard_MCP.tools.audit import (
    extract_structured_evidence,
    get_document_passages,
    verify_claim_evidence,
)
from Medical_Wizard_MCP.tools.drugs import search_approved_drugs
from Medical_Wizard_MCP.tools.monitoring import track_indication_changes
from Medical_Wizard_MCP.tools.publications import search_preprints, search_publications

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

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
    abstract=(
        "Objective response rate was 34% and median progression-free survival was 8.2 months "
        "in PD-L1 positive NSCLC patients treated with mRNA vaccine plus pembrolizumab "
        "(n=82, p=0.03)."
    ),
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

# ---------------------------------------------------------------------------
# Async fakes
# ---------------------------------------------------------------------------

async def fake_get_trial_details(_: str) -> DetailQueryResult[TrialDetail]:
    return DetailQueryResult(item=DETAIL, queried_sources=["clinicaltrials_gov"], warnings=[])

async def fake_search_publications(**_: Any) -> ListQueryResult[Publication]:
    return ListQueryResult(items=[PUB], queried_sources=["pubmed"], warnings=[])

async def fake_search_preprints(**_: Any) -> ListQueryResult[Publication]:
    return ListQueryResult(items=[PREPRINT], queried_sources=["medrxiv"], warnings=[])

async def fake_search_trials(**_: Any) -> ListQueryResult[TrialSummary]:
    return ListQueryResult(items=[TRIAL], queried_sources=["clinicaltrials_gov"], warnings=[])

async def fake_search_approved_drugs(**_: Any) -> ListQueryResult[ApprovedDrug]:
    return ListQueryResult(items=[DRUG], queried_sources=["openfda"], warnings=[])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

results: list[tuple[str, bool]] = []

def check(name: str, condition: bool) -> None:
    marker = "  [OK]" if condition else "  [!!]"
    print(f"{marker} {name}")
    results.append((name, condition))

@contextmanager
def audit_patches():
    """Patch all registry methods used by the audit tools."""
    with (
        patch("Medical_Wizard_MCP.tools.audit.registry.get_trial_details", fake_get_trial_details),
        patch("Medical_Wizard_MCP.tools.audit.registry.search_publications", fake_search_publications),
        patch("Medical_Wizard_MCP.tools.audit.registry.search_preprints", fake_search_preprints),
        patch("Medical_Wizard_MCP.tools.audit.registry.search_approved_drugs", fake_search_approved_drugs),
    ):
        yield

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_evidence_quality_annotation() -> None:
    print("\n── evidence quality tiers on publications / preprints / drugs ──")

    with (
        patch("Medical_Wizard_MCP.tools.publications.registry.search_publications", fake_search_publications),
        patch("Medical_Wizard_MCP.tools.publications.registry.search_preprints", fake_search_preprints),
        patch("Medical_Wizard_MCP.tools.drugs.registry.search_approved_drugs", fake_search_approved_drugs),
    ):
        pub_resp = await search_publications(query="mRNA vaccine NSCLC")
        pre_resp = await search_preprints(query="mRNA vaccine NSCLC")
        drug_resp = await search_approved_drugs(indication="NSCLC")

    print("\nPublication result:")
    print(json.dumps(pub_resp["results"][0], indent=2))
    print("\nPreprint result:")
    print(json.dumps(pre_resp["results"][0], indent=2))
    print("\nDrug result:")
    print(json.dumps(drug_resp["results"][0], indent=2))

    check(
        "publication tier is medium_high or high",
        pub_resp["results"][0]["evidence_quality_tier"] in {"medium_high", "high"},
    )
    check(
        "publication quality score >= 0.75",
        pub_resp["results"][0]["evidence_quality_score"] >= 0.75,
    )
    check(
        "preprint tier is low",
        pre_resp["results"][0]["evidence_quality_tier"] == "low",
    )
    check(
        "drug tier is high",
        drug_resp["results"][0]["evidence_quality_tier"] == "high",
    )


async def test_track_indication_changes() -> None:
    print("\n── track_indication_changes filters by date ────────────────────")

    with (
        patch("Medical_Wizard_MCP.tools.monitoring.registry.search_trials", fake_search_trials),
        patch("Medical_Wizard_MCP.tools.monitoring.registry.search_publications", fake_search_publications),
        patch("Medical_Wizard_MCP.tools.monitoring.registry.search_preprints", fake_search_preprints),
    ):
        resp = await track_indication_changes(indication="NSCLC", since="2025-01-01")

    print("\nResponse summary:")
    print(json.dumps(resp["result"]["summary"], indent=2))
    print("\nLast evidence trace step:", resp["_meta"]["evidence_trace"][-1]["step"])

    check("tool name is track_indication_changes", resp["_meta"]["tool"] == "track_indication_changes")
    check("new_trials_started == 1", resp["result"]["summary"]["new_trials_started"] == 1)
    check("new_publications == 1", resp["result"]["summary"]["new_publications"] == 1)
    check("new_preprints == 1", resp["result"]["summary"]["new_preprints"] == 1)
    check(
        "last trace step is filter_recent_changes",
        resp["_meta"]["evidence_trace"][-1]["step"] == "filter_recent_changes",
    )


async def test_get_document_passages() -> None:
    print("\n── get_document_passages returns ranked passages ────────────────")

    with audit_patches():
        resp = await get_document_passages(
            query="objective response rate NSCLC",
            nct_id="NCT70000001",
            max_passages=5,
        )

    print(f"\nPassage count: {resp['count']}")
    if resp["results"]:
        print("First passage:")
        print(json.dumps(resp["results"][0], indent=2))

    check("at least 1 passage returned", resp["count"] >= 1)
    check(
        "passage document_url starts with https://",
        resp["results"][0]["document_url"].startswith("https://"),
    )


async def test_extract_structured_evidence() -> None:
    print("\n── extract_structured_evidence finds endpoints and findings ─────")

    with audit_patches():
        resp = await extract_structured_evidence(
            nct_id="NCT70000001",
            indication="NSCLC",
            intervention="mRNA vaccine",
            max_documents=4,
        )

    print("\nFinding summary:")
    print(json.dumps(resp["result"]["finding_summary"], indent=2))
    print("\nFindings (first 3):")
    print(json.dumps(resp["result"]["findings"][:3], indent=2))

    check("tool name is extract_structured_evidence", resp["_meta"]["tool"] == "extract_structured_evidence")
    check("at least 2 findings extracted", resp["result"]["finding_summary"]["finding_count"] >= 2)
    check(
        "ORR endpoint found",
        any(item["endpoint_name"] == "ORR" for item in resp["result"]["findings"]),
    )


async def test_verify_claim_evidence() -> None:
    print("\n── verify_claim_evidence returns verdict + supporting passages ──")

    with audit_patches():
        resp = await verify_claim_evidence(
            claim="mRNA vaccine improved objective response rate in NSCLC",
            nct_id="NCT70000001",
            indication="NSCLC",
            intervention="mRNA vaccine",
            max_passages=6,
        )

    print(f"\nVerdict: {resp['result']['verdict']}")
    print(f"Supporting passages: {len(resp['result']['supporting_evidence'])}")
    print(f"Conflicting passages: {len(resp['result']['conflicting_evidence'])}")
    print("Last trace step:", resp["_meta"]["evidence_trace"][-1]["step"])

    check(
        "verdict is supported or mixed",
        resp["result"]["verdict"] in {"supported", "mixed"},
    )
    check(
        "at least 1 supporting passage",
        len(resp["result"]["supporting_evidence"]) >= 1,
    )
    check(
        "last trace step is bind_claim_to_passages",
        resp["_meta"]["evidence_trace"][-1]["step"] == "bind_claim_to_passages",
    )


async def test_extract_structured_evidence_no_scope_returns_error() -> None:
    print("\n── extract_structured_evidence with no scope returns error ──────")

    with audit_patches():
        resp = await extract_structured_evidence()

    print(f"\nResult: {resp.get('result')}")
    print(f"Message: {resp.get('message')}")
    print(f"Warnings: {resp['_meta'].get('partial_failures', [])}")

    check("result is None when no scope given", resp.get("result") is None)
    check("warnings are present", len(resp["_meta"].get("partial_failures", [])) >= 1)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

async def main() -> None:
    tests = [
        test_evidence_quality_annotation,
        test_track_indication_changes,
        test_get_document_passages,
        test_extract_structured_evidence,
        test_verify_claim_evidence,
        test_extract_structured_evidence_no_scope_returns_error,
    ]

    failed_tests: list[str] = []
    for test_fn in tests:
        try:
            await test_fn()
        except Exception:
            print(f"\n\033[31mERROR in {test_fn.__name__}:\033[0m")
            traceback.print_exc()
            failed_tests.append(test_fn.__name__)

    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    failed_checks = [name for name, ok in results if not ok]

    print("\n" + "=" * 60)
    print(f"Checks:  {passed}/{total} passed")
    if failed_checks:
        print("\033[31mFailed checks:\033[0m")
        for name in failed_checks:
            print(f"  - {name}")
    if failed_tests:
        print("\033[31mCrashed tests:\033[0m")
        for name in failed_tests:
            print(f"  - {name}")
    if not failed_checks and not failed_tests:
        print("\033[32mAll tests passed.\033[0m")
    print("=" * 60)

    if failed_checks or failed_tests:
        sys.exit(1)


asyncio.run(main())
