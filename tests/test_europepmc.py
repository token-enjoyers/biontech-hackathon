from __future__ import annotations

import httpx
import pytest

from Medical_Wizard_MCP.sources.europepmc import BASE_URL, EuropePMCSource


EUROPEPMC_JSON = {
    "resultList": {
        "result": [
            {
                "pmid": "37001234",
                "title": "mRNA cancer vaccine phase 2 trial results",
                "authorString": "Smith A, Jones B, et al.",
                "journalTitle": "Nature Medicine",
                "pubYear": "2024",
                "firstPublicationDate": "2024-03-15",
                "abstractText": "Background: mRNA vaccines show promising results. Methods: Phase 2 trial.",
                "doi": "10.1038/s41591-024-0001",
                "meshHeadingList": {
                    "meshHeading": [
                        {"descriptorName": "Vaccines, mRNA"},
                        {"descriptorName": "Lung Neoplasms"},
                    ]
                },
            },
            {
                "pmid": "37005678",
                "title": "Pembrolizumab in NSCLC: updated survival data",
                "authorString": "Müller C, Garcia D",
                "journalTitle": "Journal of Clinical Oncology",
                "pubYear": "2023",
                "abstractText": "Overall survival benefit confirmed at 5-year follow-up.",
                "doi": "10.1200/JCO.2023.0002",
                "meshHeadingList": {},
            },
        ]
    }
}


@pytest.mark.asyncio
async def test_search_publications_returns_normalized_results() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/search"
        assert request.url.params["query"] == "mRNA vaccine NSCLC"
        assert request.url.params["format"] == "json"
        assert request.url.params["resultType"] == "core"
        return httpx.Response(200, json=EUROPEPMC_JSON)

    source = EuropePMCSource()
    source._client = httpx.AsyncClient(
        base_url=BASE_URL,
        transport=httpx.MockTransport(handler),
    )

    results = await source.search_publications("mRNA vaccine NSCLC", max_results=10)
    await source.close()

    assert len(results) == 2

    first = results[0]
    assert first.source == "europepmc"
    assert first.pmid == "37001234"
    assert first.title == "mRNA cancer vaccine phase 2 trial results"
    assert first.authors == ["Smith A", "Jones B"]
    assert first.journal == "Nature Medicine"
    assert first.pub_date == "2024"
    assert first.doi == "10.1038/s41591-024-0001"
    assert first.mesh_terms == ["Vaccines, mRNA", "Lung Neoplasms"]
    assert "mRNA vaccines" in first.abstract

    second = results[1]
    assert second.pmid == "37005678"
    assert second.journal == "Journal of Clinical Oncology"
    assert second.mesh_terms == []


@pytest.mark.asyncio
async def test_search_publications_applies_year_filter() -> None:
    captured_params: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_params.update(dict(request.url.params))
        return httpx.Response(200, json={"resultList": {"result": []}})

    source = EuropePMCSource()
    source._client = httpx.AsyncClient(
        base_url=BASE_URL,
        transport=httpx.MockTransport(handler),
    )

    results = await source.search_publications("NSCLC", max_results=5, year_from=2022)
    await source.close()

    assert "2022" in captured_params["query"]
    assert "2099" in captured_params["query"]
    assert results == []


@pytest.mark.asyncio
async def test_search_publications_returns_empty_on_no_results() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"resultList": {"result": []}})

    source = EuropePMCSource()
    source._client = httpx.AsyncClient(
        base_url=BASE_URL,
        transport=httpx.MockTransport(handler),
    )

    results = await source.search_publications("no hits query", max_results=5)
    await source.close()

    assert results == []


@pytest.mark.asyncio
async def test_search_publications_raises_on_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, request=request)

    source = EuropePMCSource()
    source._client = httpx.AsyncClient(
        base_url=BASE_URL,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(RuntimeError, match="Europe PMC search failed with status 503"):
        await source.search_publications("mRNA vaccine")

    await source.close()


@pytest.mark.asyncio
async def test_search_publications_raises_on_invalid_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not-json{{")

    source = EuropePMCSource()
    source._client = httpx.AsyncClient(
        base_url=BASE_URL,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(RuntimeError, match="Europe PMC returned invalid JSON"):
        await source.search_publications("mRNA vaccine")

    await source.close()


@pytest.mark.asyncio
async def test_search_publications_strips_et_al_from_authors() -> None:
    payload = {
        "resultList": {
            "result": [
                {
                    "pmid": "99999",
                    "title": "Some trial paper",
                    "authorString": "Brown E, White F, et al.",
                    "journalTitle": "Lancet",
                    "pubYear": "2023",
                }
            ]
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    source = EuropePMCSource()
    source._client = httpx.AsyncClient(
        base_url=BASE_URL,
        transport=httpx.MockTransport(handler),
    )

    results = await source.search_publications("trial", max_results=5)
    await source.close()

    assert results[0].authors == ["Brown E", "White F"]


@pytest.mark.asyncio
async def test_search_publications_respects_max_results() -> None:
    many_results = [
        {
            "pmid": str(i),
            "title": f"Paper {i}",
            "authorString": "Author A",
            "journalTitle": "Journal",
            "pubYear": "2024",
        }
        for i in range(20)
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert int(request.url.params["pageSize"]) <= 25
        return httpx.Response(200, json={"resultList": {"result": many_results}})

    source = EuropePMCSource()
    source._client = httpx.AsyncClient(
        base_url=BASE_URL,
        transport=httpx.MockTransport(handler),
    )

    results = await source.search_publications("cancer", max_results=5)
    await source.close()

    assert len(results) == 5
