from __future__ import annotations

import json
import os

import pytest

from Medical_Wizard_MCP.sources.europepmc import EuropePMCConferenceSource


@pytest.mark.asyncio
async def test_europepmc_live_output() -> None:
    if os.getenv("RUN_LIVE_EUROPEPMC") != "1":
        pytest.skip("Set RUN_LIVE_EUROPEPMC=1 to run the live Europe PMC smoke test.")

    query = os.getenv("EUROPEPMC_LIVE_QUERY", "mRNA therapy")
    max_results = int(os.getenv("EUROPEPMC_LIVE_MAX_RESULTS", "3"))
    year_from_raw = os.getenv("EUROPEPMC_LIVE_YEAR_FROM")
    year_from = int(year_from_raw) if year_from_raw else None
    conference_series = [
        item.strip()
        for item in os.getenv("EUROPEPMC_LIVE_SERIES", "SITC,ASCO,AACR,ESMO").split(",")
        if item.strip()
    ]

    source = EuropePMCConferenceSource()
    await source.initialize()

    try:
        results = await source.search_conference_abstracts(
            query=query,
            conference_series=conference_series,
            max_results=max_results,
            year_from=year_from,
        )
    finally:
        await source.close()

    payload = [item.model_dump() for item in results]
    print(json.dumps(payload, indent=2, ensure_ascii=False))

    assert payload, "Live Europe PMC conference query returned no results."
    assert all(item["source"] == "europe_pmc" for item in payload)
    assert all(item["title"] for item in payload)
