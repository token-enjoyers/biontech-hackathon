from __future__ import annotations

import json
import os

import pytest

from Medical_Wizard_MCP.sources.pubmed import PubMedSource


@pytest.mark.asyncio
async def test_pubmed_live_output() -> None:
    if os.getenv("RUN_LIVE_PUBMED") != "1":
        pytest.skip("Set RUN_LIVE_PUBMED=1 to run the live PubMed smoke test.")

    query = os.getenv("PUBMED_LIVE_QUERY", "mrna cancer vaccine")
    max_results = int(os.getenv("PUBMED_LIVE_MAX_RESULTS", "3"))
    year_from_raw = os.getenv("PUBMED_LIVE_YEAR_FROM")
    year_from = int(year_from_raw) if year_from_raw else None

    source = PubMedSource()
    await source.initialize()

    try:
        results = await source.search_publications(
            query=query,
            max_results=max_results,
            year_from=year_from,
        )
    finally:
        await source.close()

    payload = [publication.model_dump() for publication in results]
    print(json.dumps(payload, indent=2, ensure_ascii=False))

    assert payload, "Live PubMed query returned no results."
    assert all(item["source"] == "pubmed" for item in payload)
    assert all(item["pmid"] for item in payload)
    assert all(item["title"] for item in payload)
