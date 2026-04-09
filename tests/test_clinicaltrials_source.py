from __future__ import annotations

import httpx
import pytest

from Medical_Wizard_MCP.sources.clinicaltrials import BASE_URL, ClinicalTrialsSource


LIST_RESPONSE = {
    "studies": [
        {
            "protocolSection": {
                "identificationModule": {
                    "nctId": "NCT12345678",
                    "briefTitle": "Example Lung Cancer Trial",
                },
                "statusModule": {"overallStatus": "RECRUITING"},
                "sponsorCollaboratorsModule": {"leadSponsor": {"name": "BioNTech"}},
                "designModule": {"phases": ["PHASE2"]},
            }
        }
    ]
}


@pytest.mark.asyncio
async def test_search_trials_retries_with_browser_headers_on_403() -> None:
    calls: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(dict(request.headers))
        if len(calls) == 1:
            return httpx.Response(403, request=request)
        return httpx.Response(200, json=LIST_RESPONSE)

    source = ClinicalTrialsSource()
    source._client = httpx.AsyncClient(
        base_url=BASE_URL,
        transport=httpx.MockTransport(handler),
        follow_redirects=True,
        headers=source._base_headers(),
    )

    results = await source.search_trials("lung cancer", max_results=1)

    await source.close()

    assert len(results) == 1
    assert len(calls) == 2
    assert calls[0]["user-agent"] == "medical-wizard-mcp/0.1.0"
    assert "Mozilla/5.0" in calls[1]["user-agent"]
    assert calls[1]["referer"].startswith("https://clinicaltrials.gov/search?")


@pytest.mark.asyncio
async def test_search_trials_raises_clear_error_on_persistent_403() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, request=request)

    source = ClinicalTrialsSource()
    source._client = httpx.AsyncClient(
        base_url=BASE_URL,
        transport=httpx.MockTransport(handler),
        follow_redirects=True,
        headers=source._base_headers(),
    )

    with pytest.raises(RuntimeError, match="bot protection|egress IP restriction"):
        await source.search_trials("lung cancer", max_results=1)

    await source.close()
