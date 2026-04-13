from typing import Any

from .._mcp import mcp
from ..sources import registry
from ._evidence_quality import annotate_evidence_quality
from ._inputs import build_literature_query
from ._responses import list_response


@mcp.tool()
async def search_publications(
    query: str | None = None,
    term: str | None = None,
    indication: str | None = None,
    intervention: str | None = None,
    nct_id: str | None = None,
    max_results: int = 10,
    year_from: int | None = None,
) -> dict[str, Any]:
    """Peer-reviewed literature search tool.

Use this when you need PubMed evidence for a mechanism, indication, or known trial.

Avoid this when you specifically need unpublished or preprint-only evidence.

Returns a standardized list envelope with `_meta`, `count`, and `results`.
Each publication result includes: pmid, title, authors, journal, pub_date, abstract, source.

Args:
    query: PubMed search query (e.g. "mRNA vaccine glioblastoma", "pembrolizumab NSCLC phase 3 overall survival", "CAR-T cell therapy ALL")
    term: Alias for query to match product-oriented tool naming
    indication: Optional disease-area hint appended to the PubMed search query
    intervention: Optional therapy or mechanism hint appended to the PubMed search query
    nct_id: Optional trial identifier hint appended to the PubMed search query
    max_results: Number of results (default 10, max 15)
    year_from: Only return publications published on or after this year
    """
    effective_query, requested_filters = build_literature_query(
        query=query,
        term=term,
        indication=indication,
        intervention=intervention,
        nct_id=nct_id,
    )
    if effective_query is None:
        return list_response(
            tool_name="search_publications",
            data_type="publication_search_results",
            items=[],
            quality_note="Publication search requires a query term, intervention, indication, or NCT ID.",
            coverage="Peer-reviewed publications indexed in PubMed.",
            warnings=[
                {
                    "source": "tool_validation",
                    "stage": "validate_query",
                    "error": "Provide at least one of `query`, `term`, `intervention`, `indication`, or `nct_id`.",
                }
            ],
            requested_filters={
                **requested_filters,
                "year_from": year_from,
                "max_results": max_results,
            },
            evidence_sources=["tool_validation"],
            evidence_trace=[
                {
                    "step": "validate_publication_query",
                    "sources": ["tool_validation"],
                    "note": "Rejected the request because no usable literature search terms were provided.",
                    "filters": requested_filters,
                    "output_kind": "raw",
                    "refs": [],
                }
            ],
        )

    max_results = min(max_results, 15)
    response = await registry.search_publications(
        query=effective_query,
        max_results=max_results,
        year_from=year_from,
    )
    payload = annotate_evidence_quality([r.model_dump() for r in response.items])
    return list_response(
        tool_name="search_publications",
        data_type="publication_search_results",
        items=payload,
        quality_note="Publication records are normalized from PubMed E-utilities responses and annotated with a transparent evidence-quality tier based on source type and available metadata.",
        coverage="Peer-reviewed publications indexed in PubMed for the given query and optional year filter.",
        queried_sources=response.queried_sources,
        warnings=[warning.as_dict() for warning in response.warnings],
        evidence_sources=response.queried_sources,
        evidence_trace=[
            {
                "step": "search_pubmed",
                "sources": response.queried_sources,
                "note": "Queried peer-reviewed literature sources for the effective search string and ranked the returned records by evidence-quality heuristics.",
                "filters": {
                    **requested_filters,
                    "year_from": year_from,
                    "max_results": max_results,
                },
                "output_kind": "raw",
                "refs": payload,
            }
        ],
        requested_filters={
            **requested_filters,
            "year_from": year_from,
            "max_results": max_results,
        },
    )


@mcp.tool()
async def search_preprints(
    query: str | None = None,
    term: str | None = None,
    indication: str | None = None,
    intervention: str | None = None,
    nct_id: str | None = None,
    max_results: int = 10,
    year_from: int | None = None,
) -> dict[str, Any]:
    """Early-signal preprint search tool.

Use this when you want medRxiv evidence or emerging signals before peer review.

Avoid this when the user explicitly needs peer-reviewed evidence first.

Returns a standardized list envelope with `_meta`, `count`, and `results`.
Each preprint result includes: title, authors, journal, pub_date, abstract, doi, mesh_terms, source.

Args:
    query: Search query for medRxiv preprints
    term: Alias for query to match product-oriented tool naming
    indication: Optional disease-area hint appended to the query
    intervention: Optional therapy or mechanism hint appended to the query
    nct_id: Optional trial identifier hint appended to the query
    max_results: Number of results (default 10, max 15)
    year_from: Only return preprints from this year onward; otherwise the source searches a recent rolling window
    """
    effective_query, requested_filters = build_literature_query(
        query=query,
        term=term,
        indication=indication,
        intervention=intervention,
        nct_id=nct_id,
    )
    if effective_query is None:
        return list_response(
            tool_name="search_preprints",
            data_type="preprint_search_results",
            items=[],
            quality_note="Preprint search requires a query term, intervention, indication, or NCT ID.",
            coverage="Recent medRxiv preprints.",
            warnings=[
                {
                    "source": "tool_validation",
                    "stage": "validate_query",
                    "error": "Provide at least one of `query`, `term`, `intervention`, `indication`, or `nct_id`.",
                }
            ],
            requested_filters={
                **requested_filters,
                "year_from": year_from,
                "max_results": max_results,
            },
            evidence_sources=["tool_validation"],
            evidence_trace=[
                {
                    "step": "validate_preprint_query",
                    "sources": ["tool_validation"],
                    "note": "Rejected the request because no usable literature search terms were provided.",
                    "filters": requested_filters,
                    "output_kind": "raw",
                    "refs": [],
                }
            ],
        )

    max_results = min(max_results, 15)
    response = await registry.search_preprints(
        query=effective_query,
        max_results=max_results,
        year_from=year_from,
    )
    payload = annotate_evidence_quality([r.model_dump() for r in response.items])
    return list_response(
        tool_name="search_preprints",
        data_type="preprint_search_results",
        items=payload,
        quality_note="Preprint records are normalized from medRxiv API responses, exclude entries that already list a published journal DOI, and are annotated with transparent evidence-quality tiers.",
        coverage="Recent medRxiv preprints filtered locally against the requested query and optional year range.",
        queried_sources=response.queried_sources,
        warnings=[warning.as_dict() for warning in response.warnings],
        evidence_sources=response.queried_sources,
        evidence_trace=[
            {
                "step": "search_medrxiv",
                "sources": response.queried_sources,
                "note": "Queried preprint sources for the effective search string and ranked the returned records by evidence-quality heuristics.",
                "filters": {
                    **requested_filters,
                    "year_from": year_from,
                    "max_results": max_results,
                },
                "output_kind": "raw",
                "refs": payload,
            }
        ],
        requested_filters={
            **requested_filters,
            "year_from": year_from,
            "max_results": max_results,
        },
    )
