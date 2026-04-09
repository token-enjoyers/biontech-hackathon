from __future__ import annotations

import httpx
import pytest

from Medical_Wizard_MCP.sources.crossref import BASE_URL as CROSSREF_BASE_URL, CrossrefConferenceSource
from Medical_Wizard_MCP.sources.europepmc import BASE_URL as EUROPE_PMC_BASE_URL, EuropePMCConferenceSource
from Medical_Wizard_MCP.sources.openalex import BASE_URL as OPENALEX_BASE_URL, OpenAlexConferenceSource


@pytest.mark.asyncio
async def test_openalex_conference_source_filters_to_target_series() -> None:
    payload = {
        "results": [
            {
                "id": "https://openalex.org/W123",
                "display_name": "Late-breaking ASCO abstract for individualized neoantigen therapy",
                "publication_year": 2025,
                "publication_date": "2025-06-01",
                "doi": "https://doi.org/10.1200/JCO.2025.2501",
                "authorships": [{"author": {"display_name": "Alice Smith"}}],
                "primary_location": {
                    "landing_page_url": "https://doi.org/10.1200/JCO.2025.2501",
                    "source": {"display_name": "ASCO Annual Meeting"},
                },
                "abstract_inverted_index": {"neoantigen": [0], "therapy": [1]},
            }
        ]
    }

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    source = OpenAlexConferenceSource()
    source._client = httpx.AsyncClient(base_url=OPENALEX_BASE_URL, transport=httpx.MockTransport(handler))

    results = await source.search_conference_abstracts("neoantigen therapy", conference_series=["ASCO"], max_results=5)
    await source.close()

    assert len(results) == 1
    assert results[0].conference_series == "ASCO"
    assert results[0].title.startswith("Late-breaking ASCO")


@pytest.mark.asyncio
async def test_crossref_conference_source_maps_event_metadata() -> None:
    payload = {
        "message": {
            "items": [
                {
                    "title": ["AACR abstract for mRNA vaccine combinations"],
                    "event": {"name": "AACR Annual Meeting 2025"},
                    "container-title": ["Cancer Research"],
                    "issued": {"date-parts": [[2025, 4, 28]]},
                    "DOI": "10.1158/1538-7445.AM2025-1234",
                    "URL": "https://doi.org/10.1158/1538-7445.AM2025-1234",
                    "author": [{"given": "Alice", "family": "Smith"}],
                    "abstract": "<jats:p>Poster abstract for biomarker-selected cohorts.</jats:p>",
                }
            ]
        }
    }

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    source = CrossrefConferenceSource()
    source._client = httpx.AsyncClient(base_url=CROSSREF_BASE_URL, transport=httpx.MockTransport(handler))

    results = await source.search_conference_abstracts("mRNA vaccine", conference_series=["AACR"], max_results=5)
    await source.close()

    assert len(results) == 1
    assert results[0].conference_series == "AACR"
    assert results[0].conference_name == "AACR Annual Meeting 2025"
    assert results[0].doi == "10.1158/1538-7445.AM2025-1234"


@pytest.mark.asyncio
async def test_crossref_conference_source_filters_low_signal_meeting_tips() -> None:
    payload = {
        "message": {
            "items": [
                {
                    "title": ["ASCO Annual Meeting Tips"],
                    "container-title": ["Oncology Nursing News"],
                    "issued": {"date-parts": [[2024, 6, 1]]},
                    "DOI": "10.0000/meeting-tips",
                    "URL": "https://doi.org/10.0000/meeting-tips",
                }
            ]
        }
    }

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    source = CrossrefConferenceSource()
    source._client = httpx.AsyncClient(base_url=CROSSREF_BASE_URL, transport=httpx.MockTransport(handler))

    results = await source.search_conference_abstracts("melanoma", conference_series=["ASCO"], max_results=5)
    await source.close()

    assert results == []


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
