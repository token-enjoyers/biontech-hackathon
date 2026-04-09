from __future__ import annotations

from datetime import date

import httpx
import pytest

from Medical_Wizard_MCP.sources.medrxiv import BASE_URL, MedRxivSource


@pytest.mark.asyncio
async def test_search_preprints_filters_to_unpublished_matching_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/details/medrxiv/2024-01-01/2024-12-31/0/json"
        return httpx.Response(
            200,
            json={
                "messages": [{"total": 3}],
                "collection": [
                    {
                        "doi": "10.1101/2024.03.01.123456",
                        "title": "mRNA vaccine response in GBM",
                        "authors": "Alice Smith; Bob Jones",
                        "date": "2024-03-01",
                        "category": "Cancer Biology",
                        "abstract": "GBM patients showed early signal for mRNA vaccine therapy.",
                        "published": "NA",
                    },
                    {
                        "doi": "10.1101/2024.03.05.222222",
                        "title": "mRNA vaccine response in GBM",
                        "authors": "Carol White",
                        "date": "2024-03-05",
                        "category": "Cancer Biology",
                        "abstract": "This one was later published.",
                        "published": "10.1016/j.cell.2024.01.001",
                    },
                    {
                        "doi": "10.1101/2024.04.01.333333",
                        "title": "Cardiology biomarker update",
                        "authors": "Dan Black",
                        "date": "2024-04-01",
                        "category": "Cardiovascular Medicine",
                        "abstract": "No oncology relevance here.",
                        "published": "NA",
                    },
                ],
            },
        )

    source = MedRxivSource()
    source._client = httpx.AsyncClient(
        base_url=BASE_URL,
        transport=httpx.MockTransport(handler),
    )
    monkeypatch.setattr(
        "Medical_Wizard_MCP.sources.medrxiv.utc_today",
        lambda: date(2024, 12, 31),
    )

    results = await source.search_preprints(
        query="mRNA vaccine GBM",
        max_results=2,
        year_from=2024,
    )

    await source.close()

    assert len(results) == 1
    assert results[0].source == "medrxiv"
    assert results[0].pmid is None
    assert results[0].journal == "medRxiv"
    assert results[0].doi == "10.1101/2024.03.01.123456"
    assert results[0].authors == ["Alice Smith", "Bob Jones"]
    assert results[0].mesh_terms == ["Cancer Biology"]


@pytest.mark.asyncio
async def test_search_preprints_raises_clear_error_on_http_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, request=request)

    source = MedRxivSource()
    source._client = httpx.AsyncClient(
        base_url=BASE_URL,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(RuntimeError, match="medRxiv details failed with status 502"):
        await source.search_preprints(query="mRNA vaccine", max_results=1)

    await source.close()
