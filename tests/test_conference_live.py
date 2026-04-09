from __future__ import annotations

import os

import pytest

from Medical_Wizard_MCP.sources.crossref import CrossrefConferenceSource
from Medical_Wizard_MCP.sources.europepmc import EuropePMCConferenceSource
from Medical_Wizard_MCP.sources.openalex import OpenAlexConferenceSource


@pytest.mark.asyncio
async def test_conference_sources_live_smoke() -> None:
    if os.getenv("RUN_LIVE_CONFERENCE") != "1":
        pytest.skip("Set RUN_LIVE_CONFERENCE=1 to run the live conference smoke test.")

    query = os.getenv("CONFERENCE_LIVE_QUERY", "neoantigen therapy melanoma")
    year_from_raw = os.getenv("CONFERENCE_LIVE_YEAR_FROM", "2022")
    year_from = int(year_from_raw) if year_from_raw else None
    conference_series = [
        item.strip()
        for item in os.getenv("CONFERENCE_LIVE_SERIES", "ASCO,AACR,ESMO,SITC").split(",")
        if item.strip()
    ]

    specs = [
        ("openalex", OpenAlexConferenceSource()),
        ("crossref", CrossrefConferenceSource()),
        ("europe_pmc", EuropePMCConferenceSource()),
    ]

    results_by_source: dict[str, list[str]] = {}
    total_hits = 0
    for name, source in specs:
        await source.initialize()
        try:
            results = await source.search_conference_abstracts(
                query=query,
                conference_series=conference_series,
                max_results=3,
                year_from=year_from,
            )
        finally:
            await source.close()

        titles = [item.title for item in results]
        results_by_source[name] = titles
        total_hits += len(results)

    print(results_by_source)

    assert results_by_source["openalex"], "OpenAlex live conference search returned no results."
    assert total_hits >= 1, "Live conference search returned no hits across the enabled sources."
