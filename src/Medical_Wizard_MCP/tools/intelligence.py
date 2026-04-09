from __future__ import annotations

import asyncio
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import Any

from ..models import ConferenceAbstract, Publication, TrialDetail, TrialSummary
from ..app import mcp
from ..sources import registry
from ._evidence_refs import document_refs_from_models
from ._evidence_quality import annotate_evidence_quality, summarize_evidence_quality
from ._inputs import build_trial_query_variants
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
MAX_DOSSIER_QUERY_VARIANTS = 6

BURDEN_SITE_HINTS = {
    "nsclc": "Lung",
    "non-small cell lung cancer": "Lung",
    "sclc": "Lung",
    "small cell lung cancer": "Lung",
    "lung cancer": "Lung",
    "gbm": "Central Nervous system",
    "glioblastoma": "Central Nervous system",
    "glioblastoma multiforme": "Central Nervous system",
    "brain cancer": "Central Nervous system",
    "breast cancer": "Breast",
    "pancreatic cancer": "Pancreas",
    "pancreas cancer": "Pancreas",
    "colorectal cancer": "Colon, rectum, anus",
}

COUNTRY_ALIASES = {
    "u s": "united states",
    "u s a": "united states",
    "usa": "united states",
    "us": "united states",
    "united states of america": "united states",
    "u k": "united kingdom",
    "uk": "united kingdom",
    "great britain": "united kingdom",
    "republic of korea": "south korea",
    "korea republic of": "south korea",
    "korea south": "south korea",
    "russian federation": "russia",
}


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
    refs: Any = None,
) -> dict[str, Any]:
    trace = {
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
    if refs is not None:
        trace["refs"] = refs
    return trace


def _model_payloads(items: list[Any]) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for item in items:
        if hasattr(item, "model_dump"):
            payload = item.model_dump()
        elif isinstance(item, dict):
            payload = item
        else:
            continue
        if isinstance(payload, dict):
            payloads.append(payload)
    return payloads


def _clean_query_text(value: str | None) -> str:
    return " ".join(value.split()) if isinstance(value, str) and value.strip() else ""


def _clean_lower_text(value: str | None) -> str:
    return _clean_query_text(value).lower()


def _country_join_key(value: str | None) -> str:
    cleaned = _clean_query_text(value)
    if not cleaned:
        return ""

    normalized = re.sub(r"[^a-z0-9]+", " ", cleaned.casefold()).strip()
    normalized = re.sub(r"\bthe\b", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return COUNTRY_ALIASES.get(normalized, normalized)


def _dedupe_publications(items: list[Publication]) -> list[Publication]:
    deduped: dict[str, Publication] = {}
    ordered_keys: list[str] = []

    for item in items:
        key = (
            _clean_query_text(item.pmid)
            or _clean_query_text(item.doi).lower()
            or _clean_query_text(item.title).lower()
        )
        if not key:
            continue
        if key not in deduped:
            ordered_keys.append(key)
            deduped[key] = item

    return [deduped[key] for key in ordered_keys]


def _dedupe_conference_abstracts(items: list[ConferenceAbstract]) -> list[ConferenceAbstract]:
    deduped: dict[str, ConferenceAbstract] = {}
    ordered_keys: list[str] = []

    for item in items:
        key = (
            _clean_query_text(item.source_id)
            or _clean_lower_text(item.doi)
            or _clean_lower_text(item.title)
        )
        if not key:
            continue
        if key not in deduped:
            ordered_keys.append(key)
            deduped[key] = item

    return [deduped[key] for key in ordered_keys]


def _burden_site_hint(indication: str) -> str:
    cleaned = _clean_query_text(indication)
    lowered = cleaned.casefold()
    if lowered in BURDEN_SITE_HINTS:
        return BURDEN_SITE_HINTS[lowered]
    for suffix in (" cancer", " tumour", " tumor"):
        if lowered.endswith(suffix):
            trimmed = cleaned[: -len(suffix)].strip()
            if trimmed:
                return trimmed
    return cleaned


def _build_trial_evidence_queries(trial: TrialDetail) -> tuple[list[str], list[str]]:
    title_queries = unique_nonempty(
        [
            variant
            for title in [trial.brief_title, trial.official_title]
            for variant in build_trial_query_variants(title)
        ]
    )
    condition_hint = trial.conditions[0] if trial.conditions else ""
    intervention_hint = trial.interventions[0] if trial.interventions else ""
    title_and_id = f"{trial.nct_id} {trial.brief_title}".strip() if trial.brief_title else trial.nct_id
    context_query = " ".join(part for part in [trial.nct_id, intervention_hint, condition_hint] if part)
    lighter_context_query = " ".join(part for part in [intervention_hint, condition_hint] if part)

    publication_queries = unique_nonempty(
        [
            *title_queries,
            title_and_id,
            context_query,
            trial.nct_id,
        ]
    )[:4]
    preprint_queries = unique_nonempty(
        [
            *title_queries,
            title_and_id,
            lighter_context_query,
            trial.nct_id,
        ]
    )[:4]
    return publication_queries, preprint_queries


async def _collect_publication_matches(
    queries: list[str],
    *,
    year_from: int,
    max_results_per_query: int,
    search_fn: Any,
) -> tuple[list[Publication], list[str], list[dict[str, str]]]:
    items: list[Publication] = []
    queried_sources: list[str] = []
    warnings: list[dict[str, str]] = []

    for query in queries:
        response = await search_fn(
            query=query,
            max_results=max_results_per_query,
            year_from=year_from,
        )
        items.extend(response.items)
        queried_sources.extend(response.queried_sources)
        warnings.extend(_warning_dicts(response.warnings))

    return _dedupe_publications(items), sorted(set(queried_sources)), warnings


async def _collect_conference_matches(
    queries: list[str],
    *,
    year_from: int | None,
    max_results_per_query: int,
    conference_series: list[str] | None = None,
) -> tuple[list[ConferenceAbstract], list[str], list[dict[str, str]]]:
    items: list[ConferenceAbstract] = []
    queried_sources: list[str] = []
    warnings: list[dict[str, str]] = []

    for query in queries:
        response = await registry.search_conference_abstracts(
            query=query,
            conference_series=conference_series,
            max_results=max_results_per_query,
            year_from=year_from,
        )
        items.extend(response.items)
        queried_sources.extend(response.queried_sources)
        warnings.extend(_warning_dicts(response.warnings))

    return _dedupe_conference_abstracts(items), sorted(set(queried_sources)), warnings


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


def _phase_matches_filter(
    trial_phase: str | None,
    requested_phase: str | None,
    *,
    allow_combination_phases: bool,
) -> bool:
    if not requested_phase:
        return True
    requested_code = phase_code(requested_phase)
    trial_phase_code = phase_code(trial_phase)
    if not requested_code or not trial_phase_code:
        return False
    if trial_phase_code == requested_code:
        return True
    if allow_combination_phases:
        return requested_code in {part.strip() for part in trial_phase_code.split("/") if part.strip()}
    return False


def _trial_status_sort_key(status: str | None) -> tuple[int, int, str]:
    normalized = (status or "").upper()
    if normalized == "RECRUITING":
        return (0, 0, normalized)
    if normalized == "NOT_YET_RECRUITING":
        return (0, 1, normalized)
    if normalized == "ACTIVE_NOT_RECRUITING":
        return (0, 2, normalized)
    if normalized == "COMPLETED":
        return (1, 0, normalized)
    if normalized in TERMINAL_STATUSES:
        return (2, 0, normalized)
    return (3, 0, normalized)


def _label_intersection(candidate_labels: list[str], requested_labels: list[str]) -> list[str]:
    requested_lookup = {label.casefold(): label for label in requested_labels if label}
    matches: list[str] = []
    for label in candidate_labels:
        if label and label.casefold() in requested_lookup and label not in matches:
            matches.append(label)
    return matches


def _trial_screen_row(
    trial: TrialSummary | TrialDetail,
    *,
    candidate_mechanisms: list[str],
    candidate_segments: list[str],
    matched_mechanisms: list[str],
    matched_segments: list[str],
    phase_match: bool,
    interventional_match: bool,
    terminal_status: bool,
    mechanism_filter_requested: bool,
    patient_segment_filter_requested: bool,
    decision: str,
    reasons: list[str],
) -> dict[str, Any]:
    official_title = getattr(trial, "official_title", None)
    study_type = getattr(trial, "study_type", None)
    conditions = getattr(trial, "conditions", [])
    payload = trial.model_dump() if hasattr(trial, "model_dump") else {}
    return {
        "source": trial.source,
        "nct_id": trial.nct_id,
        "brief_title": trial.brief_title,
        "official_title": official_title,
        "phase": trial.phase,
        "phase_code": phase_code(trial.phase),
        "overall_status": trial.overall_status,
        "lead_sponsor": trial.lead_sponsor,
        "study_type": study_type,
        "conditions": conditions,
        "interventions": trial.interventions,
        "mechanism_labels": candidate_mechanisms,
        "patient_segment_labels": candidate_segments,
        "matched_mechanism_labels": matched_mechanisms,
        "matched_patient_segment_labels": matched_segments,
        "screen_flags": {
            "matches_phase_filter": phase_match,
            "matches_interventional_requirement": interventional_match,
            "matches_mechanism_filter": bool(matched_mechanisms) if mechanism_filter_requested else True,
            "matches_patient_segment_filter": bool(matched_segments) if patient_segment_filter_requested else True,
            "is_terminal_status": terminal_status,
        },
        "screen_decision": decision,
        "decision_reasons": reasons,
        "source_refs": document_refs_from_models([payload]) if payload else [],
    }


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
    trace[0]["refs"] = _model_payloads(details)
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
    trace[0]["refs"] = _model_payloads(response.items)
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


def _asset_dossier_queries(
    *,
    asset: str,
    indication: str | None,
    trials: list[TrialSummary],
    details: list[TrialDetail],
) -> tuple[list[str], list[str], list[str]]:
    base_query = " ".join(part for part in [asset, indication] if part).strip()
    publication_queries = unique_nonempty([base_query, asset])
    preprint_queries = unique_nonempty([base_query, asset])
    conference_queries = unique_nonempty([base_query, asset])

    for trial in details[:DETAIL_SAMPLE_SIZE]:
        trial_publication_queries, trial_preprint_queries = _build_trial_evidence_queries(trial)
        publication_queries.extend(trial_publication_queries[:2])
        preprint_queries.extend(trial_preprint_queries[:2])
        conference_queries.extend(
            query
            for query in [
                trial.brief_title,
                trial.official_title,
                " ".join(
                    part
                    for part in [trial.interventions[0] if trial.interventions else "", indication or ""]
                    if part
                ).strip(),
            ]
            if query
        )

    conference_queries.extend(trial.brief_title for trial in trials[:3] if trial.brief_title)

    return (
        unique_nonempty(publication_queries)[:MAX_DOSSIER_QUERY_VARIANTS],
        unique_nonempty(preprint_queries)[:MAX_DOSSIER_QUERY_VARIANTS],
        unique_nonempty(conference_queries)[:MAX_DOSSIER_QUERY_VARIANTS],
    )


def _top_sponsor_rows(trials: list[TrialSummary], *, limit: int = 5) -> list[dict[str, Any]]:
    return [
        {"sponsor": sponsor, "trial_count": count}
        for sponsor, count in Counter(
            trial.lead_sponsor or "Unknown"
            for trial in trials
        ).most_common(limit)
    ]


def _top_mechanism_rows(trials: list[TrialSummary], *, limit: int = 6) -> list[dict[str, Any]]:
    mechanism_counter: Counter[str] = Counter()
    for trial in trials:
        for mechanism in _trial_mechanisms(trial):
            mechanism_counter[mechanism] += 1
    return [
        {"mechanism": mechanism, "trial_count": count}
        for mechanism, count in mechanism_counter.most_common(limit)
    ]


def _country_gap_signal(score: float, visible_trials: int) -> str:
    if score >= 0.6 and visible_trials <= 1:
        return "HIGH"
    if score >= 0.4:
        return "MEDIUM"
    return "LOW"


def _safe_round(value: float | None, digits: int = 1) -> float | None:
    if value is None:
        return None
    return round(value, digits)


def _clamp_score(value: float) -> float:
    return round(min(max(value, 0.05), 0.99), 2)


def _opportunity_tier(score: float) -> str:
    if score >= 0.75:
        return "HIGH"
    if score >= 0.5:
        return "MEDIUM"
    return "LOW"


def _medication_gap_score(approved_drug_count: int) -> float:
    pressure = min(max(approved_drug_count, 0) / 8, 1.0)
    return _clamp_score(1.0 - pressure)


def _competition_whitespace_score(*, active_trial_count: int, unique_sponsors: int, total_trial_count: int) -> float:
    pressure = (
        min(max(active_trial_count, 0) / 20, 1.0) * 0.55
        + min(max(unique_sponsors, 0) / 10, 1.0) * 0.30
        + min(max(total_trial_count, 0) / 30, 1.0) * 0.15
    )
    return _clamp_score(1.0 - pressure)


def _burden_scale_score(*, total_cases: float, average_burden_per_100k: float | None, affected_country_count: int) -> float:
    score = (
        0.55 * min(max(total_cases, 0.0) / 50000, 1.0)
        + 0.30 * min(max(average_burden_per_100k or 0.0, 0.0) / 60, 1.0)
        + 0.15 * min(max(affected_country_count, 0) / 10, 1.0)
    )
    return _clamp_score(score)


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
                refs=_model_payloads(active_response.items),
            ),
            *(
                [
                    _trace_step(
                        "search_terminated_trials",
                        sources=terminated_response.queried_sources,
                        note="Collected terminated trials to add stop-signal context.",
                        filters={"indication": indication, "status": "TERMINATED"},
                        output_kind="raw",
                        refs=_model_payloads(terminated_response.items),
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
                refs=terminated_rows[:10],
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
                refs=comparison_rows,
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
                refs=_model_payloads(response.items),
            ),
            _trace_step(
                "aggregate_trial_density",
                sources=response.queried_sources,
                note="Grouped the retrieved trial rows by phase, sponsor, or heuristic intervention type.",
                filters={"indication": indication, "group_by": group_by, "status": status},
                output_kind="derived",
                refs=_model_payloads(response.items),
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
                refs=_model_payloads(response.items),
            ),
            _trace_step(
                "aggregate_competitive_landscape",
                sources=response.queried_sources,
                note="Grouped trials by sponsor and heuristic mechanism labels, then computed a simple saturation score.",
                filters={"indication": indication, "phase": phase, "status": status},
                output_kind="derived",
                refs=sponsors,
            ),
        ],
        requested_filters={"indication": indication, "phase": phase, "status": status},
    )


@mcp.tool()
async def screen_trial_candidates(
    indication: str,
    phase: str | None = None,
    mechanism: str | None = None,
    sponsor: str | None = None,
    patient_segment: str | None = None,
    include_terminated: bool = False,
    allow_combination_phases: bool = False,
    max_results: int = 30,
) -> dict[str, Any]:
    """Deterministic trial screen for narrow, high-precision answer sets.

Use this when the user asks for an exact cohort such as "all phase 3 bispecific antibody trials in advanced NSCLC" and hallucination risk matters more than broad recall.

Only studies listed under `included_trials` should be treated as safe-to-name final answers. `excluded_trials` are returned for auditability and abstention support.
    """
    max_results = min(max_results, ANALYSIS_MAX_RESULTS)
    candidate_trials, details, warnings, queried_sources, evidence_trace = await _collect_trials_and_details(
        indication=indication,
        phase=phase,
        sponsor=sponsor,
        max_results=max_results,
        detail_limit=max_results,
    )

    detail_by_id = {detail.nct_id: detail for detail in details}
    requested_mechanisms = classify_mechanisms(mechanism) if mechanism else []
    requested_segments = extract_patient_segments(patient_segment) if patient_segment else []
    normalized_mechanism = (mechanism or "").strip().casefold()
    normalized_patient_segment = (patient_segment or "").strip().casefold()

    included_trials: list[dict[str, Any]] = []
    excluded_trials: list[dict[str, Any]] = []
    exclusion_counter: Counter[str] = Counter()

    for trial in candidate_trials:
        detail = detail_by_id.get(trial.nct_id)
        candidate = detail or trial
        merged_text = _merged_trial_text(candidate).casefold()
        candidate_mechanisms = _trial_mechanisms(candidate)
        candidate_segments = extract_patient_segments(_merged_trial_text(candidate))
        terminal_status = candidate.overall_status in TERMINAL_STATUSES
        interventional_match = getattr(candidate, "study_type", None) == "INTERVENTIONAL" if detail is not None else False
        phase_match = _phase_matches_filter(
            candidate.phase,
            phase,
            allow_combination_phases=allow_combination_phases,
        )

        matched_mechanisms = []
        if mechanism:
            matched_mechanisms = _label_intersection(candidate_mechanisms, requested_mechanisms)
            if not matched_mechanisms and normalized_mechanism and normalized_mechanism in merged_text:
                matched_mechanisms = [mechanism.strip()]

        matched_segments = []
        if patient_segment:
            matched_segments = _label_intersection(candidate_segments, requested_segments)
            if not matched_segments and normalized_patient_segment and normalized_patient_segment in merged_text:
                matched_segments = [patient_segment.strip()]

        exclusion_reasons: list[str] = []
        if detail is None:
            exclusion_reasons.append("Excluded because no detailed ClinicalTrials.gov record could be retrieved for deterministic screening.")
        if phase and not phase_match:
            exclusion_reasons.append("Excluded because the verified trial phase does not match the requested phase filter.")
        if detail is not None and not interventional_match:
            exclusion_reasons.append("Excluded because the verified study type is not interventional.")
        if mechanism and not matched_mechanisms:
            exclusion_reasons.append("Excluded because the verified trial text does not support the requested mechanism filter.")
        if patient_segment and not matched_segments:
            exclusion_reasons.append("Excluded because the verified trial text does not support the requested patient-segment filter.")
        if not include_terminated and terminal_status:
            exclusion_reasons.append("Excluded because the trial has a terminal status and terminal studies were not requested.")

        if exclusion_reasons:
            row = _trial_screen_row(
                candidate,
                candidate_mechanisms=candidate_mechanisms,
                candidate_segments=candidate_segments,
                matched_mechanisms=matched_mechanisms,
                matched_segments=matched_segments,
                phase_match=phase_match,
                interventional_match=interventional_match,
                terminal_status=terminal_status,
                mechanism_filter_requested=bool(mechanism),
                patient_segment_filter_requested=bool(patient_segment),
                decision="excluded",
                reasons=exclusion_reasons,
            )
            excluded_trials.append(row)
            for reason in exclusion_reasons:
                exclusion_counter[reason] += 1
            continue

        inclusion_reasons = [
            "Included because the trial has a verifiable detailed ClinicalTrials.gov record.",
            "Included because the verified study type is interventional.",
        ]
        if phase:
            inclusion_reasons.append("Included because the verified trial phase matches the requested phase filter.")
        if mechanism:
            inclusion_reasons.append("Included because the verified trial text matches the requested mechanism filter.")
        if patient_segment:
            inclusion_reasons.append("Included because the verified trial text matches the requested patient-segment filter.")
        if not terminal_status:
            inclusion_reasons.append("Included because the trial status is non-terminal under the current screening settings.")
        elif include_terminated:
            inclusion_reasons.append("Included even though the trial status is terminal because terminal studies were explicitly requested.")

        included_trials.append(
            _trial_screen_row(
                candidate,
                candidate_mechanisms=candidate_mechanisms,
                candidate_segments=candidate_segments,
                matched_mechanisms=matched_mechanisms,
                matched_segments=matched_segments,
                phase_match=phase_match,
                interventional_match=interventional_match,
                terminal_status=terminal_status,
                mechanism_filter_requested=bool(mechanism),
                patient_segment_filter_requested=bool(patient_segment),
                decision="included",
                reasons=inclusion_reasons,
            )
        )

    included_trials.sort(
        key=lambda item: (
            _trial_status_sort_key(item.get("overall_status")),
            -phase_rank(item.get("phase")),
            item.get("nct_id") or "",
        )
    )
    excluded_trials.sort(
        key=lambda item: (
            _trial_status_sort_key(item.get("overall_status")),
            -phase_rank(item.get("phase")),
            item.get("nct_id") or "",
        )
    )

    result = {
        "screen_type": "deterministic_trial_candidate_screen",
        "decision_policy": {
            "high_precision_mode": True,
            "safe_answer_field": "included_trials",
            "exclude_terminal_by_default": not include_terminated,
            "requires_detail_verification": True,
            "notes": [
                "Only studies listed under `included_trials` should be named in a final answer unless the user explicitly asks about exclusions.",
                "Excluded trials are returned to support abstention and transparent auditing rather than broad narrative synthesis.",
            ],
        },
        "filters": {
            "indication": indication,
            "phase": phase,
            "mechanism": mechanism,
            "sponsor": sponsor,
            "patient_segment": patient_segment,
            "include_terminated": include_terminated,
            "allow_combination_phases": allow_combination_phases,
            "max_results": max_results,
        },
        "summary": {
            "candidate_count": len(candidate_trials),
            "detailed_candidate_count": len(details),
            "included_count": len(included_trials),
            "excluded_count": len(excluded_trials),
        },
        "included_trials": included_trials,
        "excluded_trials": excluded_trials,
        "excluded_reason_counts": [
            {"reason": reason, "count": count}
            for reason, count in exclusion_counter.most_common()
        ],
    }

    if not included_trials:
        result["abstention_note"] = (
            "No trials satisfied all deterministic screening criteria. Prefer stating that no verifiable matches were found rather than broadening the answer implicitly."
        )

    return detail_response(
        tool_name="screen_trial_candidates",
        data_type="trial_candidate_screen",
        item=result,
        quality_note="This tool is intentionally conservative. It is designed to reduce hallucinations by requiring detailed trial verification and returning explicit inclusion and exclusion reasons before an attached LLM writes prose.",
        coverage="ClinicalTrials.gov trial-search rows plus detailed records for deterministic screening against the requested filters.",
        queried_sources=queried_sources,
        warnings=warnings,
        evidence_sources=queried_sources,
        evidence_trace=[
            *evidence_trace,
            _trace_step(
                "screen_trial_candidates",
                sources=queried_sources,
                note="Applied deterministic inclusion and exclusion rules to the verified trial detail set and separated answer-safe included trials from audit-only exclusions.",
                filters={
                    "indication": indication,
                    "phase": phase,
                    "mechanism": mechanism,
                    "sponsor": sponsor,
                    "patient_segment": patient_segment,
                    "include_terminated": include_terminated,
                    "allow_combination_phases": allow_combination_phases,
                    "max_results": max_results,
                },
                output_kind="derived",
                refs={"included_trials": included_trials, "excluded_trials": excluded_trials},
            ),
        ],
        requested_filters={
            "indication": indication,
            "phase": phase,
            "mechanism": mechanism,
            "sponsor": sponsor,
            "patient_segment": patient_segment,
            "include_terminated": include_terminated,
            "allow_combination_phases": allow_combination_phases,
            "max_results": max_results,
        },
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
                refs=payload,
            ),
            _trace_step(
                "estimate_recruitment_velocity",
                sources=response.queried_sources,
                note="Estimated enrollment-per-month from enrollment targets and observed or elapsed durations.",
                filters={"indication": indication, "phase": phase, "sponsor": sponsor},
                output_kind="derived",
                refs=rows,
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
                refs=((whitespace.get("_meta") or {}).get("evidence_refs", [])),
            ),
            _trace_step(
                "search_candidate_trials",
                sources=candidate_trials.queried_sources,
                note="Fetched trials matching the requested indication and mechanism.",
                filters={"indication": indication, "mechanism": mechanism, "max_results": ANALYSIS_MAX_RESULTS},
                output_kind="raw",
                refs=_model_payloads(candidate_trials.items),
            ),
            _trace_step(
                "search_supporting_publications",
                sources=publication_response.queried_sources,
                note="Fetched peer-reviewed evidence relevant to the mechanism and indication.",
                filters={"query": f"{mechanism} {indication}", "year_from": 2018, "max_results": 8},
                output_kind="raw",
                refs=_model_payloads(publication_response.items),
            ),
            *detail_trace,
            _trace_step(
                "generate_design_recommendation",
                sources=queried_sources,
                note="Combined trial patterns, publication hints, and gap heuristics into a draft recommendation.",
                filters={"indication": indication, "mechanism": mechanism},
                output_kind="heuristic",
                refs=[result],
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
                refs=_model_payloads(completed_trials.items),
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
                refs=_model_payloads(publications.items),
            ),
            *detail_trace,
            _trace_step(
                "generate_patient_profile",
                sources=queried_sources,
                note="Applied heuristic inclusion, exclusion, and biomarker rules to produce a draft patient profile.",
                filters={"indication": indication, "mechanism": mechanism, "biomarker": biomarker},
                output_kind="heuristic",
                refs=[result],
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
                refs=[result],
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
                refs=[result],
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
                refs=[result],
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
    publication_queries, preprint_queries = _build_trial_evidence_queries(trial)

    publication_items, publication_sources, publication_warnings = await _collect_publication_matches(
        publication_queries,
        year_from=2018,
        max_results_per_query=4,
        search_fn=registry.search_publications,
    )
    warnings = _warning_dicts(detail.warnings)
    warnings.extend(publication_warnings)
    queried_sources = sorted(set(detail.queried_sources + publication_sources))

    preprint_items: list[Publication] = []
    if include_preprints:
        preprint_items, preprint_sources, preprint_warnings = await _collect_publication_matches(
            preprint_queries,
            year_from=2022,
            max_results_per_query=3,
            search_fn=registry.search_preprints,
        )
        warnings.extend(preprint_warnings)
        queried_sources = sorted(set(queried_sources + preprint_sources))

    condition_hint = trial.conditions[0] if trial.conditions else ""
    intervention_hint = trial.interventions[0] if trial.interventions else ""
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

    linked_publications = annotate_evidence_quality([item.model_dump() for item in publication_items[:8]])
    linked_preprints = annotate_evidence_quality([item.model_dump() for item in preprint_items[:6]])
    related_approvals = annotate_evidence_quality(approval_items)
    evidence_documents = linked_publications + linked_preprints + related_approvals

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
            "publications": publication_queries[0] if len(publication_queries) == 1 else publication_queries,
            "publication_queries": publication_queries,
            "preprints": preprint_queries[0] if len(preprint_queries) == 1 else preprint_queries,
            "preprint_queries": preprint_queries,
            "approvals": {"indication": condition_hint, "intervention": intervention_hint or None},
        },
        "linked_publications": linked_publications,
        "linked_preprints": linked_preprints,
        "related_approvals": related_approvals,
        "evidence_summary": {
            "publication_count": len(linked_publications),
            "preprint_count": len(linked_preprints),
            "approval_count": len(approval_items),
        },
        "evidence_quality_summary": summarize_evidence_quality(evidence_documents),
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
                refs=[trial.model_dump()],
            ),
            _trace_step(
                "search_publications",
                sources=publication_sources,
                note="Queried peer-reviewed literature using trial identifiers plus title-derived search terms.",
                filters={"queries": publication_queries, "year_from": 2018, "max_results_per_query": 4},
                output_kind="raw",
                refs=linked_publications,
            ),
            *(
                [
                    _trace_step(
                        "search_preprints",
                        sources=preprint_sources,
                        note="Queried preprints using trial identifiers plus title-derived search terms.",
                        filters={"queries": preprint_queries, "year_from": 2022, "max_results_per_query": 3},
                        output_kind="raw",
                        refs=linked_preprints,
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
                        refs=related_approvals,
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
                refs=[result],
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
                refs=[result],
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
                refs=_model_payloads(response.items),
            ),
            _trace_step(
                "forecast_readout_dates",
                sources=response.queried_sources,
                note="Used known completion dates when available and otherwise estimated dates from phase-duration benchmarks.",
                filters={"indication": indication, "phase": phase, "sponsor": sponsor, "months_ahead": months_ahead},
                output_kind="heuristic",
                refs=forecast_rows,
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
                refs=_model_payloads(response.items),
            ),
            _trace_step(
                "group_competitor_assets",
                sources=response.queried_sources,
                note="Grouped interventions under sponsors and attached heuristic mechanism labels.",
                filters={"indication": indication, "sponsors": sponsors or [], "mechanism": mechanism},
                output_kind="derived",
                refs=assets,
            ),
        ],
        requested_filters={"indication": indication, "sponsors": sponsors or [], "mechanism": mechanism},
    )


@mcp.tool()
async def burden_vs_trial_footprint(
    indication: str,
    indicator: str = "Mortality",
    year: int | None = None,
    phase: str | None = None,
    sponsor: str | None = None,
    status: str = "RECRUITING",
    max_results: int = 10,
) -> dict[str, Any]:
    """Cross-source country ranking for burden versus visible clinical-trial footprint.

Use this when you want to identify countries where oncology burden looks high relative to the visible trial-site footprint.

Avoid this when you only need raw burden rows or raw trial/site data without the cross-source comparison.
    """
    max_results = min(max_results, 25)
    burden_site = _burden_site_hint(indication)
    burden_response = await registry.search_oncology_burden(
        site=burden_site,
        indicator=indicator,
        year=year,
        max_results=100,
    )
    _, details, trial_warnings, trial_sources, trial_trace = await _collect_trials_and_details(
        indication=indication,
        phase=phase,
        status=status,
        sponsor=sponsor,
        detail_limit=40,
    )

    warnings = _warning_dicts(burden_response.warnings, trial_warnings)
    queried_sources = sorted(set(burden_response.queried_sources + trial_sources))

    burden_payload = [item.model_dump() for item in burden_response.items]
    burden_by_country: dict[str, dict[str, Any]] = {}
    for row in burden_payload:
        country = _clean_query_text(row.get("country")) or "Unknown"
        country_key = _country_join_key(country) or "unknown"
        entry = burden_by_country.setdefault(
            country_key,
            {
                "country": country,
                "cases": 0.0,
                "population": 0.0,
                "row_count": 0,
                "years": set(),
                "registries": set(),
                "reference_burden_rows": [],
            },
        )
        cases = row.get("cases")
        population = row.get("population")
        entry["cases"] += float(cases) if isinstance(cases, (int, float)) else 0.0
        entry["population"] += float(population) if isinstance(population, (int, float)) else 0.0
        entry["row_count"] += 1
        if isinstance(row.get("year"), int):
            entry["years"].add(row["year"])
        if _clean_query_text(row.get("registry")):
            entry["registries"].add(str(row["registry"]))
        if len(entry["reference_burden_rows"]) < 3:
            entry["reference_burden_rows"].append(row)

    trial_footprint_by_country: dict[str, dict[str, Any]] = {}
    for detail in details:
        trial_payload = detail.model_dump()
        unique_countries = unique_nonempty(detail.location_countries)
        for country in unique_countries:
            country_key = _country_join_key(country)
            if not country_key:
                continue
            entry = trial_footprint_by_country.setdefault(
                country_key,
                {
                    "visible_trials": set(),
                    "site_mentions": 0,
                    "sponsors": set(),
                    "reference_trials": [],
                },
            )
            entry["visible_trials"].add(detail.nct_id)
            entry["site_mentions"] += detail.location_countries.count(country)
            if detail.lead_sponsor:
                entry["sponsors"].add(detail.lead_sponsor)
            if len(entry["reference_trials"]) < 3:
                entry["reference_trials"].append(
                    {
                        "source": trial_payload["source"],
                        "nct_id": trial_payload["nct_id"],
                        "brief_title": trial_payload["brief_title"],
                        "phase": trial_payload.get("phase"),
                        "overall_status": trial_payload.get("overall_status"),
                        "lead_sponsor": trial_payload.get("lead_sponsor"),
                        "location_countries": trial_payload.get("location_countries", []),
                    }
                )

    max_cases = max((entry["cases"] for entry in burden_by_country.values()), default=0.0)
    max_rate = max(
        (
            entry["cases"] / entry["population"] * 100000
            for entry in burden_by_country.values()
            if entry["population"] > 0
        ),
        default=0.0,
    )

    country_rankings: list[dict[str, Any]] = []
    for country_key, burden_entry in burden_by_country.items():
        footprint_entry = trial_footprint_by_country.get(
            country_key,
            {"visible_trials": set(), "site_mentions": 0, "sponsors": set(), "reference_trials": []},
        )
        visible_trials = len(footprint_entry["visible_trials"])
        unique_sponsors = len(footprint_entry["sponsors"])
        burden_per_100k = (
            burden_entry["cases"] / burden_entry["population"] * 100000
            if burden_entry["population"] > 0
            else None
        )
        burden_index = 0.0
        if max_cases > 0:
            burden_index += 0.65 * (burden_entry["cases"] / max_cases)
        if burden_per_100k is not None and max_rate > 0:
            burden_index += 0.35 * (burden_per_100k / max_rate)
        whitespace_bonus = 0.18 if visible_trials == 0 else 0.08 if visible_trials == 1 else 0.0
        footprint_penalty = (
            min(visible_trials, 4) * 0.16
            + min(footprint_entry["site_mentions"], 8) * 0.04
            + min(unique_sponsors, 4) * 0.05
        )
        footprint_gap_score = max(0.05, min(0.99, burden_index + whitespace_bonus - footprint_penalty))
        country_rankings.append(
            {
                "country": burden_entry["country"],
                "burden_cases": _safe_round(burden_entry["cases"]),
                "population": _safe_round(burden_entry["population"]),
                "burden_per_100k": _safe_round(burden_per_100k, 2),
                "burden_records_considered": burden_entry["row_count"],
                "years_covered": sorted(burden_entry["years"], reverse=True),
                "visible_trial_count": visible_trials,
                "visible_site_mentions": footprint_entry["site_mentions"],
                "visible_sponsor_count": unique_sponsors,
                "burden_per_visible_trial": _safe_round(
                    burden_entry["cases"] / visible_trials if visible_trials else None,
                    2,
                ),
                "footprint_gap_score": round(footprint_gap_score, 2),
                "opportunity_signal": _country_gap_signal(footprint_gap_score, visible_trials),
                "reference_burden_rows": burden_entry["reference_burden_rows"],
                "reference_trials": footprint_entry["reference_trials"],
            }
        )

    country_rankings.sort(
        key=lambda item: (
            -float(item["footprint_gap_score"]),
            -(item.get("burden_cases") or 0),
            item["country"],
        )
    )

    result = {
        "analysis_type": "cross_source_burden_vs_trial_footprint",
        "indication": indication,
        "burden_site_used": burden_site,
        "indicator": indicator,
        "year_filter": year,
        "trial_filters": {
            "phase": phase,
            "sponsor": sponsor,
            "status": status,
        },
        "burden_summary": {
            "country_count": len(country_rankings),
            "total_cases": _safe_round(sum(item["burden_cases"] or 0 for item in country_rankings)),
            "total_population": _safe_round(sum(item["population"] or 0 for item in country_rankings)),
        },
        "trial_footprint_summary": {
            "detail_sample_size": len(details),
            "countries_with_visible_sites": len(trial_footprint_by_country),
            "top_trial_countries": [
                {
                    "country": country,
                    "visible_trial_count": len(entry["visible_trials"]),
                    "visible_site_mentions": entry["site_mentions"],
                }
                for country, entry in sorted(
                    trial_footprint_by_country.items(),
                    key=lambda item: (-len(item[1]["visible_trials"]), -item[1]["site_mentions"], item[0]),
                )[:10]
            ],
        },
        "country_rankings": country_rankings[:max_results],
    }

    return detail_response(
        tool_name="burden_vs_trial_footprint",
        data_type="burden_vs_trial_footprint",
        item=result,
        quality_note="This tool ranks countries by combining oncology burden rows with the visible clinical-trial footprint from published site metadata. It is meant for opportunity triage, not for definitive epidemiology or feasibility decisions.",
        coverage="Configured BigQuery oncology burden rows plus ClinicalTrials.gov detail records with visible site countries.",
        queried_sources=queried_sources,
        warnings=warnings,
        evidence_sources=queried_sources,
        evidence_trace=[
            _trace_step(
                "query_oncology_burden",
                sources=burden_response.queried_sources,
                note="Fetched oncology burden rows for the mapped disease site and indicator.",
                filters={"indication": indication, "burden_site": burden_site, "indicator": indicator, "year": year, "max_results": 100},
                output_kind="raw",
                refs=burden_payload,
            ),
            *trial_trace,
            _trace_step(
                "compare_burden_to_trial_footprint",
                sources=queried_sources,
                note="Aggregated burden by country and compared it with the visible trial-country footprint to rank whitespace-like opportunities.",
                filters={"indication": indication, "indicator": indicator, "year": year, "phase": phase, "sponsor": sponsor, "status": status, "max_results": max_results},
                output_kind="derived",
                refs=result["country_rankings"],
            ),
        ],
        requested_filters={
            "indication": indication,
            "burden_site_used": burden_site,
            "indicator": indicator,
            "year": year,
            "phase": phase,
            "sponsor": sponsor,
            "status": status,
            "max_results": max_results,
        },
    )


@mcp.tool()
async def asset_dossier(
    asset: str,
    indication: str | None = None,
    sponsor: str | None = None,
    year_from: int = 2019,
    include_preprints: bool = True,
    include_conference_signals: bool = True,
    include_approvals: bool = True,
) -> dict[str, Any]:
    """Cross-source asset dossier for one therapy or program name.

Use this when you want one sponsor/asset-centric brief that bundles trials, literature, preprints, conference signals, and approved-drug context.

Avoid this when you only need one source family, one known trial, or a broad indication-level watchlist.
    """
    normalized_asset = _clean_query_text(asset)
    if not normalized_asset:
        return detail_response(
            tool_name="asset_dossier",
            data_type="asset_dossier",
            item=None,
            quality_note="Asset dossiers require a concrete therapy, asset, or program name.",
            coverage="ClinicalTrials.gov, PubMed, medRxiv, Europe PMC, and optional OpenFDA context.",
            missing_message="Provide a non-empty `asset` value.",
            warnings=[
                {
                    "source": "tool_validation",
                    "stage": "validate_asset",
                    "error": "Asset dossiers require a concrete asset or program name.",
                }
            ],
            requested_filters={
                "asset": asset,
                "indication": indication,
                "sponsor": sponsor,
            },
            evidence_sources=["tool_validation"],
            evidence_trace=[
                _trace_step(
                    "validate_asset",
                    sources=["tool_validation"],
                    note="Rejected the request because no usable asset name was provided.",
                    filters={"asset": asset},
                    output_kind="raw",
                    refs=[],
                )
            ],
        )

    trial_response = await registry.search_trials(
        condition=indication or "",
        query=normalized_asset,
        sponsor=sponsor,
        intervention=normalized_asset,
        max_results=ANALYSIS_MAX_RESULTS,
    )
    fallback_trial_response = None
    if not trial_response.items:
        fallback_trial_response = await registry.search_trials(
            condition=indication or "",
            query=normalized_asset,
            sponsor=sponsor,
            intervention=None,
            max_results=ANALYSIS_MAX_RESULTS,
        )
        if fallback_trial_response.items:
            trial_response = fallback_trial_response

    details, detail_warnings, detail_sources, detail_trace = await _fetch_details(
        [trial.nct_id for trial in trial_response.items[: DETAIL_SAMPLE_SIZE * 2]]
    )
    publication_queries, preprint_queries, conference_queries = _asset_dossier_queries(
        asset=normalized_asset,
        indication=indication,
        trials=trial_response.items,
        details=details,
    )

    publications, publication_sources, publication_warnings = await _collect_publication_matches(
        publication_queries,
        year_from=year_from,
        max_results_per_query=4,
        search_fn=registry.search_publications,
    )

    preprints: list[Publication] = []
    preprint_sources: list[str] = []
    preprint_warnings: list[dict[str, str]] = []
    if include_preprints:
        preprints, preprint_sources, preprint_warnings = await _collect_publication_matches(
            preprint_queries,
            year_from=max(year_from, 2022),
            max_results_per_query=3,
            search_fn=registry.search_preprints,
        )

    conference_signals: list[ConferenceAbstract] = []
    conference_sources: list[str] = []
    conference_warnings: list[dict[str, str]] = []
    if include_conference_signals:
        conference_signals, conference_sources, conference_warnings = await _collect_conference_matches(
            conference_queries,
            year_from=year_from,
            max_results_per_query=3,
        )

    approval_items: list[dict[str, Any]] = []
    approval_sources: list[str] = []
    approval_warnings: list[dict[str, str]] = []
    if include_approvals and indication:
        approval_response = await registry.search_approved_drugs(
            indication=indication,
            sponsor=sponsor,
            intervention=normalized_asset,
            max_results=6,
        )
        approval_items = [item.model_dump() for item in approval_response.items]
        approval_sources = approval_response.queried_sources
        approval_warnings = _warning_dicts(approval_response.warnings)

    warnings = _warning_dicts(
        trial_response.warnings,
        _warning_dicts(fallback_trial_response.warnings) if fallback_trial_response is not None else [],
        detail_warnings,
        publication_warnings,
        preprint_warnings,
        conference_warnings,
        approval_warnings,
    )
    queried_sources = sorted(
        set(
            trial_response.queried_sources
            + detail_sources
            + publication_sources
            + preprint_sources
            + conference_sources
            + approval_sources
        )
    )

    trial_payload = [item.model_dump() for item in trial_response.items]
    detail_payload = [item.model_dump() for item in details]
    publication_payload = annotate_evidence_quality([item.model_dump() for item in publications], sort_desc=True)
    preprint_payload = annotate_evidence_quality([item.model_dump() for item in preprints], sort_desc=True)
    conference_payload = annotate_evidence_quality([item.model_dump() for item in conference_signals], sort_desc=True)
    approval_payload = annotate_evidence_quality(approval_items, sort_desc=True)
    evidence_documents = annotate_evidence_quality(
        detail_payload + publication_payload + preprint_payload + conference_payload + approval_payload,
        sort_desc=True,
    )

    result = {
        "dossier_type": "cross_source_asset_dossier",
        "asset": normalized_asset,
        "indication_filter": indication,
        "sponsor_filter": sponsor,
        "year_from": year_from,
        "queries_used": {
            "publication_queries": publication_queries,
            "preprint_queries": preprint_queries if include_preprints else [],
            "conference_queries": conference_queries if include_conference_signals else [],
        },
        "trial_program": {
            "trial_count": len(trial_payload),
            "active_trial_count": sum(1 for trial in trial_response.items if trial.overall_status in ACTIVE_STATUSES),
            "completed_trial_count": sum(1 for trial in trial_response.items if trial.overall_status == "COMPLETED"),
            "terminated_trial_count": sum(1 for trial in trial_response.items if trial.overall_status in TERMINAL_STATUSES),
            "phase_distribution": dict(
                sorted(
                    Counter(phase_code(trial.phase) or "UNSPECIFIED" for trial in trial_response.items).items(),
                    key=lambda item: (-item[1], item[0]),
                )
            ),
            "top_sponsors": _top_sponsor_rows(trial_response.items),
            "top_mechanisms": _top_mechanism_rows(trial_response.items),
        },
        "key_trials": detail_payload[:5],
        "publications": publication_payload[:6],
        "preprints": preprint_payload[:5] if include_preprints else [],
        "conference_signals": conference_payload[:5] if include_conference_signals else [],
        "approved_context": approval_payload[:5] if include_approvals else [],
        "evidence_summary": {
            "trial_count": len(trial_payload),
            "trial_detail_count": len(detail_payload),
            "publication_count": len(publication_payload),
            "preprint_count": len(preprint_payload) if include_preprints else 0,
            "conference_signal_count": len(conference_payload) if include_conference_signals else 0,
            "approved_context_count": len(approval_payload) if include_approvals and indication else 0,
        },
        "evidence_quality_summary": summarize_evidence_quality(evidence_documents),
    }

    evidence_trace = [
        _trace_step(
            "search_trial_registry",
            sources=trial_response.queried_sources,
            note="Fetched trial rows matching the requested asset plus optional indication and sponsor filters.",
            filters={"asset": normalized_asset, "indication": indication, "sponsor": sponsor, "max_results": ANALYSIS_MAX_RESULTS},
            output_kind="raw",
            refs=trial_payload,
        ),
        *detail_trace,
        _trace_step(
            "search_publications",
            sources=publication_sources,
            note="Fetched peer-reviewed literature using asset-centric and title-derived queries.",
            filters={"queries": publication_queries, "year_from": year_from, "max_results_per_query": 4},
            output_kind="raw",
            refs=publication_payload,
        ),
    ]
    if fallback_trial_response is not None and fallback_trial_response.items:
        evidence_trace.insert(
            1,
            _trace_step(
                "fallback_trial_search_without_intervention_filter",
                sources=fallback_trial_response.queried_sources,
                note="Retried the trial search without the structured intervention filter after the stricter asset match returned no visible studies.",
                filters={"asset": normalized_asset, "indication": indication, "sponsor": sponsor, "max_results": ANALYSIS_MAX_RESULTS},
                output_kind="raw",
                refs=[item.model_dump() for item in fallback_trial_response.items],
            ),
        )
    if include_preprints:
        evidence_trace.append(
            _trace_step(
                "search_preprints",
                sources=preprint_sources,
                note="Fetched preprints using asset-centric and title-derived queries.",
                filters={"queries": preprint_queries, "year_from": max(year_from, 2022), "max_results_per_query": 3},
                output_kind="raw",
                refs=preprint_payload,
            )
        )
    if include_conference_signals:
        evidence_trace.append(
            _trace_step(
                "search_conference_signals",
                sources=conference_sources,
                note="Fetched conference-stage evidence for the asset using Europe PMC conference matching.",
                filters={"queries": conference_queries, "year_from": year_from, "max_results_per_query": 3},
                output_kind="raw",
                refs=conference_payload,
            )
        )
    if include_approvals and indication:
        evidence_trace.append(
            _trace_step(
                "search_approved_drug_labels",
                sources=approval_sources,
                note="Fetched approved-drug label context for the same indication and asset terms.",
                filters={"indication": indication, "sponsor": sponsor, "intervention": normalized_asset, "max_results": 6},
                output_kind="raw",
                refs=approval_payload,
            )
        )
    evidence_trace.append(
        _trace_step(
            "assemble_asset_dossier",
            sources=queried_sources,
            note="Packaged the trial, literature, conference, and approval context into one asset-centric dossier.",
            filters={
                "asset": normalized_asset,
                "indication": indication,
                "sponsor": sponsor,
                "year_from": year_from,
                "include_preprints": include_preprints,
                "include_conference_signals": include_conference_signals,
                "include_approvals": include_approvals,
            },
            output_kind="derived",
            refs=[result],
        )
    )

    return detail_response(
        tool_name="asset_dossier",
        data_type="asset_dossier",
        item=result,
        quality_note="The asset dossier is a cross-source brief meant to accelerate competitive and program scouting. It bundles evidence around an asset name, so it should be reviewed for false-positive query matches before making high-stakes decisions.",
        coverage="ClinicalTrials.gov, PubMed, optional medRxiv, optional Europe PMC conference records, and optional OpenFDA context.",
        queried_sources=queried_sources,
        warnings=warnings,
        evidence_sources=queried_sources,
        evidence_trace=evidence_trace,
        requested_filters={
            "asset": normalized_asset,
            "indication": indication,
            "sponsor": sponsor,
            "year_from": year_from,
            "include_preprints": include_preprints,
            "include_conference_signals": include_conference_signals,
            "include_approvals": include_approvals,
        },
    )


@mcp.tool()
async def estimate_commercial_opportunity_proxy(
    indication: str,
    indicator: str = "Mortality",
    year: int | None = None,
    max_results: int = 10,
) -> dict[str, Any]:
    """Heuristic strategy proxy for disease burden, treatment gap, and visible competition.

Use this when you want a rough commercial-opportunity proxy built from burden, approved-drug scarcity, visible trial competition, and visible trial-footprint gaps.

Avoid this when you need real pricing, reimbursement, sales, or epidemiology/market-access data.
    """
    max_results = min(max_results, 25)
    burden_vs_trial = await burden_vs_trial_footprint(
        indication=indication,
        indicator=indicator,
        year=year,
        max_results=max_results,
    )
    burden_meta = burden_vs_trial.get("_meta") or {}
    burden_result = burden_vs_trial.get("result") or {}
    country_rankings = list(burden_result.get("country_rankings") or [])

    trial_response = await registry.search_trials(
        condition=indication,
        max_results=ANALYSIS_MAX_RESULTS,
    )
    approval_response = await registry.search_approved_drugs(
        indication=indication,
        max_results=20,
    )

    trial_payload = [item.model_dump() for item in trial_response.items]
    approval_payload = annotate_evidence_quality([item.model_dump() for item in approval_response.items], sort_desc=True)
    approved_drug_count = len(approval_response.items)
    active_trial_count = sum(1 for trial in trial_response.items if trial.overall_status in ACTIVE_STATUSES)
    unique_sponsors = len({trial.lead_sponsor for trial in trial_response.items if trial.lead_sponsor})
    total_trial_count = len(trial_response.items)

    burden_cases = [float(item["burden_cases"]) for item in country_rankings if isinstance(item.get("burden_cases"), (int, float))]
    burden_rates = [float(item["burden_per_100k"]) for item in country_rankings if isinstance(item.get("burden_per_100k"), (int, float))]
    total_cases = sum(burden_cases)
    average_burden_per_100k = round(sum(burden_rates) / len(burden_rates), 2) if burden_rates else None

    burden_score = _burden_scale_score(
        total_cases=total_cases,
        average_burden_per_100k=average_burden_per_100k,
        affected_country_count=len(country_rankings),
    )
    medication_gap_score = _medication_gap_score(approved_drug_count)
    competition_whitespace_score = _competition_whitespace_score(
        active_trial_count=active_trial_count,
        unique_sponsors=unique_sponsors,
        total_trial_count=total_trial_count,
    )
    footprint_gap_score = _clamp_score(
        sum(float(item.get("footprint_gap_score", 0)) for item in country_rankings[:3]) / max(len(country_rankings[:3]), 1)
        if country_rankings
        else 0.05
    )
    commercial_proxy_score = _clamp_score(
        0.40 * burden_score
        + 0.25 * medication_gap_score
        + 0.20 * competition_whitespace_score
        + 0.15 * footprint_gap_score
    )

    max_country_cases = max(burden_cases, default=0.0)
    country_opportunity_rankings: list[dict[str, Any]] = []
    for row in country_rankings:
        country_burden_share = (
            float(row.get("burden_cases", 0)) / max_country_cases
            if max_country_cases > 0 and isinstance(row.get("burden_cases"), (int, float))
            else 0.0
        )
        country_proxy_score = _clamp_score(
            0.55 * float(row.get("footprint_gap_score", 0))
            + 0.25 * medication_gap_score
            + 0.20 * country_burden_share
        )
        country_opportunity_rankings.append(
            {
                "country": row.get("country"),
                "country_opportunity_proxy_score": country_proxy_score,
                "country_opportunity_tier": _opportunity_tier(country_proxy_score),
                "burden_cases": row.get("burden_cases"),
                "burden_per_100k": row.get("burden_per_100k"),
                "visible_trial_count": row.get("visible_trial_count"),
                "visible_site_mentions": row.get("visible_site_mentions"),
                "global_medication_gap_score": medication_gap_score,
                "reference_burden_rows": row.get("reference_burden_rows", []),
                "reference_trials": row.get("reference_trials", []),
            }
        )

    country_opportunity_rankings.sort(
        key=lambda item: (-float(item["country_opportunity_proxy_score"]), item.get("country") or "")
    )

    result = {
        "proxy_type": "commercial_opportunity_proxy",
        "indication": indication,
        "indicator": indicator,
        "year_filter": year,
        "overall_proxy_score": commercial_proxy_score,
        "overall_opportunity_tier": _opportunity_tier(commercial_proxy_score),
        "proxy_components": {
            "burden_scale_score": burden_score,
            "medication_gap_score": medication_gap_score,
            "competition_whitespace_score": competition_whitespace_score,
            "footprint_gap_score": footprint_gap_score,
        },
        "proxy_inputs_summary": {
            "total_cases": _safe_round(total_cases),
            "average_burden_per_100k": average_burden_per_100k,
            "affected_country_count": len(country_rankings),
            "approved_drug_count": approved_drug_count,
            "active_trial_count": active_trial_count,
            "total_trial_count": total_trial_count,
            "unique_visible_trial_sponsors": unique_sponsors,
        },
        "economic_proxy_limits": {
            "includes_pricing_data": False,
            "includes_reimbursement_data": False,
            "includes_sales_data": False,
            "includes_country_specific_access_data": False,
            "note": "This is a strategic proxy only. It does not estimate revenue or market size directly because the current MCP lacks pricing, reimbursement, sales, and access sources.",
        },
        "approved_treatment_context": approval_payload[:8],
        "competition_context": {
            "top_sponsors": _top_sponsor_rows(trial_response.items),
            "top_mechanisms": _top_mechanism_rows(trial_response.items),
            "phase_distribution": dict(
                sorted(
                    Counter(phase_code(trial.phase) or "UNSPECIFIED" for trial in trial_response.items).items(),
                    key=lambda item: (-item[1], item[0]),
                )
            ),
        },
        "country_opportunity_rankings": country_opportunity_rankings[:max_results],
    }

    warnings = _warning_dicts(
        burden_meta.get("partial_failures", []),
        trial_response.warnings,
        approval_response.warnings,
    )
    queried_sources = sorted(
        set(
            list(burden_meta.get("evidence_sources") or [])
            + trial_response.queried_sources
            + approval_response.queried_sources
        )
    )

    return detail_response(
        tool_name="estimate_commercial_opportunity_proxy",
        data_type="commercial_opportunity_proxy",
        item=result,
        quality_note="This tool is a commercial-strategy proxy built from burden, treatment scarcity, visible trial competition, and visible footprint gaps. It is intentionally heuristic and should not be read as a real revenue forecast.",
        coverage="Configured BigQuery oncology burden rows, ClinicalTrials.gov trial records, and OpenFDA approved-drug label context.",
        queried_sources=queried_sources,
        warnings=warnings,
        evidence_sources=queried_sources,
        evidence_trace=[
            _trace_step(
                "load_burden_vs_trial_footprint",
                sources=list(burden_meta.get("evidence_sources") or []),
                note="Loaded the burden-versus-trial-footprint comparison as the geographic opportunity base layer.",
                filters={"indication": indication, "indicator": indicator, "year": year, "max_results": max_results},
                output_kind="derived",
                refs=country_rankings,
            ),
            _trace_step(
                "search_trial_registry",
                sources=trial_response.queried_sources,
                note="Fetched the current trial landscape to estimate visible competition intensity.",
                filters={"indication": indication, "max_results": ANALYSIS_MAX_RESULTS},
                output_kind="raw",
                refs=trial_payload,
            ),
            _trace_step(
                "search_approved_drug_labels",
                sources=approval_response.queried_sources,
                note="Fetched approved-drug label records as a proxy for available treatment options.",
                filters={"indication": indication, "max_results": 20},
                output_kind="raw",
                refs=approval_payload,
            ),
            _trace_step(
                "score_commercial_opportunity_proxy",
                sources=queried_sources,
                note="Combined burden scale, medication scarcity, visible competition intensity, and footprint gaps into a strategy proxy score. No pricing, reimbursement, or sales data were used.",
                filters={"indication": indication, "indicator": indicator, "year": year, "max_results": max_results},
                output_kind="heuristic",
                refs=[result],
            ),
        ],
        requested_filters={
            "indication": indication,
            "indicator": indicator,
            "year": year,
            "max_results": max_results,
        },
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
                refs=_model_payloads(publications.items),
            ),
            _trace_step(
                "search_preprints",
                sources=preprints.queried_sources,
                note="Fetched preprints for additional early safety signals.",
                filters={"query": query, "year_from": year_from, "max_results": 5},
                output_kind="raw",
                refs=_model_payloads(preprints.items),
            ),
            _trace_step(
                "search_approved_drug_labels",
                sources=approvals.queried_sources,
                note="Fetched approved-drug labels for marketed safety context.",
                filters={"indication": indication, "mechanism": mechanism, "max_results": 6},
                output_kind="raw",
                refs=_model_payloads(approvals.items),
            ),
            _trace_step(
                "extract_safety_signal_patterns",
                sources=queried_sources,
                note="Applied deterministic safety-term extraction across abstracts and label sections.",
                filters={"indication": indication, "mechanism": mechanism, "year_from": year_from},
                output_kind="derived",
                refs=[result],
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
                refs=[result],
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
                refs=_model_payloads(trials_response.items),
            ),
            _trace_step(
                "search_publications",
                sources=publications.queried_sources,
                note="Fetched recent peer-reviewed literature for the watch window.",
                filters={"query": " ".join(part for part in [mechanism, indication] if part) or indication, "year_from": year_from, "max_results": 6},
                output_kind="raw",
                refs=_model_payloads(publications.items),
            ),
            _trace_step(
                "search_preprints",
                sources=preprints.queried_sources,
                note="Fetched recent preprints for the watch window.",
                filters={"query": " ".join(part for part in [mechanism, indication] if part) or indication, "year_from": year_from, "max_results": 6},
                output_kind="raw",
                refs=_model_payloads(preprints.items),
            ),
            _trace_step(
                "search_approved_drug_labels",
                sources=approvals.queried_sources,
                note="Fetched approved-product context for the same indication slice.",
                filters={"indication": indication, "mechanism": mechanism, "sponsor": sponsor, "max_results": 6},
                output_kind="raw",
                refs=_model_payloads(approvals.items),
            ),
            _trace_step(
                "forecast_readouts",
                sources=trials_response.queried_sources,
                note="Estimated upcoming readouts from known or phase-benchmark timing signals.",
                filters={"indication": indication, "months_ahead": months_ahead},
                output_kind="heuristic",
                refs=forecast_rows,
            ),
            _trace_step(
                "assemble_watch_snapshot",
                sources=sorted(set(trials_response.queried_sources + publications.queried_sources + preprints.queried_sources + approvals.queried_sources)),
                note="Packaged the trial, publication, preprint, approval, and forecast signals into one watchlist snapshot.",
                filters={"indication": indication, "mechanism": mechanism, "sponsor": sponsor, "recent_years": recent_years, "months_ahead": months_ahead},
                output_kind="derived",
                refs=[result],
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
