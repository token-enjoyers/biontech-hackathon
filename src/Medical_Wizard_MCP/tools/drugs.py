from typing import Any

from ..app import mcp
from ..sources import registry
from ._evidence_quality import annotate_evidence_quality
from ._responses import list_response


@mcp.tool()
async def search_approved_drugs(
    indication: str,
    sponsor: str | None = None,
    intervention: str | None = None,
    max_results: int = 10,
) -> dict[str, Any]:
    """Approved-product evidence tool.

Use this when you need standard-of-care, sponsor, pharmacology, or safety context from marketed products.

Avoid this when you are searching investigational trials rather than approved therapies.

Returns a standardized list envelope with `_meta`, `count`, and `results`.
Each approved-drug result includes: approval_id, brand_name, generic_name, indication, sponsor,
route, product_type, substance_names, mechanism_of_action, safety, and pharmacology fields.

Args:
    indication: Disease area or indication (e.g. "NSCLC", "lung cancer", "glioblastoma")
    sponsor: Optional manufacturer filter (e.g. "Merck", "Genentech")
    intervention: Optional active substance filter (e.g. "pembrolizumab")
    max_results: Number of results (default 10, max 20)
    """
    max_results = min(max_results, 20)
    response = await registry.search_approved_drugs(
        indication=indication,
        sponsor=sponsor,
        intervention=intervention,
        max_results=max_results,
    )
    payload = annotate_evidence_quality([r.model_dump() for r in response.items])
    return list_response(
        tool_name="search_approved_drugs",
        data_type="approved_drug_search_results",
        items=payload,
        quality_note="Approved-therapy records are normalized from OpenFDA drug label data and annotated with transparent evidence-quality tiers.",
        coverage="Approved products represented in OpenFDA drug labels for the requested indication and optional filters.",
        queried_sources=response.queried_sources,
        warnings=[warning.as_dict() for warning in response.warnings],
        evidence_sources=response.queried_sources,
        evidence_trace=[
            {
                "step": "search_openfda_labels",
                "sources": response.queried_sources,
                "note": "Retrieved approved-drug label records matching the requested indication and optional sponsor/intervention filters, then ranked them with evidence-quality heuristics.",
                "filters": {
                    "indication": indication,
                    "sponsor": sponsor,
                    "intervention": intervention,
                    "max_results": max_results,
                },
                "output_kind": "raw",
                "refs": payload,
            }
        ],
        requested_filters={
            "indication": indication,
            "sponsor": sponsor,
            "intervention": intervention,
            "max_results": max_results,
        },
    )
