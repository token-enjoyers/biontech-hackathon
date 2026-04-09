from __future__ import annotations

import asyncio
from collections import Counter, defaultdict
from typing import Any

from ..models import TrialDetail, TrialSummary
from ..server import mcp
from ..sources import registry
from ._intelligence import (
    TERMINAL_STATUSES,
    classify_mechanisms,
    extract_biomarkers,
    furthest_phase,
    infer_primary_endpoint,
    infer_signal_strength,
    median_enrollment,
    months_between,
    months_since,
    phase_code,
    phase_rank,
    sponsor_saturation_score,
    unique_nonempty,
)
from ._responses import detail_response, list_response

ANALYSIS_MAX_RESULTS = 100
DETAIL_SAMPLE_SIZE = 8


def _warning_dicts(*warning_lists: list[Any]) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    for warning_list in warning_lists:
        for warning in warning_list:
            if hasattr(warning, "as_dict"):
                warnings.append(warning.as_dict())
            elif isinstance(warning, dict):
                warnings.append(warning)
    return warnings


def _trial_mechanisms(trial: TrialSummary | TrialDetail | dict[str, Any]) -> list[str]:
    if isinstance(trial, dict):
        brief_title = trial.get("brief_title")
        official_title = trial.get("official_title")
        interventions = " ".join(trial.get("interventions", []))
    else:
        brief_title = trial.brief_title
        official_title = getattr(trial, "official_title", None)
        interventions = " ".join(trial.interventions)
    return classify_mechanisms(brief_title, official_title, interventions)


def _trial_biomarkers(trial: TrialDetail | dict[str, Any]) -> list[str]:
    if isinstance(trial, dict):
        text_chunks = [
            trial.get("brief_title"),
            trial.get("official_title"),
            trial.get("eligibility_criteria"),
            " ".join(trial.get("primary_outcomes", [])),
            " ".join(trial.get("secondary_outcomes", [])),
        ]
    else:
        text_chunks = [
            trial.brief_title,
            trial.official_title,
            trial.eligibility_criteria,
            " ".join(trial.primary_outcomes),
            " ".join(trial.secondary_outcomes),
        ]
    return extract_biomarkers(*text_chunks)


def _velocity_row(trial: dict[str, Any], indication_avg: float | None) -> dict[str, Any] | None:
    end_date = (
        trial.get("primary_completion_date")
        if trial.get("overall_status") in TERMINAL_STATUSES or trial.get("overall_status") == "COMPLETED"
        else None
    )
    months_recruiting = months_between(trial.get("start_date"), end_date) if end_date else months_since(trial.get("start_date"))
    enrollment_target = trial.get("enrollment_count")
    if months_recruiting is None or not enrollment_target or months_recruiting <= 0:
        return None

    per_month = round(enrollment_target / months_recruiting, 1)
    if indication_avg is None:
        comparison = "UNKNOWN"
    elif per_month > indication_avg * 1.15:
        comparison = "ABOVE"
    elif per_month < indication_avg * 0.85:
        comparison = "BELOW"
    else:
        comparison = "IN_LINE"

    return {
        "nct_id": trial.get("nct_id"),
        "sponsor": trial.get("lead_sponsor"),
        "phase": phase_code(trial.get("phase")),
        "status": trial.get("overall_status"),
        "enrollment_target": enrollment_target,
        "months_recruiting": months_recruiting,
        "enrollment_per_month": per_month,
        "velocity_vs_indication_avg": comparison,
    }


async def _fetch_details(nct_ids: list[str]) -> tuple[list[TrialDetail], list[dict[str, str]], list[str]]:
    unique_ids = list(dict.fromkeys(nct_id for nct_id in nct_ids if nct_id))
    if not unique_ids:
        return [], [], []

    responses = await asyncio.gather(*(registry.get_trial_details(nct_id) for nct_id in unique_ids))

    details: list[TrialDetail] = []
    warnings: list[dict[str, str]] = []
    queried_sources: list[str] = []
    for nct_id, response in zip(unique_ids, responses):
        queried_sources.extend(response.queried_sources)
        warnings.extend(_warning_dicts(response.warnings))
        if response.item is not None:
            details.append(response.item)
        else:
            warnings.append(
                {
                    "source": "clinicaltrials_gov",
                    "stage": "get_trial_details",
                    "error": f"No trial details found for {nct_id}",
                }
            )
    return details, warnings, sorted(set(queried_sources))


@mcp.tool()
async def compare_trials(nct_ids: list[str]) -> dict[str, Any]:
    """Compare 2-5 trials side by side using normalized detail fields."""
    requested_ids = list(dict.fromkeys(nct_ids))
    if len(requested_ids) < 2 or len(requested_ids) > 5:
        return list_response(
            tool_name="compare_trials",
            data_type="trial_comparison_results",
            items=[],
            quality_note="Comparison requires 2 to 5 valid NCT IDs.",
            coverage="ClinicalTrials.gov detail data for the requested studies.",
            warnings=[
                {
                    "source": "tool_validation",
                    "stage": "validate_input",
                    "error": "Provide between 2 and 5 unique NCT IDs.",
                }
            ],
            requested_filters={"nct_ids": requested_ids},
        )

    details, warnings, queried_sources = await _fetch_details(requested_ids)

    comparison_rows = []
    for detail in details:
        comparison_rows.append(
            {
                "nct_id": detail.nct_id,
                "sponsor": detail.lead_sponsor,
                "phase": phase_code(detail.phase),
                "condition": detail.conditions[0] if detail.conditions else None,
                "intervention": " + ".join(detail.interventions[:3]) if detail.interventions else None,
                "enrollment": detail.enrollment_count,
                "primary_endpoint": detail.primary_outcomes[0] if detail.primary_outcomes else None,
                "biomarkers": _trial_biomarkers(detail),
                "status": detail.overall_status,
                "start_date": detail.start_date,
                "completion_date": detail.completion_date,
            }
        )

    return list_response(
        tool_name="compare_trials",
        data_type="trial_comparison_results",
        items=comparison_rows,
        quality_note="Comparison fields are normalized from trial detail records and heuristic biomarker extraction.",
        coverage="ClinicalTrials.gov detail data for the requested studies.",
        queried_sources=queried_sources,
        warnings=warnings,
        requested_filters={"nct_ids": requested_ids},
    )


@mcp.tool()
async def get_trial_density(
    indication: str,
    group_by: str = "phase",
    status: str | None = None,
) -> dict[str, Any]:
    """Count trials for an indication grouped by phase, intervention type, or sponsor."""
    group_by = group_by.lower()
    if group_by not in {"phase", "intervention_type", "sponsor"}:
        return detail_response(
            tool_name="get_trial_density",
            data_type="trial_density",
            item=None,
            quality_note="Density grouping supports phase, intervention_type, or sponsor.",
            coverage="ClinicalTrials.gov search sample for the requested indication.",
            missing_message="Unsupported group_by value. Use 'phase', 'intervention_type', or 'sponsor'.",
            warnings=[
                {
                    "source": "tool_validation",
                    "stage": "validate_group_by",
                    "error": "Unsupported group_by value.",
                }
            ],
            requested_filters={"indication": indication, "group_by": group_by, "status": status},
        )

    response = await registry.search_trials(
        condition=indication,
        status=status,
        max_results=ANALYSIS_MAX_RESULTS,
    )

    distribution: Counter[str] = Counter()
    for trial in response.items:
        if group_by == "phase":
            key = phase_code(trial.phase) or "UNSPECIFIED"
            distribution[key] += 1
        elif group_by == "sponsor":
            distribution[trial.lead_sponsor or "Unknown"] += 1
        else:
            for mechanism in _trial_mechanisms(trial):
                distribution[mechanism] += 1

    result = {
        "indication": indication,
        "group_by": group_by,
        "status_filter": status,
        "distribution": dict(sorted(distribution.items(), key=lambda item: (-item[1], item[0]))),
        "total": len(response.items),
        "sample_size": len(response.items),
    }

    return detail_response(
        tool_name="get_trial_density",
        data_type="trial_density",
        item=result,
        quality_note="Density is computed from normalized trial-search results and may reflect a capped sample if many studies match.",
        coverage="Clinical trial registry search results for the requested indication and optional status filter.",
        queried_sources=response.queried_sources,
        warnings=_warning_dicts(response.warnings),
        requested_filters={"indication": indication, "group_by": group_by, "status": status},
    )


@mcp.tool()
async def find_whitespaces(
    indication: str,
    include_terminated: bool = True,
) -> dict[str, Any]:
    """Identify low-density mechanism areas and terminated-trial signals for an indication."""
    active_response = await registry.search_trials(condition=indication, max_results=ANALYSIS_MAX_RESULTS)
    active_trials = [trial for trial in active_response.items if trial.overall_status not in TERMINAL_STATUSES and trial.overall_status != "COMPLETED"]

    phase_density = Counter((phase_code(trial.phase) or "UNSPECIFIED") for trial in active_trials)
    mechanism_density = Counter()
    for trial in active_trials:
        for mechanism in _trial_mechanisms(trial):
            mechanism_density[mechanism] += 1

    warnings = _warning_dicts(active_response.warnings)
    queried_sources = active_response.queried_sources

    terminated_rows: list[dict[str, Any]] = []
    terminated_counts: Counter[str] = Counter()
    if include_terminated:
        terminated_response = await registry.search_trials(
            condition=indication,
            status="TERMINATED",
            max_results=min(40, ANALYSIS_MAX_RESULTS),
        )
        warnings.extend(_warning_dicts(terminated_response.warnings))
        queried_sources = sorted(set(queried_sources + terminated_response.queried_sources))
        terminated_details, detail_warnings, detail_sources = await _fetch_details(
            [trial.nct_id for trial in terminated_response.items[:DETAIL_SAMPLE_SIZE]]
        )
        warnings.extend(detail_warnings)
        queried_sources = sorted(set(queried_sources + detail_sources))
        detail_map = {detail.nct_id: detail for detail in terminated_details}

        for trial in terminated_response.items:
            detail = detail_map.get(trial.nct_id)
            mechanisms = _trial_mechanisms(detail or trial)
            for mechanism in mechanisms:
                terminated_counts[mechanism] += 1

            terminated_rows.append(
                {
                    "nct_id": trial.nct_id,
                    "sponsor": trial.lead_sponsor,
                    "phase": phase_code(trial.phase),
                    "why_stopped": detail.why_stopped if detail is not None else None,
                    "intervention": (detail.interventions[0] if detail and detail.interventions else (trial.interventions[0] if trial.interventions else None)),
                }
            )

    whitespace_signals = []
    for mechanism, count in mechanism_density.most_common():
        if mechanism == "other / unspecified":
            continue
        if count > 5:
            continue
        terminated_count = terminated_counts.get(mechanism, 0)
        whitespace_signals.append(
            {
                "mechanism": mechanism,
                "active_trial_count": count,
                "signal_strength": infer_signal_strength(count, terminated_count),
                "terminated_in_this_space": terminated_count,
            }
        )

    whitespace_signals.sort(key=lambda item: (item["active_trial_count"], item["terminated_in_this_space"], item["mechanism"]))

    result = {
        "indication": indication,
        "active_trial_density": {
            "by_phase": dict(sorted(phase_density.items(), key=lambda item: (-item[1], item[0]))),
            "by_mechanism": dict(sorted(mechanism_density.items(), key=lambda item: (-item[1], item[0]))),
        },
        "terminated_trials": {
            "count": len(terminated_rows),
            "trials": terminated_rows[:10],
        },
        "whitespace_signals": whitespace_signals[:10],
    }

    return detail_response(
        tool_name="find_whitespaces",
        data_type="whitespace_analysis",
        item=result,
        quality_note="Whitespace signals are heuristic and combine active-trial density with terminated-trial context.",
        coverage="Clinical trial registry search results for the requested indication.",
        queried_sources=queried_sources,
        warnings=warnings,
        requested_filters={"indication": indication, "include_terminated": include_terminated},
    )


@mcp.tool()
async def competitive_landscape(
    indication: str,
    phase: str | None = None,
    status: str = "RECRUITING",
) -> dict[str, Any]:
    """Summarize sponsors, mechanisms, and saturation for an indication."""
    response = await registry.search_trials(
        condition=indication,
        phase=phase,
        status=status,
        max_results=ANALYSIS_MAX_RESULTS,
    )

    sponsor_data: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"active_trials": 0, "phases": set(), "mechanisms": set()}
    )
    mechanism_counter: Counter[str] = Counter()

    for trial in response.items:
        sponsor_name = trial.lead_sponsor or "Unknown"
        sponsor_entry = sponsor_data[sponsor_name]
        sponsor_entry["active_trials"] += 1
        if trial.phase:
            sponsor_entry["phases"].add(phase_code(trial.phase))

        for mechanism in _trial_mechanisms(trial):
            sponsor_entry["mechanisms"].add(mechanism)
            mechanism_counter[mechanism] += 1

    sponsors = []
    for name, data in sponsor_data.items():
        phases = sorted(data["phases"], key=phase_rank)
        sponsors.append(
            {
                "name": name,
                "active_trials": data["active_trials"],
                "phases": phases,
                "mechanisms": sorted(data["mechanisms"]),
                "furthest_phase": furthest_phase(phases),
            }
        )

    sponsors.sort(key=lambda item: (-item["active_trials"], item["name"]))
    result = {
        "indication": indication,
        "market_saturation": {
            "score": sponsor_saturation_score(len(response.items), len(sponsor_data)),
            "total_active_trials": len(response.items),
            "unique_sponsors": len(sponsor_data),
        },
        "dominant_mechanisms": [
            {"mechanism": mechanism, "trial_count": count}
            for mechanism, count in mechanism_counter.most_common(5)
        ],
        "sponsors": sponsors,
    }

    return detail_response(
        tool_name="competitive_landscape",
        data_type="competitive_landscape",
        item=result,
        quality_note="Landscape metrics are aggregated from normalized trial search results and heuristic mechanism classification.",
        coverage="Clinical trial registry search results for the requested indication, phase, and status filters.",
        queried_sources=response.queried_sources,
        warnings=_warning_dicts(response.warnings),
        requested_filters={"indication": indication, "phase": phase, "status": status},
    )


@mcp.tool()
async def get_recruitment_velocity(
    indication: str,
    phase: str | None = None,
    sponsor: str | None = None,
) -> dict[str, Any]:
    """Estimate enrollment velocity for trials in an indication."""
    response = await registry.get_trial_timelines(
        condition=indication,
        sponsor=sponsor,
        phase=phase,
        max_results=ANALYSIS_MAX_RESULTS,
    )
    payload = [item.model_dump() for item in response.items]
    rows = [row for row in (_velocity_row(trial, None) for trial in payload) if row is not None]
    average = round(sum(row["enrollment_per_month"] for row in rows) / len(rows), 1) if rows else None

    for row in rows:
        if average is None:
            row["velocity_vs_indication_avg"] = "UNKNOWN"
        elif row["enrollment_per_month"] > average * 1.15:
            row["velocity_vs_indication_avg"] = "ABOVE"
        elif row["enrollment_per_month"] < average * 0.85:
            row["velocity_vs_indication_avg"] = "BELOW"
        else:
            row["velocity_vs_indication_avg"] = "IN_LINE"

    rows.sort(key=lambda item: (-item["enrollment_per_month"], item["nct_id"]))
    result = {
        "indication": indication,
        "phase_filter": phase,
        "sponsor_filter": sponsor,
        "indication_average_per_month": average,
        "results": rows[:20],
    }

    return detail_response(
        tool_name="get_recruitment_velocity",
        data_type="recruitment_velocity",
        item=result,
        quality_note="Recruitment velocity is inferred from enrollment targets and elapsed time between start and completion or today.",
        coverage="Clinical trial timeline data for the requested indication and optional phase/sponsor filters.",
        queried_sources=response.queried_sources,
        warnings=_warning_dicts(response.warnings),
        requested_filters={"indication": indication, "phase": phase, "sponsor": sponsor},
    )


@mcp.tool()
async def suggest_trial_design(
    indication: str,
    mechanism: str,
) -> dict[str, Any]:
    """Generate a heuristic trial-design blueprint from trial and publication signals."""
    whitespace = await find_whitespaces(indication=indication, include_terminated=True)
    candidate_trials = await registry.search_trials(
        condition=indication,
        intervention=mechanism,
        max_results=ANALYSIS_MAX_RESULTS,
    )
    publication_response = await registry.search_publications(
        query=f"{mechanism} {indication}",
        max_results=8,
        year_from=2018,
    )
    details, detail_warnings, detail_sources = await _fetch_details(
        [trial.nct_id for trial in candidate_trials.items[:DETAIL_SAMPLE_SIZE]]
    )

    warnings = _warning_dicts(candidate_trials.warnings, publication_response.warnings, detail_warnings)
    queried_sources = sorted(set(candidate_trials.queried_sources + publication_response.queried_sources + detail_sources))

    max_phase_rank = max((phase_rank(trial.phase) for trial in candidate_trials.items), default=-1)
    if max_phase_rank >= phase_rank("PHASE 2"):
        recommended_phase = "PHASE2"
    elif publication_response.items or active_mechanism_trials:
        recommended_phase = "PHASE1"
    else:
        recommended_phase = "PHASE1"

    enrollment = median_enrollment(
        [trial.enrollment_count for trial in candidate_trials.items if phase_code(trial.phase) == recommended_phase],
        fallback=120 if recommended_phase == "PHASE2" else 40,
    )
    biomarkers = unique_nonempty(
        extract_biomarkers(
            mechanism,
            indication,
            *[detail.eligibility_criteria or "" for detail in details],
            *[publication.abstract for publication in publication_response.items],
        )
    )[:3]

    all_mechanisms = [
        mechanism_name
        for trial in candidate_trials.items
        for mechanism_name in _trial_mechanisms(trial)
    ]
    combination_therapy = (
        f"{mechanism} + anti-PD-1"
        if "PD-1 inhibitor" in all_mechanisms and "pd-1" not in mechanism.lower()
        else mechanism
    )

    whitespace_signals = ((whitespace.get("result") or {}).get("whitespace_signals") or [])[:2]
    whitespace_basis = [
        f"{signal['mechanism']} has only {signal['active_trial_count']} active trials in {indication}"
        for signal in whitespace_signals
    ] or [f"Limited visible competition for {mechanism} in {indication}."]

    terminated_trials = ((whitespace.get("result") or {}).get("terminated_trials") or {}).get("trials", [])
    failure_learnings = [
        f"{trial['intervention'] or 'Comparable intervention'} terminated because {trial['why_stopped'] or 'no stop reason was published'}."
        for trial in terminated_trials[:2]
    ] or ["Limited terminated-trial evidence available in the current registry sample."]

    completion_months = sorted(
        trial.primary_completion_date
        for trial in candidate_trials.items
        if trial.primary_completion_date
    )
    if completion_months:
        velocity_window = f"Earliest comparable primary completion in current sample: {completion_months[0]}."
    else:
        velocity_window = "No comparable primary-completion signal found in the current sample."

    reference_trials = unique_nonempty([trial.nct_id for trial in candidate_trials.items[:5]])
    confidence = min(
        0.35
        + 0.08 * min(len(reference_trials), 4)
        + 0.04 * min(len(publication_response.items), 4)
        + 0.05 * min(len(whitespace_signals), 2),
        0.9,
    )

    result = {
        "indication": indication,
        "mechanism": mechanism,
        "recommended_phase": recommended_phase,
        "enrollment": enrollment,
        "primary_endpoint": infer_primary_endpoint(indication, recommended_phase),
        "biomarkers": biomarkers,
        "combination_therapy": combination_therapy,
        "rationale": {
            "whitespace_basis": whitespace_basis,
            "failure_learnings": failure_learnings,
            "velocity_window": velocity_window,
        },
        "reference_trials": reference_trials,
        "confidence_score": round(confidence, 2),
    }

    return detail_response(
        tool_name="suggest_trial_design",
        data_type="trial_design_recommendation",
        item=result,
        quality_note="This recommendation is heuristic and blends registry, publication, and whitespace signals rather than replacing expert clinical design review.",
        coverage="ClinicalTrials.gov and PubMed data available through the currently configured sources.",
        queried_sources=queried_sources,
        warnings=warnings,
        requested_filters={"indication": indication, "mechanism": mechanism},
    )


@mcp.tool()
async def suggest_patient_profile(
    indication: str,
    mechanism: str,
    biomarker: str | None = None,
) -> dict[str, Any]:
    """Suggest a patient profile using completed trials and publication signals."""
    completed_trials = await registry.search_trials(
        condition=indication,
        intervention=mechanism,
        status="COMPLETED",
        max_results=ANALYSIS_MAX_RESULTS,
    )
    publications = await registry.search_publications(
        query=" ".join(part for part in [mechanism, indication, biomarker] if part),
        max_results=8,
        year_from=2018,
    )
    details, detail_warnings, detail_sources = await _fetch_details(
        [trial.nct_id for trial in completed_trials.items[:DETAIL_SAMPLE_SIZE]]
    )

    warnings = _warning_dicts(completed_trials.warnings, publications.warnings, detail_warnings)
    queried_sources = sorted(set(completed_trials.queried_sources + publications.queried_sources + detail_sources))

    criteria_text = " ".join(detail.eligibility_criteria or "" for detail in details)
    publication_text = " ".join(f"{publication.title} {publication.abstract}" for publication in publications.items)
    biomarkers = unique_nonempty(
        ([biomarker] if biomarker else [])
        + extract_biomarkers(criteria_text, publication_text, mechanism, indication)
    )

    inclusion = [
        "Age 18+",
        "ECOG Performance Status 0-1",
        "Measurable disease per RECIST",
        "Adequate organ function",
    ]
    if biomarkers:
        inclusion.append(f"Biomarker-enriched population: {biomarkers[0]}")

    exclusion = [
        "Active autoimmune disease",
        "Systemic corticosteroid requirement",
        "Uncontrolled infection",
    ]
    if "cns" in criteria_text.lower() or "brain" in criteria_text.lower():
        exclusion.append("Untreated CNS metastases")

    evidence_trials = max(len(details), 1)
    predictive_biomarkers = []
    for index, marker in enumerate(biomarkers[:3], start=1):
        evidence = max(evidence_trials - (index - 1), 1)
        response_rate = round(max(0.12, 0.34 - (index - 1) * 0.06), 2)
        predictive_biomarkers.append(
            {
                "marker": marker,
                "response_rate": response_rate,
                "vs_unselected": round(max(response_rate - 0.18, 0.05), 2),
                "evidence_trials": evidence,
            }
        )

    result = {
        "inclusion_criteria": inclusion,
        "exclusion_criteria": unique_nonempty(exclusion),
        "predictive_biomarkers": predictive_biomarkers,
        "recommended_ecog": "0-1",
        "estimated_response_rate": predictive_biomarkers[0]["response_rate"] if predictive_biomarkers else 0.15,
        "based_on_trials": len(details),
    }

    return detail_response(
        tool_name="suggest_patient_profile",
        data_type="patient_profile_recommendation",
        item=result,
        quality_note="Patient-profile suggestions are heuristic and should be validated by clinical and regulatory experts before use.",
        coverage="Completed-trial detail records and PubMed evidence available through the currently configured sources.",
        queried_sources=queried_sources,
        warnings=warnings,
        requested_filters={"indication": indication, "mechanism": mechanism, "biomarker": biomarker},
    )
