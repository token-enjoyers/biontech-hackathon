from __future__ import annotations

import asyncio
from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import Any

from ..models import TrialDetail, TrialSummary
from ..server import mcp
from ..sources import registry
from ._intelligence import (
    ACTIVE_STATUSES,
    add_months_to_date,
    TERMINAL_STATUSES,
    classify_endpoint,
    classify_mechanisms,
    extract_comparator_signals,
    extract_biomarkers,
    extract_eligibility_features,
    extract_patient_segments,
    extract_safety_signals,
    furthest_phase,
    infer_primary_endpoint,
    infer_signal_strength,
    median_enrollment,
    months_between,
    months_since,
    months_until,
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


def _trace_step(
    step: str,
    *,
    sources: list[str] | None,
    note: str,
    filters: dict[str, Any] | None = None,
    output_kind: str,
) -> dict[str, Any]:
    return {
        "step": step,
        "sources": sorted(set(sources or [])),
        "note": note,
        "filters": {
            key: value
            for key, value in (filters or {}).items()
            if value is not None and value != "" and value != []
        },
        "output_kind": output_kind,
    }


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


async def _fetch_details(
    nct_ids: list[str],
) -> tuple[list[TrialDetail], list[dict[str, str]], list[str], list[dict[str, Any]]]:
    unique_ids = list(dict.fromkeys(nct_id for nct_id in nct_ids if nct_id))
    if not unique_ids:
        return [], [], [], []

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
    unique_sources = sorted(set(queried_sources))
    trace = [
        _trace_step(
            "fetch_trial_details",
            sources=unique_sources,
            note="Loaded trial detail records for the selected NCT identifiers.",
            filters={"nct_ids": unique_ids},
            output_kind="raw",
        )
    ]
    return details, warnings, unique_sources, trace


async def _collect_trials_and_details(
    *,
    indication: str,
    phase: str | None = None,
    status: str | None = None,
    sponsor: str | None = None,
    mechanism: str | None = None,
    max_results: int = ANALYSIS_MAX_RESULTS,
    detail_limit: int = DETAIL_SAMPLE_SIZE * 2,
) -> tuple[list[TrialSummary], list[TrialDetail], list[dict[str, str]], list[str], list[dict[str, Any]]]:
    response = await registry.search_trials(
        condition=indication,
        phase=phase,
        status=status,
        sponsor=sponsor,
        intervention=mechanism,
        max_results=max_results,
    )
    details, detail_warnings, detail_sources, detail_trace = await _fetch_details(
        [trial.nct_id for trial in response.items[:detail_limit]]
    )
    warnings = _warning_dicts(response.warnings, detail_warnings)
    queried_sources = sorted(set(response.queried_sources + detail_sources))
    trace = [
        _trace_step(
            "search_trial_registry",
            sources=response.queried_sources,
            note="Collected comparable trial rows as the starting evidence set.",
            filters={
                "indication": indication,
                "phase": phase,
                "status": status,
                "sponsor": sponsor,
                "mechanism": mechanism,
                "max_results": max_results,
            },
            output_kind="raw",
        ),
        *detail_trace,
    ]
    return response.items, details, warnings, queried_sources, trace


def _merged_trial_text(trial: TrialSummary | TrialDetail) -> str:
    parts = [
        trial.brief_title,
        getattr(trial, "official_title", None),
        " ".join(getattr(trial, "conditions", [])),
        getattr(trial, "eligibility_criteria", None),
        " ".join(trial.interventions),
        " ".join(trial.primary_outcomes),
        " ".join(getattr(trial, "secondary_outcomes", [])),
    ]
    return " ".join(part for part in parts if part)


def _top_counter_rows(counter: Counter[str], limit: int = 10) -> list[dict[str, Any]]:
    return [
        {"label": label, "count": count}
        for label, count in counter.most_common(limit)
    ]


def _intelligence_year_floor(recent_years: int) -> int:
    current_year = datetime.now(UTC).year
    return current_year - max(recent_years - 1, 0)


def _normalize_asset_name(intervention: str) -> str:
    value = intervention.strip()
    if not value:
        return "Unknown asset"
    lowered = value.lower()
    if lowered in {"placebo", "standard of care", "best supportive care"}:
        return ""
    return value


def _design_archetype(detail: TrialDetail) -> str:
    arm_count = len(detail.arms)
    intervention_count = len(detail.interventions)
    if intervention_count >= 2:
        combo_label = "combination"
    elif intervention_count == 1:
        combo_label = "monotherapy"
    else:
        combo_label = "unspecified therapy model"

    if arm_count >= 3:
        arm_label = "multi-arm"
    elif arm_count == 2:
        arm_label = "two-arm"
    elif arm_count == 1:
        arm_label = "single-arm"
    else:
        arm_label = "arm structure unspecified"

    return f"{arm_label} {combo_label}"


def _forecast_rows_from_trials(
    trials: list[TrialSummary],
    *,
    months_ahead: int,
) -> tuple[list[dict[str, Any]], dict[str, float]]:
    phase_benchmarks: dict[str, list[float]] = defaultdict(list)
    for trial in trials:
        duration = months_between(trial.start_date, trial.primary_completion_date)
        code = phase_code(trial.phase)
        if duration is not None and code:
            phase_benchmarks[code].append(duration)

    benchmark_medians = {
        phase_name: round(sum(values) / len(values), 1)
        for phase_name, values in phase_benchmarks.items()
        if values
    }
    fallback_months = {"PHASE1": 18, "PHASE1/PHASE2": 24, "PHASE2": 30, "PHASE2/PHASE3": 36, "PHASE3": 42}

    rows: list[dict[str, Any]] = []
    for trial in trials:
        known_date = trial.primary_completion_date or trial.completion_date
        months_to_known = months_until(known_date)
        code = phase_code(trial.phase)

        estimated_date = None
        confidence = "LOW"
        basis = "No forecast basis available."
        if known_date:
            estimated_date = known_date
            confidence = "HIGH"
            basis = "Uses the registered primary/completion date."
        elif code and trial.start_date:
            estimate_months = int(round(benchmark_medians.get(code, fallback_months.get(code, 30))))
            estimated_date = add_months_to_date(trial.start_date, estimate_months)
            confidence = "MEDIUM" if code in benchmark_medians else "LOW"
            basis = "Estimated from observed phase benchmark duration." if code in benchmark_medians else "Estimated from fallback phase duration."

        months_to_estimated = months_until(estimated_date)
        if (
            estimated_date is None
            or months_to_estimated is None
            or months_to_estimated < 0
            or months_to_estimated > months_ahead
        ):
            continue

        rows.append(
            {
                "nct_id": trial.nct_id,
                "sponsor": trial.lead_sponsor,
                "phase": code,
                "status": trial.overall_status,
                "known_primary_completion_date": known_date,
                "estimated_readout_date": estimated_date,
                "months_until_readout": months_to_estimated,
                "forecast_confidence": confidence,
                "forecast_basis": basis,
            }
        )

    rows.sort(key=lambda item: (item["months_until_readout"], item["nct_id"]))
    return rows, benchmark_medians


async def _analyze_competition_gaps_impl(
    *,
    indication: str,
    include_terminated: bool,
    tool_name: str,
) -> dict[str, Any]:
    active_response = await registry.search_trials(condition=indication, max_results=ANALYSIS_MAX_RESULTS)
    active_trials = [
        trial
        for trial in active_response.items
        if trial.overall_status not in TERMINAL_STATUSES and trial.overall_status != "COMPLETED"
    ]

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
        terminated_details, detail_warnings, detail_sources, detail_trace = await _fetch_details(
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
                    "intervention": (
                        detail.interventions[0]
                        if detail and detail.interventions
                        else (trial.interventions[0] if trial.interventions else None)
                    ),
                }
            )

    gap_signals = []
    for mechanism, count in mechanism_density.most_common():
        if mechanism == "other / unspecified":
            continue
        if count > 5:
            continue
        terminated_count = terminated_counts.get(mechanism, 0)
        gap_signals.append(
            {
                "mechanism": mechanism,
                "active_trial_count": count,
                "signal_strength": infer_signal_strength(count, terminated_count),
                "terminated_in_this_space": terminated_count,
            }
        )

    gap_signals.sort(key=lambda item: (item["active_trial_count"], item["terminated_in_this_space"], item["mechanism"]))

    result = {
        "analysis_type": "heuristic_gap_scan",
        "indication": indication,
        "active_trial_density": {
            "by_phase": dict(sorted(phase_density.items(), key=lambda item: (-item[1], item[0]))),
            "by_mechanism": dict(sorted(mechanism_density.items(), key=lambda item: (-item[1], item[0]))),
        },
        "terminated_trials": {
            "count": len(terminated_rows),
            "trials": terminated_rows[:10],
        },
        "gap_signals": gap_signals[:10],
        "heuristic_basis": "Low-density mechanism areas are highlighted using active-trial counts plus terminated-trial context.",
    }

    return detail_response(
        tool_name=tool_name,
        data_type="competition_gap_analysis",
        item=result,
        quality_note="Competition-gap signals are heuristic and combine active-trial density with terminated-trial context.",
        coverage="Clinical trial registry search results for the requested indication.",
        queried_sources=queried_sources,
        warnings=warnings,
        evidence_sources=queried_sources,
        evidence_trace=[
            _trace_step(
                "search_active_trials",
                sources=active_response.queried_sources,
                note="Collected active or non-completed trials for mechanism-density analysis.",
                filters={"indication": indication, "max_results": ANALYSIS_MAX_RESULTS},
                output_kind="raw",
            ),
            *(
                [
                    _trace_step(
                        "search_terminated_trials",
                        sources=terminated_response.queried_sources,
                        note="Collected terminated trials to add stop-signal context.",
                        filters={"indication": indication, "status": "TERMINATED"},
                        output_kind="raw",
                    ),
                    *detail_trace,
                ]
                if include_terminated
                else []
            ),
            _trace_step(
                "score_competition_gaps",
                sources=queried_sources,
                note="Classified mechanisms and scored low-density spaces using simple rule-based thresholds.",
                filters={"indication": indication, "include_terminated": include_terminated},
                output_kind="heuristic",
            ),
        ],
        requested_filters={"indication": indication, "include_terminated": include_terminated},
    )


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

    details, warnings, queried_sources, detail_trace = await _fetch_details(requested_ids)

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
        evidence_sources=queried_sources,
        evidence_trace=[
            *detail_trace,
            _trace_step(
                "compare_trial_fields",
                sources=queried_sources,
                note="Aligned comparable trial fields and extracted biomarker hints from normalized detail text.",
                filters={"nct_ids": requested_ids},
                output_kind="derived",
            ),
        ],
        requested_filters={"nct_ids": requested_ids},
    )


@mcp.tool()
async def get_trial_density(
    indication: str,
    group_by: str = "phase",
    status: str | None = None,
) -> dict[str, Any]:
    """Derived density summary for one indication.

Use this when you need counts by phase, intervention type, or sponsor rather than raw trial rows.
    """
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
        evidence_sources=response.queried_sources,
        evidence_trace=[
            _trace_step(
                "search_trial_registry",
                sources=response.queried_sources,
                note="Fetched comparable trials for the requested indication and optional status filter.",
                filters={"indication": indication, "status": status, "max_results": ANALYSIS_MAX_RESULTS},
                output_kind="raw",
            ),
            _trace_step(
                "aggregate_trial_density",
                sources=response.queried_sources,
                note="Grouped the retrieved trial rows by phase, sponsor, or heuristic intervention type.",
                filters={"indication": indication, "group_by": group_by, "status": status},
                output_kind="derived",
            ),
        ],
        requested_filters={"indication": indication, "group_by": group_by, "status": status},
    )


@mcp.tool()
async def analyze_competition_gaps(
    indication: str,
    include_terminated: bool = True,
) -> dict[str, Any]:
    """Heuristic gap-analysis tool for one indication.

Use this only when the user wants a gap scan or whitespace-style recommendation. Prefer raw discovery tools when you want the LLM to reason from evidence itself.
    """
    return await _analyze_competition_gaps_impl(
        indication=indication,
        include_terminated=include_terminated,
        tool_name="analyze_competition_gaps",
    )


@mcp.tool()
async def find_whitespaces(
    indication: str,
    include_terminated: bool = True,
) -> dict[str, Any]:
    """Deprecated alias for analyze_competition_gaps.

Use `analyze_competition_gaps` for new integrations. This alias is kept for backward compatibility only.
    """
    response = await _analyze_competition_gaps_impl(
        indication=indication,
        include_terminated=include_terminated,
        tool_name="find_whitespaces",
    )
    result = response.get("result")
    if isinstance(result, dict) and "gap_signals" in result and "whitespace_signals" not in result:
        result["whitespace_signals"] = result["gap_signals"]
    return response


@mcp.tool()
async def competitive_landscape(
    indication: str,
    phase: str | None = None,
    status: str = "RECRUITING",
) -> dict[str, Any]:
    """Derived market snapshot for one indication.

Use this when you want sponsor and mechanism concentration rather than raw trial records.
    """
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
        evidence_sources=response.queried_sources,
        evidence_trace=[
            _trace_step(
                "search_trial_registry",
                sources=response.queried_sources,
                note="Fetched trial rows for the requested competitive slice.",
                filters={"indication": indication, "phase": phase, "status": status, "max_results": ANALYSIS_MAX_RESULTS},
                output_kind="raw",
            ),
            _trace_step(
                "aggregate_competitive_landscape",
                sources=response.queried_sources,
                note="Grouped trials by sponsor and heuristic mechanism labels, then computed a simple saturation score.",
                filters={"indication": indication, "phase": phase, "status": status},
                output_kind="derived",
            ),
        ],
        requested_filters={"indication": indication, "phase": phase, "status": status},
    )


@mcp.tool()
async def get_recruitment_velocity(
    indication: str,
    phase: str | None = None,
    sponsor: str | None = None,
) -> dict[str, Any]:
    """Derived enrollment-velocity estimate for comparable trials."""
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
        evidence_sources=response.queried_sources,
        evidence_trace=[
            _trace_step(
                "fetch_trial_timelines",
                sources=response.queried_sources,
                note="Retrieved normalized timeline rows for the requested indication.",
                filters={"indication": indication, "phase": phase, "sponsor": sponsor, "max_results": ANALYSIS_MAX_RESULTS},
                output_kind="raw",
            ),
            _trace_step(
                "estimate_recruitment_velocity",
                sources=response.queried_sources,
                note="Estimated enrollment-per-month from enrollment targets and observed or elapsed durations.",
                filters={"indication": indication, "phase": phase, "sponsor": sponsor},
                output_kind="derived",
            ),
        ],
        requested_filters={"indication": indication, "phase": phase, "sponsor": sponsor},
    )


@mcp.tool()
async def suggest_trial_design(
    indication: str,
    mechanism: str,
) -> dict[str, Any]:
    """Heuristic draft design recommendation.

Use this only when the user explicitly wants a server-generated recommendation. Prefer raw discovery and evidence tools if the LLM should synthesize the answer itself.
    """
    whitespace = await analyze_competition_gaps(indication=indication, include_terminated=True)
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
    details, detail_warnings, detail_sources, detail_trace = await _fetch_details(
        [trial.nct_id for trial in candidate_trials.items[:DETAIL_SAMPLE_SIZE]]
    )

    warnings = _warning_dicts(candidate_trials.warnings, publication_response.warnings, detail_warnings)
    queried_sources = sorted(set(candidate_trials.queried_sources + publication_response.queried_sources + detail_sources))

    max_phase_rank = max((phase_rank(trial.phase) for trial in candidate_trials.items), default=-1)
    active_mechanism_trials = [
        trial for trial in candidate_trials.items if trial.overall_status in ACTIVE_STATUSES
    ]
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

    whitespace_signals = ((whitespace.get("result") or {}).get("gap_signals") or [])[:2]
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
        "recommendation_type": "heuristic_draft",
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
        evidence_sources=queried_sources,
        evidence_trace=[
            _trace_step(
                "analyze_competition_gaps",
                sources=((whitespace.get("_meta") or {}).get("evidence_sources", [])),
                note="Loaded a heuristic gap scan to identify sparse or failure-prone mechanism spaces.",
                filters={"indication": indication, "include_terminated": True},
                output_kind="heuristic",
            ),
            _trace_step(
                "search_candidate_trials",
                sources=candidate_trials.queried_sources,
                note="Fetched trials matching the requested indication and mechanism.",
                filters={"indication": indication, "mechanism": mechanism, "max_results": ANALYSIS_MAX_RESULTS},
                output_kind="raw",
            ),
            _trace_step(
                "search_supporting_publications",
                sources=publication_response.queried_sources,
                note="Fetched peer-reviewed evidence relevant to the mechanism and indication.",
                filters={"query": f"{mechanism} {indication}", "year_from": 2018, "max_results": 8},
                output_kind="raw",
            ),
            *detail_trace,
            _trace_step(
                "generate_design_recommendation",
                sources=queried_sources,
                note="Combined trial patterns, publication hints, and gap heuristics into a draft recommendation.",
                filters={"indication": indication, "mechanism": mechanism},
                output_kind="heuristic",
            ),
        ],
        requested_filters={"indication": indication, "mechanism": mechanism},
    )


@mcp.tool()
async def suggest_patient_profile(
    indication: str,
    mechanism: str,
    biomarker: str | None = None,
) -> dict[str, Any]:
    """Heuristic patient-profile recommendation.

Use this only when the user explicitly wants a server-generated profile draft rather than raw evidence.
    """
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
    details, detail_warnings, detail_sources, detail_trace = await _fetch_details(
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
        "recommendation_type": "heuristic_draft",
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
        evidence_sources=queried_sources,
        evidence_trace=[
            _trace_step(
                "search_completed_trials",
                sources=completed_trials.queried_sources,
                note="Fetched completed trials for the requested indication and mechanism.",
                filters={"indication": indication, "mechanism": mechanism, "status": "COMPLETED"},
                output_kind="raw",
            ),
            _trace_step(
                "search_supporting_publications",
                sources=publications.queried_sources,
                note="Fetched publications used to derive biomarker and profile hints.",
                filters={
                    "query": " ".join(part for part in [mechanism, indication, biomarker] if part),
                    "year_from": 2018,
                    "max_results": 8,
                },
                output_kind="raw",
            ),
            *detail_trace,
            _trace_step(
                "generate_patient_profile",
                sources=queried_sources,
                note="Applied heuristic inclusion, exclusion, and biomarker rules to produce a draft patient profile.",
                filters={"indication": indication, "mechanism": mechanism, "biomarker": biomarker},
                output_kind="heuristic",
            ),
        ],
        requested_filters={"indication": indication, "mechanism": mechanism, "biomarker": biomarker},
    )


@mcp.tool()
async def benchmark_trial_design(
    indication: str,
    phase: str | None = None,
    mechanism: str | None = None,
    sponsor: str | None = None,
) -> dict[str, Any]:
    """Derived benchmark of common design patterns across similar trials."""
    _, details, warnings, queried_sources, evidence_trace = await _collect_trials_and_details(
        indication=indication,
        phase=phase,
        sponsor=sponsor,
        mechanism=mechanism,
    )

    primary_counter: Counter[str] = Counter()
    secondary_counter: Counter[str] = Counter()
    archetype_counter: Counter[str] = Counter()
    study_type_counter: Counter[str] = Counter()
    biomarker_counter: Counter[str] = Counter()
    combination_counter: Counter[str] = Counter()
    comparator_counter: Counter[str] = Counter()
    enrollments: list[int | None] = []

    for detail in details:
        archetype_counter[_design_archetype(detail)] += 1
        if detail.study_type:
            study_type_counter[detail.study_type] += 1
        enrollments.append(detail.enrollment_count)

        for endpoint in detail.primary_outcomes:
            primary_counter[classify_endpoint(endpoint)] += 1
        for endpoint in detail.secondary_outcomes:
            secondary_counter[classify_endpoint(endpoint)] += 1
        for biomarker in _trial_biomarkers(detail):
            biomarker_counter[biomarker] += 1
        for comparator in extract_comparator_signals(
            detail.official_title,
            detail.brief_title,
            " ".join(detail.arms),
            " ".join(detail.interventions),
        ):
            comparator_counter[comparator] += 1

        if len(detail.interventions) >= 2:
            combination_counter["combination therapy"] += 1
        elif len(detail.interventions) == 1:
            combination_counter["monotherapy"] += 1
        else:
            combination_counter["therapy model unspecified"] += 1

    enrollment_values = [value for value in enrollments if isinstance(value, int) and value > 0]
    result = {
        "indication": indication,
        "phase_filter": phase,
        "mechanism_filter": mechanism,
        "sponsor_filter": sponsor,
        "sample_size": len(details),
        "enrollment_benchmark": {
            "median": median_enrollment(enrollments, fallback=0) if details else None,
            "min": min(enrollment_values) if enrollment_values else None,
            "max": max(enrollment_values) if enrollment_values else None,
        },
        "study_types": _top_counter_rows(study_type_counter, limit=5),
        "design_archetypes": _top_counter_rows(archetype_counter, limit=5),
        "therapy_models": _top_counter_rows(combination_counter, limit=5),
        "primary_endpoint_categories": _top_counter_rows(primary_counter, limit=6),
        "secondary_endpoint_categories": _top_counter_rows(secondary_counter, limit=6),
        "biomarker_segments": _top_counter_rows(biomarker_counter, limit=6),
        "comparator_signals": _top_counter_rows(comparator_counter, limit=6),
        "reference_trials": [detail.nct_id for detail in details[:8]],
    }

    return detail_response(
        tool_name="benchmark_trial_design",
        data_type="trial_design_benchmark",
        item=result,
        quality_note="Design benchmark aggregates normalized trial detail fields and lightweight heuristics across a comparable trial sample.",
        coverage="ClinicalTrials.gov detail records for the requested indication and optional filters.",
        queried_sources=queried_sources,
        warnings=warnings,
        evidence_sources=queried_sources,
        evidence_trace=[
            *evidence_trace,
            _trace_step(
                "benchmark_design_patterns",
                sources=queried_sources,
                note="Aggregated study types, archetypes, enrollment, endpoints, biomarkers, and comparator signals across the detail sample.",
                filters={"indication": indication, "phase": phase, "mechanism": mechanism, "sponsor": sponsor},
                output_kind="derived",
            ),
        ],
        requested_filters={"indication": indication, "phase": phase, "mechanism": mechanism, "sponsor": sponsor},
    )


@mcp.tool()
async def benchmark_eligibility_criteria(
    indication: str,
    phase: str | None = None,
    mechanism: str | None = None,
) -> dict[str, Any]:
    """Derived benchmark of recurring eligibility and biomarker criteria."""
    _, details, warnings, queried_sources, evidence_trace = await _collect_trials_and_details(
        indication=indication,
        phase=phase,
        mechanism=mechanism,
    )

    inclusion_counter: Counter[str] = Counter()
    exclusion_counter: Counter[str] = Counter()
    biomarker_counter: Counter[str] = Counter()
    cns_policy_counter: Counter[str] = Counter()

    for detail in details:
        inclusions, exclusions = extract_eligibility_features(detail.eligibility_criteria)
        for criterion in inclusions:
            inclusion_counter[criterion] += 1
        for criterion in exclusions:
            exclusion_counter[criterion] += 1
        for biomarker in _trial_biomarkers(detail):
            biomarker_counter[biomarker] += 1

        criteria_text = (detail.eligibility_criteria or "").lower()
        if "untreated cns" in criteria_text or "untreated brain" in criteria_text:
            cns_policy_counter["exclude untreated CNS disease"] += 1
        elif "cns" in criteria_text or "brain metast" in criteria_text:
            cns_policy_counter["CNS disease addressed case-by-case"] += 1
        else:
            cns_policy_counter["no explicit CNS rule captured"] += 1

    result = {
        "indication": indication,
        "phase_filter": phase,
        "mechanism_filter": mechanism,
        "sample_size": len(details),
        "common_inclusion_criteria": _top_counter_rows(inclusion_counter, limit=8),
        "common_exclusion_criteria": _top_counter_rows(exclusion_counter, limit=8),
        "biomarker_criteria": _top_counter_rows(biomarker_counter, limit=6),
        "cns_policy_patterns": _top_counter_rows(cns_policy_counter, limit=4),
        "reference_trials": [detail.nct_id for detail in details[:8]],
    }

    return detail_response(
        tool_name="benchmark_eligibility_criteria",
        data_type="eligibility_benchmark",
        item=result,
        quality_note="Eligibility benchmark is extracted heuristically from normalized free-text inclusion and exclusion criteria.",
        coverage="ClinicalTrials.gov trial detail records with published eligibility text.",
        queried_sources=queried_sources,
        warnings=warnings,
        evidence_sources=queried_sources,
        evidence_trace=[
            *evidence_trace,
            _trace_step(
                "extract_eligibility_patterns",
                sources=queried_sources,
                note="Applied rule-based extraction to eligibility text to summarize common inclusion, exclusion, and CNS handling patterns.",
                filters={"indication": indication, "phase": phase, "mechanism": mechanism},
                output_kind="derived",
            ),
        ],
        requested_filters={"indication": indication, "phase": phase, "mechanism": mechanism},
    )


@mcp.tool()
async def benchmark_endpoints(
    indication: str,
    phase: str | None = None,
    mechanism: str | None = None,
) -> dict[str, Any]:
    """Derived benchmark of endpoint categories across similar trials."""
    _, details, warnings, queried_sources, evidence_trace = await _collect_trials_and_details(
        indication=indication,
        phase=phase,
        mechanism=mechanism,
    )

    primary_counter: Counter[str] = Counter()
    secondary_counter: Counter[str] = Counter()
    primary_examples: dict[str, list[str]] = defaultdict(list)
    secondary_examples: dict[str, list[str]] = defaultdict(list)

    for detail in details:
        for endpoint in detail.primary_outcomes:
            category = classify_endpoint(endpoint)
            primary_counter[category] += 1
            if endpoint and len(primary_examples[category]) < 3:
                primary_examples[category].append(endpoint)
        for endpoint in detail.secondary_outcomes:
            category = classify_endpoint(endpoint)
            secondary_counter[category] += 1
            if endpoint and len(secondary_examples[category]) < 3:
                secondary_examples[category].append(endpoint)

    result = {
        "indication": indication,
        "phase_filter": phase,
        "mechanism_filter": mechanism,
        "sample_size": len(details),
        "primary_endpoint_categories": [
            {"category": label, "count": count, "examples": primary_examples.get(label, [])}
            for label, count in primary_counter.most_common(8)
        ],
        "secondary_endpoint_categories": [
            {"category": label, "count": count, "examples": secondary_examples.get(label, [])}
            for label, count in secondary_counter.most_common(8)
        ],
        "reference_trials": [detail.nct_id for detail in details[:8]],
    }

    return detail_response(
        tool_name="benchmark_endpoints",
        data_type="endpoint_benchmark",
        item=result,
        quality_note="Endpoint benchmark groups normalized endpoint text into high-level categories for fast design comparison.",
        coverage="ClinicalTrials.gov trial detail records with published primary and secondary outcomes.",
        queried_sources=queried_sources,
        warnings=warnings,
        evidence_sources=queried_sources,
        evidence_trace=[
            *evidence_trace,
            _trace_step(
                "classify_endpoint_patterns",
                sources=queried_sources,
                note="Grouped endpoint text into high-level categories using deterministic endpoint rules.",
                filters={"indication": indication, "phase": phase, "mechanism": mechanism},
                output_kind="derived",
            ),
        ],
        requested_filters={"indication": indication, "phase": phase, "mechanism": mechanism},
    )


@mcp.tool()
async def link_trial_evidence(
    nct_id: str,
    include_preprints: bool = True,
    include_approvals: bool = True,
) -> dict[str, Any]:
    """Cross-source evidence bundle for one known trial.

Use this when you already have an NCT ID and want a quick bundle of likely related literature and approvals. The links are query-based associations, not exact citation matching.
    """
    detail = await registry.get_trial_details(nct_id)
    if detail.item is None:
        return detail_response(
            tool_name="link_trial_evidence",
            data_type="trial_evidence_links",
            item=None,
            quality_note="Trial evidence linking requires a resolvable ClinicalTrials.gov NCT identifier.",
            coverage="ClinicalTrials.gov, PubMed, medRxiv, and OpenFDA where available.",
            missing_message=f"No trial found with ID {nct_id}",
            queried_sources=detail.queried_sources,
            warnings=_warning_dicts(detail.warnings),
            requested_filters={"nct_id": nct_id, "include_preprints": include_preprints, "include_approvals": include_approvals},
        )

    trial = detail.item
    condition_hint = trial.conditions[0] if trial.conditions else ""
    intervention_hint = trial.interventions[0] if trial.interventions else ""
    publication_query = " ".join(part for part in [nct_id, intervention_hint, condition_hint] if part)
    preprint_query = " ".join(part for part in [intervention_hint, condition_hint] if part)

    publication_response = await registry.search_publications(
        query=publication_query or nct_id,
        max_results=6,
        year_from=2018,
    )
    warnings = _warning_dicts(detail.warnings, publication_response.warnings)
    queried_sources = sorted(set(detail.queried_sources + publication_response.queried_sources))

    preprint_items = []
    if include_preprints:
        preprint_response = await registry.search_preprints(
            query=preprint_query or publication_query or nct_id,
            max_results=4,
            year_from=2022,
        )
        preprint_items = [item.model_dump() for item in preprint_response.items]
        warnings.extend(_warning_dicts(preprint_response.warnings))
        queried_sources = sorted(set(queried_sources + preprint_response.queried_sources))

    approval_items = []
    if include_approvals and condition_hint:
        approval_response = await registry.search_approved_drugs(
            indication=condition_hint,
            intervention=intervention_hint or None,
            max_results=5,
        )
        approval_items = [item.model_dump() for item in approval_response.items]
        warnings.extend(_warning_dicts(approval_response.warnings))
        queried_sources = sorted(set(queried_sources + approval_response.queried_sources))

    result = {
        "link_type": "query_based_association",
        "trial": {
            "nct_id": trial.nct_id,
            "brief_title": trial.brief_title,
            "phase": phase_code(trial.phase),
            "status": trial.overall_status,
            "sponsor": trial.lead_sponsor,
            "conditions": trial.conditions,
            "interventions": trial.interventions,
        },
        "queries_used": {
            "publications": publication_query or nct_id,
            "preprints": preprint_query or publication_query or nct_id,
            "approvals": {"indication": condition_hint, "intervention": intervention_hint or None},
        },
        "linked_publications": [item.model_dump() for item in publication_response.items],
        "linked_preprints": preprint_items,
        "related_approvals": approval_items,
        "evidence_summary": {
            "publication_count": len(publication_response.items),
            "preprint_count": len(preprint_items),
            "approval_count": len(approval_items),
        },
    }

    return detail_response(
        tool_name="link_trial_evidence",
        data_type="trial_evidence_links",
        item=result,
        quality_note="Evidence links are query-based associations intended to speed up evidence gathering, not to prove a definitive one-to-one linkage.",
        coverage="ClinicalTrials.gov detail data plus PubMed, medRxiv, and OpenFDA queries derived from the trial context.",
        queried_sources=queried_sources,
        warnings=warnings,
        evidence_sources=queried_sources,
        evidence_trace=[
            _trace_step(
                "fetch_trial_detail",
                sources=detail.queried_sources,
                note="Loaded the trial context used to generate evidence queries.",
                filters={"nct_id": nct_id},
                output_kind="raw",
            ),
            _trace_step(
                "search_publications",
                sources=publication_response.queried_sources,
                note="Queried peer-reviewed literature using trial-derived terms.",
                filters={"query": publication_query or nct_id, "year_from": 2018, "max_results": 6},
                output_kind="raw",
            ),
            *(
                [
                    _trace_step(
                        "search_preprints",
                        sources=preprint_response.queried_sources,
                        note="Queried preprints using trial-derived terms.",
                        filters={"query": preprint_query or publication_query or nct_id, "year_from": 2022, "max_results": 4},
                        output_kind="raw",
                    )
                ]
                if include_preprints
                else []
            ),
            *(
                [
                    _trace_step(
                        "search_approved_drugs",
                        sources=approval_response.queried_sources,
                        note="Queried approved-drug labels for trial-related indication and intervention context.",
                        filters={"indication": condition_hint, "intervention": intervention_hint or None, "max_results": 5},
                        output_kind="raw",
                    )
                ]
                if include_approvals and condition_hint
                else []
            ),
            _trace_step(
                "assemble_evidence_links",
                sources=queried_sources,
                note="Packaged the query-based evidence associations into a single cross-source bundle.",
                filters={"nct_id": nct_id, "include_preprints": include_preprints, "include_approvals": include_approvals},
                output_kind="derived",
            ),
        ],
        requested_filters={"nct_id": nct_id, "include_preprints": include_preprints, "include_approvals": include_approvals},
    )


@mcp.tool()
async def analyze_patient_segments(
    indication: str,
    phase: str | None = None,
    mechanism: str | None = None,
) -> dict[str, Any]:
    """Derived segment summary for biomarkers, disease stage, and line of therapy."""
    _, details, warnings, queried_sources, evidence_trace = await _collect_trials_and_details(
        indication=indication,
        phase=phase,
        mechanism=mechanism,
    )

    segment_counter: Counter[str] = Counter()
    biomarker_counter: Counter[str] = Counter()
    line_counter: Counter[str] = Counter()
    stage_counter: Counter[str] = Counter()

    for detail in details:
        segments = extract_patient_segments(_merged_trial_text(detail))
        for segment in segments:
            segment_counter[segment] += 1
            if segment in {"first-line", "second-line", "later-line", "maintenance"}:
                line_counter[segment] += 1
            elif segment in {"advanced / metastatic", "locally advanced / unresectable", "adjuvant", "neoadjuvant", "brain metastases"}:
                stage_counter[segment] += 1
            else:
                biomarker_counter[segment] += 1

    crowded_segments = [
        {"segment": label, "trial_count": count}
        for label, count in segment_counter.most_common(6)
    ]
    underserved_segments = [
        {
            "segment": label,
            "trial_count": count,
            "signal_strength": infer_signal_strength(count, 0),
        }
        for label, count in sorted(segment_counter.items(), key=lambda item: (item[1], item[0]))
        if count <= 3
    ][:6]

    result = {
        "indication": indication,
        "phase_filter": phase,
        "mechanism_filter": mechanism,
        "sample_size": len(details),
        "crowded_segments": crowded_segments,
        "underserved_segments": underserved_segments,
        "biomarker_segments": _top_counter_rows(biomarker_counter, limit=8),
        "line_of_therapy_segments": _top_counter_rows(line_counter, limit=6),
        "disease_stage_segments": _top_counter_rows(stage_counter, limit=6),
        "reference_trials": [detail.nct_id for detail in details[:8]],
    }

    return detail_response(
        tool_name="analyze_patient_segments",
        data_type="patient_segment_analysis",
        item=result,
        quality_note="Patient-segment analysis is based on heuristic extraction from trial titles, conditions, and eligibility text.",
        coverage="ClinicalTrials.gov detail records for the requested indication and optional filters.",
        queried_sources=queried_sources,
        warnings=warnings,
        evidence_sources=queried_sources,
        evidence_trace=[
            *evidence_trace,
            _trace_step(
                "extract_patient_segments",
                sources=queried_sources,
                note="Applied rule-based segment extraction across merged title, condition, outcome, and eligibility text.",
                filters={"indication": indication, "phase": phase, "mechanism": mechanism},
                output_kind="derived",
            ),
        ],
        requested_filters={"indication": indication, "phase": phase, "mechanism": mechanism},
    )


@mcp.tool()
async def forecast_readouts(
    indication: str,
    phase: str | None = None,
    sponsor: str | None = None,
    months_ahead: int = 24,
) -> dict[str, Any]:
    """Heuristic readout forecast.

Use this only when estimated future dates are acceptable. Prefer timeline tools for raw registered dates without forecast logic.
    """
    response = await registry.search_trials(
        condition=indication,
        phase=phase,
        sponsor=sponsor,
        max_results=ANALYSIS_MAX_RESULTS,
    )
    forecast_rows, benchmark_medians = _forecast_rows_from_trials(
        response.items,
        months_ahead=months_ahead,
    )

    result = {
        "forecast_type": "known_dates_plus_phase_benchmarks",
        "indication": indication,
        "phase_filter": phase,
        "sponsor_filter": sponsor,
        "months_ahead": months_ahead,
        "phase_duration_benchmarks_months": benchmark_medians,
        "forecast": forecast_rows[:20],
    }

    return detail_response(
        tool_name="forecast_readouts",
        data_type="readout_forecast",
        item=result,
        quality_note="Readout forecast prefers registered completion dates and falls back to observed phase-level duration benchmarks when dates are missing.",
        coverage="ClinicalTrials.gov timeline fields available through normalized trial-search results.",
        queried_sources=response.queried_sources,
        warnings=_warning_dicts(response.warnings),
        evidence_sources=response.queried_sources,
        evidence_trace=[
            _trace_step(
                "search_trial_registry",
                sources=response.queried_sources,
                note="Fetched trial rows with available timing fields for the requested indication.",
                filters={"indication": indication, "phase": phase, "sponsor": sponsor, "max_results": ANALYSIS_MAX_RESULTS},
                output_kind="raw",
            ),
            _trace_step(
                "forecast_readout_dates",
                sources=response.queried_sources,
                note="Used known completion dates when available and otherwise estimated dates from phase-duration benchmarks.",
                filters={"indication": indication, "phase": phase, "sponsor": sponsor, "months_ahead": months_ahead},
                output_kind="heuristic",
            ),
        ],
        requested_filters={"indication": indication, "phase": phase, "sponsor": sponsor, "months_ahead": months_ahead},
    )


@mcp.tool()
async def track_competitor_assets(
    indication: str,
    sponsors: list[str] | None = None,
    mechanism: str | None = None,
) -> dict[str, Any]:
    """Derived sponsor-asset grouping for one indication."""
    response = await registry.search_trials(
        condition=indication,
        intervention=mechanism,
        max_results=ANALYSIS_MAX_RESULTS,
    )
    sponsor_filters = [item.lower() for item in sponsors or [] if item]

    grouped_assets: dict[tuple[str, str], dict[str, Any]] = {}
    for trial in response.items:
        sponsor_name = trial.lead_sponsor or "Unknown"
        if sponsor_filters and not any(filter_value in sponsor_name.lower() for filter_value in sponsor_filters):
            continue

        asset_names = [_normalize_asset_name(intervention_name) for intervention_name in trial.interventions]
        asset_names = [asset for asset in asset_names if asset]
        if not asset_names:
            asset_names = [trial.brief_title]

        for asset_name in asset_names[:3]:
            key = (sponsor_name, asset_name)
            if key not in grouped_assets:
                grouped_assets[key] = {
                    "sponsor": sponsor_name,
                    "asset": asset_name,
                    "trial_count": 0,
                    "phases": set(),
                    "statuses": set(),
                    "mechanisms": set(),
                    "nct_ids": [],
                }
            entry = grouped_assets[key]
            entry["trial_count"] += 1
            if trial.phase:
                entry["phases"].add(phase_code(trial.phase))
            entry["statuses"].add(trial.overall_status)
            entry["mechanisms"].update(_trial_mechanisms(trial))
            entry["nct_ids"].append(trial.nct_id)

    assets = []
    for entry in grouped_assets.values():
        assets.append(
            {
                "sponsor": entry["sponsor"],
                "asset": entry["asset"],
                "trial_count": entry["trial_count"],
                "phases": sorted(entry["phases"], key=phase_rank),
                "furthest_phase": furthest_phase(sorted(entry["phases"], key=phase_rank)),
                "statuses": sorted(entry["statuses"]),
                "mechanisms": sorted(entry["mechanisms"]),
                "nct_ids": unique_nonempty(entry["nct_ids"])[:8],
            }
        )

    assets.sort(key=lambda item: (-item["trial_count"], item["sponsor"], item["asset"]))
    result = {
        "indication": indication,
        "sponsor_filters": sponsors or [],
        "mechanism_filter": mechanism,
        "asset_count": len(assets),
        "assets": assets[:25],
    }

    return detail_response(
        tool_name="track_competitor_assets",
        data_type="competitor_asset_tracking",
        item=result,
        quality_note="Asset tracking groups interventions under sponsors using normalized trial-search results and lightweight mechanism tagging.",
        coverage="ClinicalTrials.gov trial-search records for the requested indication.",
        queried_sources=response.queried_sources,
        warnings=_warning_dicts(response.warnings),
        evidence_sources=response.queried_sources,
        evidence_trace=[
            _trace_step(
                "search_trial_registry",
                sources=response.queried_sources,
                note="Fetched trial rows used to group sponsor assets.",
                filters={"indication": indication, "sponsors": sponsors or [], "mechanism": mechanism, "max_results": ANALYSIS_MAX_RESULTS},
                output_kind="raw",
            ),
            _trace_step(
                "group_competitor_assets",
                sources=response.queried_sources,
                note="Grouped interventions under sponsors and attached heuristic mechanism labels.",
                filters={"indication": indication, "sponsors": sponsors or [], "mechanism": mechanism},
                output_kind="derived",
            ),
        ],
        requested_filters={"indication": indication, "sponsors": sponsors or [], "mechanism": mechanism},
    )


@mcp.tool()
async def summarize_safety_signals(
    indication: str,
    mechanism: str | None = None,
    year_from: int = 2019,
) -> dict[str, Any]:
    """Derived cross-source summary of recurring safety signals."""
    query = " ".join(part for part in [mechanism, indication, "safety adverse events toxicity"] if part)
    publications = await registry.search_publications(
        query=query,
        max_results=8,
        year_from=year_from,
    )
    preprints = await registry.search_preprints(
        query=query,
        max_results=5,
        year_from=year_from,
    )
    approvals = await registry.search_approved_drugs(
        indication=indication,
        intervention=mechanism,
        max_results=6,
    )

    warnings = _warning_dicts(publications.warnings, preprints.warnings, approvals.warnings)
    queried_sources = sorted(set(publications.queried_sources + preprints.queried_sources + approvals.queried_sources))

    safety_counter: Counter[str] = Counter()
    examples: dict[str, list[str]] = defaultdict(list)
    for publication in publications.items:
        for signal in extract_safety_signals(publication.title, publication.abstract):
            safety_counter[signal] += 1
            if len(examples[signal]) < 2:
                examples[signal].append(publication.title)
    for publication in preprints.items:
        for signal in extract_safety_signals(publication.title, publication.abstract):
            safety_counter[signal] += 1
            if len(examples[signal]) < 2:
                examples[signal].append(publication.title)
    for approval in approvals.items:
        for signal in extract_safety_signals(
            approval.warnings,
            approval.adverse_reactions,
            approval.contraindications,
            approval.drug_interactions,
        ):
            safety_counter[signal] += 1
            title = approval.brand_name or approval.generic_name or approval.approval_id
            if title and len(examples[signal]) < 2:
                examples[signal].append(title)

    result = {
        "indication": indication,
        "mechanism_filter": mechanism,
        "year_from": year_from,
        "signals": [
            {"signal": label, "count": count, "examples": examples.get(label, [])}
            for label, count in safety_counter.most_common(10)
        ],
        "evidence_counts": {
            "publications": len(publications.items),
            "preprints": len(preprints.items),
            "approved_drug_labels": len(approvals.items),
        },
    }

    return detail_response(
        tool_name="summarize_safety_signals",
        data_type="safety_signal_summary",
        item=result,
        quality_note="Safety summary is an evidence-triage aid built from recurring terms in abstracts and approved-drug label sections.",
        coverage="PubMed, medRxiv, and OpenFDA results for the requested indication and optional mechanism.",
        queried_sources=queried_sources,
        warnings=warnings,
        evidence_sources=queried_sources,
        evidence_trace=[
            _trace_step(
                "search_publications",
                sources=publications.queried_sources,
                note="Fetched peer-reviewed safety-related literature.",
                filters={"query": query, "year_from": year_from, "max_results": 8},
                output_kind="raw",
            ),
            _trace_step(
                "search_preprints",
                sources=preprints.queried_sources,
                note="Fetched preprints for additional early safety signals.",
                filters={"query": query, "year_from": year_from, "max_results": 5},
                output_kind="raw",
            ),
            _trace_step(
                "search_approved_drug_labels",
                sources=approvals.queried_sources,
                note="Fetched approved-drug labels for marketed safety context.",
                filters={"indication": indication, "mechanism": mechanism, "max_results": 6},
                output_kind="raw",
            ),
            _trace_step(
                "extract_safety_signal_patterns",
                sources=queried_sources,
                note="Applied deterministic safety-term extraction across abstracts and label sections.",
                filters={"indication": indication, "mechanism": mechanism, "year_from": year_from},
                output_kind="derived",
            ),
        ],
        requested_filters={"indication": indication, "mechanism": mechanism, "year_from": year_from},
    )


@mcp.tool()
async def investigator_site_landscape(
    indication: str,
    phase: str | None = None,
    sponsor: str | None = None,
) -> dict[str, Any]:
    """Derived site and investigator landscape for active trials."""
    _, details, warnings, queried_sources, evidence_trace = await _collect_trials_and_details(
        indication=indication,
        phase=phase,
        sponsor=sponsor,
        status="RECRUITING",
    )

    country_counter: Counter[str] = Counter()
    facility_counter: Counter[str] = Counter()
    official_counter: Counter[str] = Counter()
    trial_counts_by_country: Counter[str] = Counter()

    for detail in details:
        for country in unique_nonempty(detail.location_countries):
            country_counter[country] += detail.location_countries.count(country)
            trial_counts_by_country[country] += 1
        for facility in unique_nonempty(detail.facility_names):
            facility_counter[facility] += detail.facility_names.count(facility)
        for official in unique_nonempty(detail.overall_officials):
            official_counter[official] += 1

    result = {
        "indication": indication,
        "phase_filter": phase,
        "sponsor_filter": sponsor,
        "sample_size": len(details),
        "countries": [
            {
                "country": country,
                "site_mentions": site_mentions,
                "trial_count": trial_counts_by_country.get(country, 0),
            }
            for country, site_mentions in country_counter.most_common(10)
        ],
        "facilities": [
            {"facility": facility, "site_mentions": count}
            for facility, count in facility_counter.most_common(10)
        ],
        "visible_study_officials": [
            {"name": official, "trial_count": count}
            for official, count in official_counter.most_common(10)
        ],
        "reference_trials": [detail.nct_id for detail in details[:8]],
    }

    return detail_response(
        tool_name="investigator_site_landscape",
        data_type="investigator_site_landscape",
        item=result,
        quality_note="Site landscape reflects published locations and study-official metadata visible in ClinicalTrials.gov, which may be incomplete for some studies.",
        coverage="ClinicalTrials.gov detail records with location and official metadata.",
        queried_sources=queried_sources,
        warnings=warnings,
        evidence_sources=queried_sources,
        evidence_trace=[
            *evidence_trace,
            _trace_step(
                "aggregate_site_landscape",
                sources=queried_sources,
                note="Aggregated countries, facilities, and visible study officials from recruiting-trial detail records.",
                filters={"indication": indication, "phase": phase, "sponsor": sponsor, "status": "RECRUITING"},
                output_kind="derived",
            ),
        ],
        requested_filters={"indication": indication, "phase": phase, "sponsor": sponsor},
    )


@mcp.tool()
async def watch_indication_signals(
    indication: str,
    mechanism: str | None = None,
    sponsor: str | None = None,
    recent_years: int = 2,
    months_ahead: int = 18,
) -> dict[str, Any]:
    """Derived watchlist snapshot across trials, literature, preprints, and approvals."""
    year_from = max(2018, _intelligence_year_floor(recent_years))
    trials_response = await registry.search_trials(
        condition=indication,
        sponsor=sponsor,
        intervention=mechanism,
        max_results=ANALYSIS_MAX_RESULTS,
    )
    publications = await registry.search_publications(
        query=" ".join(part for part in [mechanism, indication] if part) or indication,
        max_results=6,
        year_from=year_from,
    )
    preprints = await registry.search_preprints(
        query=" ".join(part for part in [mechanism, indication] if part) or indication,
        max_results=6,
        year_from=year_from,
    )
    approvals = await registry.search_approved_drugs(
        indication=indication,
        intervention=mechanism,
        sponsor=sponsor,
        max_results=6,
    )
    forecast_rows, benchmark_medians = _forecast_rows_from_trials(
        trials_response.items,
        months_ahead=months_ahead,
    )

    new_trial_rows = [
        {
            "nct_id": trial.nct_id,
            "sponsor": trial.lead_sponsor,
            "phase": phase_code(trial.phase),
            "status": trial.overall_status,
            "start_date": trial.start_date,
        }
        for trial in trials_response.items
        if trial.start_date and trial.start_date[:4].isdigit() and int(trial.start_date[:4]) >= year_from
    ]
    new_trial_rows.sort(key=lambda item: (item["start_date"] or "", item["nct_id"]), reverse=True)

    result = {
        "indication": indication,
        "mechanism_filter": mechanism,
        "sponsor_filter": sponsor,
        "watch_window_year_from": year_from,
        "months_ahead": months_ahead,
        "trial_activity": {
            "active_trials": sum(1 for trial in trials_response.items if trial.overall_status in ACTIVE_STATUSES),
            "recent_starts": new_trial_rows[:10],
            "upcoming_readouts": forecast_rows[:10],
            "phase_duration_benchmarks_months": benchmark_medians,
        },
        "publication_activity": [item.model_dump() for item in publications.items],
        "preprint_activity": [item.model_dump() for item in preprints.items],
        "approved_landscape": [item.model_dump() for item in approvals.items],
    }

    return detail_response(
        tool_name="watch_indication_signals",
        data_type="indication_watch_signals",
        item=result,
        quality_note="Watchlist snapshot surfaces fresh signals across trials, publications, preprints, and approved products for recurring monitoring workflows.",
        coverage="ClinicalTrials.gov, PubMed, medRxiv, and OpenFDA results filtered to the requested indication and optional sponsor/mechanism.",
        queried_sources=sorted(set(trials_response.queried_sources + publications.queried_sources + preprints.queried_sources + approvals.queried_sources)),
        warnings=_warning_dicts(trials_response.warnings, publications.warnings, preprints.warnings, approvals.warnings),
        evidence_sources=sorted(set(trials_response.queried_sources + publications.queried_sources + preprints.queried_sources + approvals.queried_sources)),
        evidence_trace=[
            _trace_step(
                "search_trial_registry",
                sources=trials_response.queried_sources,
                note="Fetched trial rows to summarize active programs and recent starts.",
                filters={"indication": indication, "mechanism": mechanism, "sponsor": sponsor, "max_results": ANALYSIS_MAX_RESULTS},
                output_kind="raw",
            ),
            _trace_step(
                "search_publications",
                sources=publications.queried_sources,
                note="Fetched recent peer-reviewed literature for the watch window.",
                filters={"query": " ".join(part for part in [mechanism, indication] if part) or indication, "year_from": year_from, "max_results": 6},
                output_kind="raw",
            ),
            _trace_step(
                "search_preprints",
                sources=preprints.queried_sources,
                note="Fetched recent preprints for the watch window.",
                filters={"query": " ".join(part for part in [mechanism, indication] if part) or indication, "year_from": year_from, "max_results": 6},
                output_kind="raw",
            ),
            _trace_step(
                "search_approved_drug_labels",
                sources=approvals.queried_sources,
                note="Fetched approved-product context for the same indication slice.",
                filters={"indication": indication, "mechanism": mechanism, "sponsor": sponsor, "max_results": 6},
                output_kind="raw",
            ),
            _trace_step(
                "forecast_readouts",
                sources=trials_response.queried_sources,
                note="Estimated upcoming readouts from known or phase-benchmark timing signals.",
                filters={"indication": indication, "months_ahead": months_ahead},
                output_kind="heuristic",
            ),
            _trace_step(
                "assemble_watch_snapshot",
                sources=sorted(set(trials_response.queried_sources + publications.queried_sources + preprints.queried_sources + approvals.queried_sources)),
                note="Packaged the trial, publication, preprint, approval, and forecast signals into one watchlist snapshot.",
                filters={"indication": indication, "mechanism": mechanism, "sponsor": sponsor, "recent_years": recent_years, "months_ahead": months_ahead},
                output_kind="derived",
            ),
        ],
        requested_filters={
            "indication": indication,
            "mechanism": mechanism,
            "sponsor": sponsor,
            "recent_years": recent_years,
            "months_ahead": months_ahead,
        },
    )
