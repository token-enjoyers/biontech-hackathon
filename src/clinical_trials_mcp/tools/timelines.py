from clinical_trials_mcp.server import mcp
from clinical_trials_mcp.sources import registry


@mcp.tool()
async def get_trial_timelines(
    condition: str,
    sponsor: str | None = None,
    max_results: int = 15,
) -> list[dict]:
    """Get start dates, completion dates, and enrollment numbers for clinical trials in a given indication.

Use this to analyze how fast competitors are moving, estimate time-to-market, compare recruitment speed across sponsors, or assess feasibility of similar study designs.

Returns for each trial: nct_id, brief_title, phase, lead_sponsor, start_date, primary_completion_date, completion_date, enrollment_count, source.

Args:
    condition: Disease or condition (e.g. "NSCLC", "breast cancer", "glioblastoma")
    sponsor: Filter to a specific sponsor (e.g. "Roche", "Merck") — omit to see all sponsors
    max_results: Number of results (default 15, max 30)
    """
    max_results = min(max_results, 30)
    results = await registry.get_trial_timelines(
        condition=condition,
        sponsor=sponsor,
        max_results=max_results,
    )
    return [r.model_dump() for r in results]
