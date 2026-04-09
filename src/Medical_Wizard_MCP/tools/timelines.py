from typing import Any

from ..server import mcp
from ..sources import registry
from ._intelligence import months_between, months_since
from ._responses import list_response


@mcp.tool()
async def get_trial_timelines(
    condition: str,
    sponsor: str | None = None,
    phase: str | None = None,
    status: str | None = None,
    max_results: int = 15,
) -> dict[str, Any]:
    """Get start dates, completion dates, and enrollment numbers for clinical trials in a given indication.

Use this to analyze how fast competitors are moving, estimate time-to-market, compare recruitment speed across sponsors, or assess feasibility of similar study designs.

Returns a standardized list envelope with `_meta`, `count`, and `results`.
Each trial timeline includes: nct_id, brief_title, phase, lead_sponsor, start_date, primary_completion_date, completion_date, enrollment_count, source.

Args:
    condition: Disease or condition (e.g. "NSCLC", "breast cancer", "glioblastoma")
    sponsor: Filter to a specific sponsor (e.g. "Roche", "Merck") — omit to see all sponsors
    phase: Optional phase filter (e.g. "PHASE2", "Phase 3")
    status: Optional status filter (e.g. "RECRUITING", "COMPLETED")
    max_results: Number of results (default 15, max 30)
    """
    max_results = min(max_results, 30)
    response = await registry.get_trial_timelines(
        condition=condition,
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
        requested_filters={
            "condition": condition,
            "sponsor": sponsor,
            "phase": phase,
            "status": status,
            "max_results": max_results,
        },
    )
