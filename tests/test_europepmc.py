from __future__ import annotations

import httpx
import pytest

from Medical_Wizard_MCP.sources.europepmc import BASE_URL, EuropePMCConferenceSource


EUROPEPMC_JSON = {
    "resultList": {
        "result": [
            {
                "id": "PPR1234",
                "pmid": "37001234",
                "title": "SITC abstract on intratumoral mRNA therapy",
                "authorString": "Smith A; Jones B",
                "journalTitle": "SITC Annual Meeting",
                "pubYear": "2024",
                "firstPublicationDate": "2024-03-15",
                "abstractText": "Poster abstract showing manageable safety and immunogenicity.",
                "doi": "10.1136/jitc-2024-SITC.1234",
            },
            {
                "id": "PPR5678",
                "pmid": "37005678",
                "title": "SITC oral presentation on biomarker-selected melanoma cohorts",
                "authorString": "Müller C; Garcia D",
                "journalTitle": "SITC Annual Meeting",
                "pubYear": "2023",
                "abstractText": "Oral presentation reporting translational biomarker data.",
                "doi": "10.1136/jitc-2023-SITC.5678",
            },
        ]
    }
}


@pytest.mark.asyncio
async def test_search_conference_abstracts_returns_normalized_results() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/search")
        assert "mRNA therapy" in request.url.params["query"]
        assert request.url.params["format"] == "json"
        assert request.url.params["resultType"] == "core"
        return httpx.Response(200, json=EUROPEPMC_JSON)

    source = EuropePMCConferenceSource()
    source._client = httpx.AsyncClient(
        base_url=BASE_URL,
        transport=httpx.MockTransport(handler),
    )

    results = await source.search_conference_abstracts(
        "mRNA therapy",
        conference_series=["SITC"],
        max_results=10,
    )
    await source.close()

    assert len(results) == 2

    first = results[0]
    assert first.source == "europe_pmc"
    assert first.source_id == "PPR1234"
    assert first.title == "SITC abstract on intratumoral mRNA therapy"
    assert first.authors == ["Smith A", "Jones B"]
    assert first.conference_name == "SITC Annual Meeting"
    assert first.conference_series == "SITC"
    assert first.presentation_type == "poster"
    assert first.abstract_number is None
    assert first.publication_year == 2024
    assert first.publication_date == "2024-03-15"
    assert first.doi == "10.1136/jitc-2024-SITC.1234"
    assert first.url == "https://europepmc.org/article/MED/37001234"
    assert "manageable safety" in first.abstract

    second = results[1]
    assert second.source_id == "PPR5678"
    assert second.presentation_type == "oral presentation"


@pytest.mark.asyncio
async def test_search_conference_abstracts_applies_year_filter() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=EUROPEPMC_JSON)

    source = EuropePMCConferenceSource()
    source._client = httpx.AsyncClient(
        base_url=BASE_URL,
        transport=httpx.MockTransport(handler),
    )

    results = await source.search_conference_abstracts(
        "mRNA therapy",
        conference_series=["SITC"],
        max_results=10,
        year_from=2024,
    )
    await source.close()

    assert len(results) == 1
    assert results[0].publication_year == 2024


@pytest.mark.asyncio
async def test_search_conference_abstracts_returns_empty_on_no_results() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"resultList": {"result": []}})

    source = EuropePMCConferenceSource()
    source._client = httpx.AsyncClient(
        base_url=BASE_URL,
        transport=httpx.MockTransport(handler),
    )

    results = await source.search_conference_abstracts(
        "no hits query",
        conference_series=["SITC"],
        max_results=5,
    )
    await source.close()

    assert results == []


@pytest.mark.asyncio
async def test_search_conference_abstracts_raises_on_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, request=request)

    source = EuropePMCConferenceSource()
    source._client = httpx.AsyncClient(
        base_url=BASE_URL,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(RuntimeError, match="Europe PMC search failed with status 503"):
        await source.search_conference_abstracts("mRNA therapy", conference_series=["SITC"])

    await source.close()


@pytest.mark.asyncio
async def test_search_conference_abstracts_raises_on_invalid_json() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not-json{{")

    source = EuropePMCConferenceSource()
    source._client = httpx.AsyncClient(
        base_url=BASE_URL,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(RuntimeError, match="Europe PMC search returned invalid JSON"):
        await source.search_conference_abstracts("mRNA therapy", conference_series=["SITC"])

    await source.close()


@pytest.mark.asyncio
async def test_search_conference_abstracts_respects_max_results() -> None:
    many_results = [
        {
            "id": f"PPR{i}",
            "pmid": str(i),
            "title": f"SITC abstract {i}",
            "authorString": "Author A; Author B",
            "journalTitle": "SITC Annual Meeting",
            "pubYear": "2024",
            "abstractText": "Poster abstract.",
        }
        for i in range(20)
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert int(request.url.params["pageSize"]) <= 25
        return httpx.Response(200, json={"resultList": {"result": many_results}})

    source = EuropePMCConferenceSource()
    source._client = httpx.AsyncClient(
        base_url=BASE_URL,
        transport=httpx.MockTransport(handler),
    )

    results = await source.search_conference_abstracts(
        "mRNA therapy",
        conference_series=["SITC"],
        max_results=5,
    )
    await source.close()

    assert len(results) == 5
