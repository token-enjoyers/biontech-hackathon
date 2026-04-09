import re
from typing import Any

from ..server import mcp
from ..sources import registry
from ._responses import detail_response, list_response

NCT_ID_PATTERN = re.compile(r"^NCT\d{8}$")


@mcp.tool()
async def search_trials(
    condition: str,
    phase: str | None = None,
    status: str | None = None,
    sponsor: str | None = None,
    intervention: str | None = None,
    max_results: int = 10,
) -> dict[str, Any]:
    """Search clinical trials by condition, phase, status, sponsor, or intervention.

This is the primary discovery tool. Use it to find trials for a given disease, identify competitors, or find terminated/failed trials for failure analysis.

Returns a standardized list envelope with `_meta`, `count`, and `results`.
Each trial result includes: nct_id, brief_title, phase, overall_status, lead_sponsor, interventions, primary_outcomes, enrollment_count, source.

Args:
    condition: Disease or condition (e.g. "lung cancer", "NSCLC", "glioblastoma", "pancreatic cancer")
    phase: Trial phase — one of EARLY_PHASE1, PHASE1, PHASE2, PHASE3, PHASE4
    status: Recruitment status — one of RECRUITING, NOT_YET_RECRUITING, ACTIVE_NOT_RECRUITING, COMPLETED, TERMINATED, WITHDRAWN, SUSPENDED
    sponsor: Sponsor organization name (e.g. "Merck", "BioNTech", "Pfizer")
    intervention: Drug or therapy name (e.g. "pembrolizumab", "mRNA vaccine")
    max_results: Number of results (default 10, max 20)
    """
    max_results = min(max_results, 20)
    response = await registry.search_trials(
        condition=condition,
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
        requested_filters={
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
    """Get full details for a single clinical trial by NCT ID.

Use this after search_trials to dive deeper into a specific trial — e.g. to inspect eligibility criteria, study arms, secondary outcomes, or study design.

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
        requested_filters={"nct_id": nct_id},
    )
