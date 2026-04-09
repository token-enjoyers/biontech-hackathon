from ..server import mcp
from ..sources import registry


@mcp.tool()
async def search_trials(
    condition: str,
    phase: str | None = None,
    status: str | None = None,
    sponsor: str | None = None,
    intervention: str | None = None,
    max_results: int = 10,
) -> list[dict]:
    """Search clinical trials by condition, phase, status, sponsor, or intervention.

This is the primary discovery tool. Use it to find trials for a given disease, identify competitors, or find terminated/failed trials for failure analysis.

Returns for each trial: nct_id, brief_title, phase, overall_status, lead_sponsor, interventions, primary_outcomes, enrollment_count, source.

Args:
    condition: Disease or condition (e.g. "lung cancer", "NSCLC", "glioblastoma", "pancreatic cancer")
    phase: Trial phase — one of EARLY_PHASE1, PHASE1, PHASE2, PHASE3, PHASE4
    status: Recruitment status — one of RECRUITING, NOT_YET_RECRUITING, ACTIVE_NOT_RECRUITING, COMPLETED, TERMINATED, WITHDRAWN, SUSPENDED
    sponsor: Sponsor organization name (e.g. "Merck", "BioNTech", "Pfizer")
    intervention: Drug or therapy name (e.g. "pembrolizumab", "mRNA vaccine")
    max_results: Number of results (default 10, max 20)
    """
    max_results = min(max_results, 20)
    results = await registry.search_trials(
        condition=condition,
        phase=phase,
        status=status,
        sponsor=sponsor,
        intervention=intervention,
        max_results=max_results,
    )
    return [r.model_dump() for r in results]


@mcp.tool()
async def get_trial_details(nct_id: str) -> dict | str:
    """Get full details for a single clinical trial by NCT ID.

Use this after search_trials to dive deeper into a specific trial — e.g. to inspect eligibility criteria, study arms, secondary outcomes, or study design.

Returns: nct_id, brief_title, official_title, phase, overall_status, lead_sponsor, interventions, primary_outcomes, secondary_outcomes, eligibility_criteria, arms, study_type, conditions, enrollment_count, source.

Args:
    nct_id: The ClinicalTrials.gov identifier (e.g. "NCT05012345")
    """
    detail = await registry.get_trial_details(nct_id)
    if detail is None:
        return f"No trial found with ID {nct_id}"
    return detail.model_dump()
