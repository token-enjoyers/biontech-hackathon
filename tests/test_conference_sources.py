from __future__ import annotations

import httpx
import pytest

from Medical_Wizard_MCP.sources.europepmc import BASE_URL as EUROPE_PMC_BASE_URL, EuropePMCConferenceSource


@pytest.mark.asyncio
async def test_europe_pmc_conference_source_uses_biomedical_result_fields() -> None:
    payload = {
        "resultList": {
            "result": [
                {
                    "id": "PPR1234",
                    "pmid": "40000001",
                    "title": "SITC abstract on intratumoral mRNA therapy",
                    "journalTitle": "SITC Annual Meeting",
                    "authorString": "Alice Smith; Bob Jones",
                    "firstPublicationDate": "2024-11-08",
                    "pubYear": "2024",
                    "doi": "10.1136/jitc-2024-SITC.1234",
                    "abstractText": "Poster abstract showing manageable safety and immunogenicity.",
                }
            ]
        }
    }

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    source = EuropePMCConferenceSource()
    source._client = httpx.AsyncClient(base_url=EUROPE_PMC_BASE_URL, transport=httpx.MockTransport(handler))

    results = await source.search_conference_abstracts("mRNA therapy", conference_series=["SITC"], max_results=5)
    await source.close()

    assert len(results) == 1
    assert results[0].conference_series == "SITC"
    assert results[0].authors == ["Alice Smith", "Bob Jones"]
    assert results[0].publication_year == 2024
