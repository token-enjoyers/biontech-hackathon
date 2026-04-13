from __future__ import annotations

import re
from typing import Any

from .._mcp import mcp
from ..sources import registry
from ..sources._conference_utils import normalize_conference_series
from ._evidence_quality import annotate_evidence_quality
from ._inputs import build_literature_query
from ._responses import list_response

_QUERY_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "into",
    "after",
    "before",
    "study",
    "trial",
    "therapy",
    "treatment",
    "meeting",
    "annual",
    "congress",
    "abstract",
}

_LOW_SIGNAL_PATTERNS = (
    re.compile(r"\bhighlights?\b", re.I),
    re.compile(r"\btips\b", re.I),
    re.compile(r"\bperspectives?\b", re.I),
    re.compile(r"\breview\b", re.I),
    re.compile(r"\bnews\b", re.I),
    re.compile(r"\bsummary\b", re.I),
)

MIN_CONFERENCE_RESULT_SCORE = 0.35
STRONG_CONFERENCE_RESULT_SCORE = 0.55


def _clamp_score(value: float) -> float:
    return round(min(max(value, 0.05), 0.99), 2)


def _query_terms(query: str) -> list[str]:
    tokens = re.findall(r"[a-zA-Z0-9\-+]{3,}", query.lower())
    return [token for token in tokens if token not in _QUERY_STOPWORDS]


def _conference_result_fields(
    item: dict[str, Any],
    *,
    effective_query: str,
    requested_series: list[str],
) -> dict[str, Any]:
    title = str(item.get("title") or "")
    abstract = str(item.get("abstract") or "")
    conference_name = str(item.get("conference_name") or "")
    journal = str(item.get("journal") or "")
    presentation_type = str(item.get("presentation_type") or "")
    conference_series = str(item.get("conference_series") or "")
    abstract_number = str(item.get("abstract_number") or "")
    source = str(item.get("source") or "").lower()

    haystack = " ".join(part for part in [title, abstract, conference_name, journal] if part).lower()
    query_terms = _query_terms(effective_query)
    overlap = sum(1 for term in query_terms if term in haystack)
    overlap_ratio = overlap / len(query_terms) if query_terms else 0.0

    score = 0.42
    reasons: list[str] = []

    if requested_series and conference_series in requested_series:
        score += 0.07
        reasons.append("Matches the requested conference series.")
    if presentation_type:
        score += 0.16
        reasons.append("Presentation format metadata is available.")
    if abstract_number:
        score += 0.13
        reasons.append("Abstract numbering suggests a concrete conference artifact.")
    if "abstract" in title.lower():
        score += 0.12
        reasons.append("Title explicitly looks like a conference abstract.")
    if abstract:
        score += 0.08
        reasons.append("Abstract text is available for direct review.")
    if item.get("doi"):
        score += 0.04
        reasons.append("DOI is available for follow-up.")
    if source == "europe_pmc":
        score += 0.05
        reasons.append("Europe PMC record comes from a biomedical index.")
    score += overlap_ratio * 0.22
    if overlap_ratio > 0:
        reasons.append(f"Query overlap is {overlap_ratio:.0%}.")

    if any(pattern.search(title) for pattern in _LOW_SIGNAL_PATTERNS):
        score -= 0.22
        reasons.append("Title looks more like commentary or highlights than a primary conference record.")
    if not presentation_type and not abstract_number and not abstract:
        score -= 0.12
        reasons.append("Key conference-artifact signals are missing.")

    return {
        "conference_result_score": _clamp_score(score),
        "conference_result_reason": " ".join(reasons) or "Conference ranking fell back to a neutral baseline.",
    }


def _conference_match_strength(score: float) -> str:
    if score >= STRONG_CONFERENCE_RESULT_SCORE:
        return "strong"
    if score >= MIN_CONFERENCE_RESULT_SCORE:
        return "related"
    return "weak"


@mcp.tool()
async def search_conference_abstracts(
    query: str | None = None,
    term: str | None = None,
    indication: str | None = None,
    intervention: str | None = None,
    nct_id: str | None = None,
    conference_series: list[str] | None = None,
    max_results: int = 10,
    year_from: int | None = None,
) -> dict[str, Any]:
    """Conference-abstract discovery tool focused on major oncology and immuno-oncology meetings.

Use this when you need early congress signals before full journal publication, especially for ASCO, AACR, ESMO, and SITC.

Avoid this when the user explicitly needs peer-reviewed journal literature first.
    """
    effective_query, requested_filters = build_literature_query(
        query=query,
        term=term,
        indication=indication,
        intervention=intervention,
        nct_id=nct_id,
    )
    resolved_series = normalize_conference_series(conference_series)
    if effective_query is None:
        return list_response(
            tool_name="search_conference_abstracts",
            data_type="conference_abstract_search_results",
            items=[],
            quality_note="Conference abstract search requires a query term, intervention, indication, or NCT ID.",
            coverage="Major oncology and immuno-oncology conference signals from Europe PMC.",
            warnings=[
                {
                    "source": "tool_validation",
                    "stage": "validate_query",
                    "error": "Provide at least one of `query`, `term`, `intervention`, `indication`, or `nct_id`.",
                }
            ],
            requested_filters={
                **requested_filters,
                "conference_series": resolved_series,
                "year_from": year_from,
                "max_results": max_results,
            },
            evidence_sources=["tool_validation"],
            evidence_trace=[
                {
                    "step": "validate_conference_query",
                    "sources": ["tool_validation"],
                    "note": "Rejected the request because no usable conference search terms were provided.",
                    "filters": requested_filters,
                    "output_kind": "raw",
                    "refs": [],
                }
            ],
        )

    max_results = min(max_results, 20)
    registry_max_results = min(max_results * 3, 50)
    response = await registry.search_conference_abstracts(
        query=effective_query,
        conference_series=resolved_series,
        max_results=registry_max_results,
        year_from=year_from,
    )
    payload = annotate_evidence_quality([item.model_dump() for item in response.items], sort_desc=False)
    ranked_payload = []
    for index, item in enumerate(payload):
        enriched = dict(item)
        enriched.update(
            _conference_result_fields(
                enriched,
                effective_query=effective_query,
                requested_series=resolved_series,
            )
        )
        enriched["conference_match_strength"] = _conference_match_strength(
            float(enriched.get("conference_result_score", 0))
        )
        ranked_payload.append((index, enriched))
    ranked_payload.sort(
        key=lambda pair: (
            -float(pair[1].get("conference_result_score", 0)),
            -float(pair[1].get("evidence_quality_score", 0)),
            pair[0],
        )
    )
    payload = [
        item
        for _, item in ranked_payload
        if float(item.get("conference_result_score", 0)) >= MIN_CONFERENCE_RESULT_SCORE
    ][:max_results]
    return list_response(
        tool_name="search_conference_abstracts",
        data_type="conference_abstract_search_results",
        items=payload,
        quality_note="Conference abstracts are early-signal evidence gathered from Europe PMC and ranked with transparent evidence-quality heuristics. They are useful for competitive and translational scouting but should not be treated as equivalent to full peer-reviewed publications.",
        coverage="ASCO, AACR, ESMO, and SITC-oriented conference records retrievable through Europe PMC.",
        queried_sources=response.queried_sources,
        warnings=[warning.as_dict() for warning in response.warnings],
        evidence_sources=response.queried_sources,
        evidence_trace=[
            {
                "step": "search_conference_sources",
                "sources": response.queried_sources,
                "note": "Queried Europe PMC for oncology and immuno-oncology congress records matching the effective search string and requested conference scope.",
                "filters": {
                    **requested_filters,
                    "conference_series": resolved_series,
                    "year_from": year_from,
                    "max_results": registry_max_results,
                },
                "output_kind": "raw",
                "refs": payload,
            },
            {
                "step": "rank_conference_results",
                "sources": response.queried_sources,
                "note": "Ranked conference results using conference-artifact signals, query overlap, source quality hints, and penalties for low-signal commentary-like records, then kept both strong and related matches above the broad-return threshold.",
                "filters": {
                    "effective_query": effective_query,
                    "conference_series": resolved_series,
                    "minimum_score": MIN_CONFERENCE_RESULT_SCORE,
                    "strong_match_score": STRONG_CONFERENCE_RESULT_SCORE,
                    "returned_results": max_results,
                },
                "output_kind": "derived",
                "refs": payload,
            }
        ],
        requested_filters={
            **requested_filters,
            "conference_series": resolved_series,
            "year_from": year_from,
            "max_results": max_results,
            "registry_max_results": registry_max_results,
            "minimum_conference_result_score": MIN_CONFERENCE_RESULT_SCORE,
            "strong_conference_result_score": STRONG_CONFERENCE_RESULT_SCORE,
        },
    )
