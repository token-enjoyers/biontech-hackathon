import re
from typing import Any

from ..server import mcp
from ..sources import registry
from ._inputs import coalesce_indication
from ._responses import detail_response, list_response

NCT_ID_PATTERN = re.compile(r"^NCT\d{8}$")


@mcp.tool()
async def search_trials(
    indication: str | None = None,
    condition: str | None = None,
    phase: str | None = None,
    status: str | None = None,
    sponsor: str | None = None,
    intervention: str | None = None,
    max_results: int = 10,
) -> dict[str, Any]:
    """Primary trial-discovery tool.

Use this when you need candidate clinical trials for a disease area, competitor discovery, or a starting set before calling more specific trial tools.

Avoid this when you already have an NCT ID and need full details for one study.

Returns a standardized list envelope with `_meta`, `count`, and `results`.
Each trial result includes: nct_id, brief_title, phase, overall_status, lead_sponsor, interventions, primary_outcomes, enrollment_count, source.

Args:
    indication: Canonical disease-area parameter (e.g. "lung cancer", "NSCLC", "glioblastoma")
    condition: Backward-compatible alias for indication
    phase: Trial phase — one of EARLY_PHASE1, PHASE1, PHASE2, PHASE3, PHASE4
    status: Recruitment status — one of RECRUITING, NOT_YET_RECRUITING, ACTIVE_NOT_RECRUITING, COMPLETED, TERMINATED, WITHDRAWN, SUSPENDED
    sponsor: Sponsor organization name (e.g. "Merck", "BioNTech", "Pfizer")
    intervention: Drug or therapy name (e.g. "pembrolizumab", "mRNA vaccine")
    max_results: Number of results (default 10, max 20)
    """
    resolved_indication = coalesce_indication(indication=indication, condition=condition)
    if resolved_indication is None:
        return list_response(
            tool_name="search_trials",
            data_type="trial_search_results",
            items=[],
            quality_note="Trial discovery requires a disease-area filter.",
            coverage="Clinical trial registry sources configured for this server.",
            warnings=[
                {
                    "source": "tool_validation",
                    "stage": "validate_indication",
                    "error": "Provide `indication` or the backward-compatible alias `condition`.",
                }
            ],
            requested_filters={
                "indication": indication,
                "condition": condition,
                "phase": phase,
                "status": status,
                "sponsor": sponsor,
                "intervention": intervention,
                "max_results": max_results,
            },
            evidence_sources=["tool_validation"],
            evidence_trace=[
                {
                    "step": "validate_indication",
                    "sources": ["tool_validation"],
                    "note": "Rejected the request because no indication or condition filter was provided.",
                    "filters": {
                        "indication": indication,
                        "condition": condition,
                    },
                    "output_kind": "raw",
                    "refs": [],
                }
            ],
        )

    max_results = min(max_results, 20)
    response = await registry.search_trials(
        condition=resolved_indication,
        phase=phase,
        status=status,
        sponsor=sponsor,
        intervention=intervention,
        max_results=max_results,
    )
    payload = [r.model_dump() for r in response.items]
    return list_response(
        tool_name="search_trials",
        data_type="trial_search_results",
        items=payload,
        quality_note="Registry search results normalized across the currently registered sources.",
        coverage="Clinical trial registry sources configured for this server.",
        queried_sources=response.queried_sources,
        warnings=[warning.as_dict() for warning in response.warnings],
        evidence_sources=response.queried_sources,
        evidence_trace=[
            {
                "step": "search_trial_registry",
                "sources": response.queried_sources,
                "note": "Fetched candidate trials matching the requested filters from registered trial sources.",
                "filters": {
                    "indication": resolved_indication,
                    "phase": phase,
                    "status": status,
                    "sponsor": sponsor,
                    "intervention": intervention,
                    "max_results": max_results,
                },
                "output_kind": "raw",
                "refs": payload,
            }
        ],
        requested_filters={
            "indication": resolved_indication,
            "condition": condition,
            "phase": phase,
            "status": status,
            "sponsor": sponsor,
            "intervention": intervention,
            "max_results": max_results,
        },
    )


@mcp.tool()
async def get_trial_details(nct_id: str) -> dict[str, Any]:
    """Trial detail tool for one known NCT identifier.

Use this after `search_trials` or whenever you already know the NCT ID and need eligibility, arms, outcomes, or other detailed fields.

Avoid this for broad discovery when you do not yet know the study identifier.

Returns a standardized detail envelope with `_meta` and `result`.
The trial detail includes: nct_id, brief_title, official_title, phase, overall_status, lead_sponsor, interventions, primary_outcomes, secondary_outcomes, eligibility_criteria, arms, study_type, conditions, enrollment_count, source.

    Args:
    nct_id: The ClinicalTrials.gov identifier (e.g. "NCT05012345")
    """
    if not NCT_ID_PATTERN.match(nct_id):
        return detail_response(
            tool_name="get_trial_details",
            data_type="trial_detail",
            item=None,
            quality_note="Trial detail lookup requires a ClinicalTrials.gov NCT identifier.",
            coverage="Currently backed by ClinicalTrials.gov detail data.",
            missing_message=f"Invalid trial ID '{nct_id}'. Expected format NCT########.",
            warnings=[
                {
                    "source": "tool_validation",
                    "stage": "validate_nct_id",
                    "error": "Expected a ClinicalTrials.gov identifier in the form NCT########.",
                }
            ],
            requested_filters={"nct_id": nct_id},
            evidence_sources=["tool_validation"],
            evidence_trace=[
                {
                    "step": "validate_nct_id",
                    "sources": ["tool_validation"],
                    "note": "Rejected the request because the identifier did not match the NCT######## format.",
                    "filters": {"nct_id": nct_id},
                    "output_kind": "raw",
                    "refs": [],
                }
            ],
        )

    detail = await registry.get_trial_details(nct_id)
    return detail_response(
        tool_name="get_trial_details",
        data_type="trial_detail",
        item=detail.item.model_dump() if detail.item is not None else None,
        quality_note="Detailed trial fields come from the first registered source that can resolve the requested NCT ID.",
        coverage="Currently backed by ClinicalTrials.gov detail data.",
        missing_message=f"No trial found with ID {nct_id}",
        queried_sources=detail.queried_sources,
        warnings=[warning.as_dict() for warning in detail.warnings],
        evidence_sources=detail.queried_sources,
        evidence_trace=[
            {
                "step": "fetch_trial_detail",
                "sources": detail.queried_sources,
                "note": "Resolved the requested trial identifier against registered detail-capable sources.",
                "filters": {"nct_id": nct_id},
                "output_kind": "raw",
                "refs": [detail.item.model_dump()] if detail.item is not None else [],
            }
        ],
        requested_filters={"nct_id": nct_id},
    )
