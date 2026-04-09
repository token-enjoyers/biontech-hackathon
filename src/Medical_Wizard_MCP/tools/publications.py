from ..server import mcp
from ..sources import registry


@mcp.tool()
async def search_publications(
    query: str,
    max_results: int = 10,
    year_from: int | None = None,
) -> list[dict]:
    """Search PubMed for scientific publications about clinical trials, therapies, or disease areas.

Use this to find published trial results, mechanism-of-action research, review articles, or evidence supporting a trial design decision. Combine with search_trials to link trials to their published outcomes.

Returns for each publication: pmid, title, authors, journal, pub_date, abstract, source.

Args:
    query: PubMed search query (e.g. "mRNA vaccine glioblastoma", "pembrolizumab NSCLC phase 3 overall survival", "CAR-T cell therapy ALL")
    max_results: Number of results (default 10, max 15)
    year_from: Only return publications published on or after this year
    """
    max_results = min(max_results, 15)
    results = await registry.search_publications(
        query=query,
        max_results=max_results,
        year_from=year_from,
    )
    return [r.model_dump() for r in results]
