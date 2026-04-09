from typing import Any

from .._mcp import mcp
from ..sources import registry
from ._inputs import coalesce_indication
from ._intelligence import months_between, months_since
from ._responses import list_response


@mcp.tool()
async def get_trial_timelines(
    indication: str | None = None,
    condition: str | None = None,
    sponsor: str | None = None,
    phase: str | None = None,
    status: str | None = None,
    max_results: int = 15,
) -> dict[str, Any]:
    """Timeline and enrollment tool for comparable trials.

Use this when you need start dates, completion dates, enrollment, or derived duration metrics across a set of trials.

Avoid this when you need full eligibility or arm-level detail for a single study.

Returns a standardized list envelope with `_meta`, `count`, and `results`.
Each trial timeline includes: nct_id, brief_title, phase, lead_sponsor, start_date, primary_completion_date, completion_date, enrollment_count, source.

Args:
    indication: Canonical disease-area parameter (e.g. "NSCLC", "breast cancer", "glioblastoma")
    condition: Backward-compatible alias for indication
    sponsor: Filter to a specific sponsor (e.g. "Roche", "Merck") — omit to see all sponsors
    phase: Optional phase filter (e.g. "PHASE2", "Phase 3")
    status: Optional status filter (e.g. "RECRUITING", "COMPLETED")
    max_results: Number of results (default 15, max 30)
    """
    resolved_indication = coalesce_indication(indication=indication, condition=condition)
    if resolved_indication is None:
        return list_response(
            tool_name="get_trial_timelines",
            data_type="trial_timeline",
            items=[],
            quality_note="Timeline lookup requires a disease-area filter.",
            coverage="Currently backed by ClinicalTrials.gov timeline data.",
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
                "sponsor": sponsor,
                "phase": phase,
                "status": status,
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

    max_results = min(max_results, 30)
    response = await registry.get_trial_timelines(
        condition=resolved_indication,
        sponsor=sponsor,
        phase=phase,
        status=status,
        max_results=max_results,
    )
    payload = []
    for item in response.items:
        trial = item.model_dump()
        trial["months_to_primary_completion"] = months_between(
            trial.get("start_date"),
            trial.get("primary_completion_date"),
        )
        trial["months_to_completion"] = months_between(
            trial.get("start_date"),
            trial.get("completion_date"),
        )
        trial["months_since_start"] = months_since(trial.get("start_date"))
        payload.append(trial)
    return list_response(
        tool_name="get_trial_timelines",
        data_type="trial_timeline",
        items=payload,
        quality_note="Timeline fields are normalized from registered trial registry sources and intended for velocity analysis.",
        coverage="Currently backed by ClinicalTrials.gov timeline data.",
        queried_sources=response.queried_sources,
        warnings=[warning.as_dict() for warning in response.warnings],
        evidence_sources=response.queried_sources,
        evidence_trace=[
            {
                "step": "fetch_trial_timelines",
                "sources": response.queried_sources,
                "note": "Retrieved start, completion, and enrollment fields for matching trials.",
                "filters": {
                    "indication": resolved_indication,
                    "sponsor": sponsor,
                    "phase": phase,
                    "status": status,
                    "max_results": max_results,
                },
                "output_kind": "raw",
                "refs": payload,
            },
            {
                "step": "derive_duration_metrics",
                "sources": response.queried_sources,
                "note": "Computed months-to-completion and months-since-start from normalized timeline dates.",
                "filters": {"indication": resolved_indication},
                "output_kind": "derived",
                "refs": payload,
            },
        ],
        requested_filters={
            "indication": resolved_indication,
            "condition": condition,
            "sponsor": sponsor,
            "phase": phase,
            "status": status,
            "max_results": max_results,
        },
    )
