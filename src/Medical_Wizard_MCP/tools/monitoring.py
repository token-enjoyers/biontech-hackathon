from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ..app import mcp
from ..sources import registry
from ._evidence_quality import annotate_evidence_quality, summarize_evidence_quality
from ._responses import detail_response

MONITORING_MAX_RESULTS = 25


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
    filters: dict[str, Any] | None,
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


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    candidate = value.strip()
    if not candidate:
        return None
    for pattern in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            parsed = datetime.strptime(candidate, pattern)
            return parsed.replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _since_date(since: str | None, recent_years: int) -> datetime:
    if since:
        parsed = _parse_date(since)
        if parsed is not None:
            return parsed
    current = datetime.now(UTC)
    return current.replace(year=current.year - max(recent_years, 1))


def _filter_by_date(items: list[dict[str, Any]], *field_names: str, since_dt: datetime) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for item in items:
        for field_name in field_names:
            parsed = _parse_date(item.get(field_name))
            if parsed is not None and parsed >= since_dt:
                filtered.append(item)
                break
    return filtered


@mcp.tool()
async def track_indication_changes(
    indication: str,
    intervention: str | None = None,
    sponsor: str | None = None,
    since: str | None = None,
    recent_years: int = 2,
    include_preprints: bool = True,
    max_results: int = 10,
) -> dict[str, Any]:
    """Date-based change tracking across trials and literature.

Use this when the user asks what changed, what is new, or what has appeared since a given date.
    """
    max_results = min(max_results, MONITORING_MAX_RESULTS)
    since_dt = _since_date(since, recent_years)
    since_label = since_dt.date().isoformat()

    trial_response = await registry.search_trials(
        condition=indication,
        sponsor=sponsor,
        intervention=intervention,
        max_results=MONITORING_MAX_RESULTS,
    )
    publication_query = " ".join(part for part in [intervention, indication] if part).strip() or indication
    publication_response = await registry.search_publications(
        query=publication_query,
        max_results=MONITORING_MAX_RESULTS,
        year_from=since_dt.year,
    )

    warnings = _warning_dicts(trial_response.warnings, publication_response.warnings)
    queried_sources = sorted(set(trial_response.queried_sources + publication_response.queried_sources))

    trial_payload = annotate_evidence_quality([item.model_dump() for item in trial_response.items])
    publication_payload = annotate_evidence_quality([item.model_dump() for item in publication_response.items])
    preprint_payload: list[dict[str, Any]] = []

    if include_preprints:
        preprint_response = await registry.search_preprints(
            query=publication_query,
            max_results=MONITORING_MAX_RESULTS,
            year_from=since_dt.year,
        )
        preprint_payload = annotate_evidence_quality([item.model_dump() for item in preprint_response.items])
        warnings.extend(_warning_dicts(preprint_response.warnings))
        queried_sources = sorted(set(queried_sources + preprint_response.queried_sources))

    new_trials_started = _filter_by_date(trial_payload, "start_date", since_dt=since_dt)
    new_trial_readouts = _filter_by_date(trial_payload, "primary_completion_date", "completion_date", since_dt=since_dt)
    new_publications = _filter_by_date(publication_payload, "pub_date", since_dt=since_dt)
    new_preprints = _filter_by_date(preprint_payload, "pub_date", since_dt=since_dt)

    result = {
        "tracking_mode": "current_snapshot_filtered_by_date",
        "since": since_label,
        "indication": indication,
        "intervention_filter": intervention,
        "sponsor_filter": sponsor,
        "summary": {
            "new_trials_started": len(new_trials_started),
            "new_trial_readouts": len(new_trial_readouts),
            "new_publications": len(new_publications),
            "new_preprints": len(new_preprints),
        },
        "note": "This tool filters the currently retrievable records by date fields. It does not reconstruct historical snapshots or infer true status diffs across past timepoints.",
        "new_trials_started": new_trials_started[:max_results],
        "new_trial_readouts": new_trial_readouts[:max_results],
        "new_publications": new_publications[:max_results],
        "new_preprints": new_preprints[:max_results],
        "evidence_quality_summary": summarize_evidence_quality(
            new_trials_started[:max_results]
            + new_trial_readouts[:max_results]
            + new_publications[:max_results]
            + new_preprints[:max_results]
        ),
    }

    return detail_response(
        tool_name="track_indication_changes",
        data_type="indication_change_tracking",
        item=result,
        quality_note="Change tracking is based on date fields available in the currently retrievable sources. It is useful for 'what is new since X' questions, but it does not reconstruct full historical snapshots.",
        coverage="ClinicalTrials.gov trial rows plus PubMed and optional medRxiv search results filtered by date.",
        queried_sources=queried_sources,
        warnings=warnings,
        evidence_sources=queried_sources,
        evidence_trace=[
            _trace_step(
                "search_trial_registry",
                sources=trial_response.queried_sources,
                note="Fetched the current trial snapshot for the requested indication and optional filters.",
                filters={"indication": indication, "intervention": intervention, "sponsor": sponsor, "max_results": MONITORING_MAX_RESULTS},
                output_kind="raw",
                refs=trial_payload,
            ),
            _trace_step(
                "search_publications",
                sources=publication_response.queried_sources,
                note="Fetched peer-reviewed literature for the requested indication window.",
                filters={"query": publication_query, "year_from": since_dt.year, "max_results": MONITORING_MAX_RESULTS},
                output_kind="raw",
                refs=publication_payload,
            ),
            *(
                [
                    _trace_step(
                        "search_preprints",
                        sources=preprint_response.queried_sources,
                        note="Fetched preprints for the requested indication window.",
                        filters={"query": publication_query, "year_from": since_dt.year, "max_results": MONITORING_MAX_RESULTS},
                        output_kind="raw",
                        refs=preprint_payload,
                    )
                ]
                if include_preprints
                else []
            ),
            _trace_step(
                "filter_recent_changes",
                sources=queried_sources,
                note="Filtered the current source snapshot down to records with date fields on or after the requested threshold.",
                filters={"since": since_label, "recent_years": recent_years, "max_results": max_results},
                output_kind="derived",
                refs=result,
            ),
        ],
        requested_filters={
            "indication": indication,
            "intervention": intervention,
            "sponsor": sponsor,
            "since": since,
            "recent_years": recent_years,
            "include_preprints": include_preprints,
            "max_results": max_results,
        },
    )
