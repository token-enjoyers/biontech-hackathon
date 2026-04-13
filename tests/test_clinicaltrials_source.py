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
                "sponsorCollaboratorsModule": {"leadSponsor": {"name": "Company"}},
                "designModule": {"phases": ["PHASE2"]},
            }
        }
    ]
}


@pytest.mark.asyncio
async def test_search_trials_defaults_to_curl() -> None:
    source = ClinicalTrialsSource()

    async def fake_curl(
        path: str,
        *,
        params: dict[str, str],
        stage: str,
        requested_max_results: int | None = None,
        allow_not_found: bool = False,
    ) -> dict[str, object]:
        assert path == "/studies"
        assert stage == "search_trials"
        assert requested_max_results == 1
        assert allow_not_found is False
        assert params["query.cond"] == "lung cancer"
        return LIST_RESPONSE

    source._get_json_via_curl = fake_curl  # type: ignore[method-assign]

    results = await source.search_trials("lung cancer", max_results=1)

    assert len(results) == 1
    assert results[0].nct_id == "NCT12345678"
    assert source._prefer_curl is True


@pytest.mark.asyncio
async def test_search_trials_switches_to_curl_after_first_403_when_opted_into_httpx(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CLINICALTRIALS_PREFER_CURL", "0")
    calls: list[dict[str, str]] = []
    curl_calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(dict(request.headers))
        return httpx.Response(403, request=request)

    source = ClinicalTrialsSource()
    source._client = httpx.AsyncClient(
        base_url=BASE_URL,
        transport=httpx.MockTransport(handler),
        follow_redirects=True,
        headers=source._base_headers(),
    )

    async def fake_curl(
        path: str,
        *,
        params: dict[str, str],
        stage: str,
        requested_max_results: int | None = None,
        allow_not_found: bool = False,
    ) -> dict[str, object]:
        curl_calls.append((path, stage))
        assert requested_max_results == 1
        assert allow_not_found is False
        assert params["query.cond"] == "lung cancer"
        return LIST_RESPONSE

    source._get_json_via_curl = fake_curl  # type: ignore[method-assign]

    first_results = await source.search_trials("lung cancer", max_results=1)
    second_results = await source.search_trials("lung cancer", max_results=1)

    await source.close()

    assert len(first_results) == 1
    assert len(second_results) == 1
    assert len(calls) == 1
    assert len(curl_calls) == 2
    assert calls[0]["user-agent"] == "medical-wizard-mcp/0.1.0"
    assert source._prefer_curl is True


@pytest.mark.asyncio
async def test_search_trials_falls_back_to_curl_on_persistent_403() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, request=request)

    source = ClinicalTrialsSource()
    source._client = httpx.AsyncClient(
        base_url=BASE_URL,
        transport=httpx.MockTransport(handler),
        follow_redirects=True,
        headers=source._base_headers(),
    )

    async def fake_curl(
        path: str,
        *,
        params: dict[str, str],
        stage: str,
        requested_max_results: int | None = None,
        allow_not_found: bool = False,
    ) -> dict[str, object]:
        assert path == "/studies"
        assert params["query.cond"] == "lung cancer"
        assert stage == "search_trials"
        assert requested_max_results == 1
        assert allow_not_found is False
        return LIST_RESPONSE

    source._get_json_via_curl = fake_curl  # type: ignore[method-assign]

    results = await source.search_trials("lung cancer", max_results=1)

    assert len(results) == 1
    assert results[0].nct_id == "NCT12345678"

    await source.close()


@pytest.mark.asyncio
async def test_search_trials_raises_clear_error_when_curl_fallback_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, request=request)

    source = ClinicalTrialsSource()
    source._client = httpx.AsyncClient(
        base_url=BASE_URL,
        transport=httpx.MockTransport(handler),
        follow_redirects=True,
        headers=source._base_headers(),
    )

    monkeypatch.setattr("Medical_Wizard_MCP.sources.clinicaltrials.shutil.which", lambda _: None)

    with pytest.raises(RuntimeError, match="curl fallback is unavailable"):
        await source.search_trials("lung cancer", max_results=1)

    await source.close()


@pytest.mark.asyncio
async def test_get_trial_details_uses_shared_curl_transport_after_403(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CLINICALTRIALS_PREFER_CURL", "0")
    calls = 0
    detail_response = {
        "protocolSection": {
            "identificationModule": {
                "nctId": "NCT12345678",
                "briefTitle": "Example Lung Cancer Trial",
            },
            "statusModule": {"overallStatus": "RECRUITING"},
            "sponsorCollaboratorsModule": {"leadSponsor": {"name": "Company"}},
            "designModule": {"phases": ["PHASE2"]},
            "armsInterventionsModule": {"armGroups": []},
            "outcomesModule": {"secondaryOutcomes": []},
            "conditionsModule": {"conditions": ["lung cancer"]},
            "contactsLocationsModule": {"locations": [], "overallOfficials": []},
            "eligibilityModule": {},
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(403, request=request)

    source = ClinicalTrialsSource()
    source._client = httpx.AsyncClient(
        base_url=BASE_URL,
        transport=httpx.MockTransport(handler),
        follow_redirects=True,
        headers=source._base_headers(),
    )

    async def fake_curl(
        path: str,
        *,
        params: dict[str, str],
        stage: str,
        requested_max_results: int | None = None,
        allow_not_found: bool = False,
    ) -> dict[str, object] | None:
        assert path == "/studies/NCT12345678"
        assert stage == "get_trial_details"
        assert requested_max_results is None
        assert allow_not_found is True
        return detail_response

    source._get_json_via_curl = fake_curl  # type: ignore[method-assign]

    detail = await source.get_trial_details("NCT12345678")

    await source.close()

    assert detail is not None
    assert detail.nct_id == "NCT12345678"
    assert calls == 1
    assert source._prefer_curl is True


def test_apply_phase_filter_uses_supported_advanced_query() -> None:
    source = ClinicalTrialsSource()
    params: dict[str, str] = {}

    source._apply_phase_filter(params, "PHASE1")

    assert params["filter.advanced"] == "AREA[Phase]PHASE1"


def test_apply_phase_filter_composes_with_existing_advanced_filter() -> None:
    source = ClinicalTrialsSource()
    params = {"filter.advanced": "AREA[LeadSponsorName]Company"}

    source._apply_phase_filter(params, "PHASE2")

    assert params["filter.advanced"] == "(AREA[LeadSponsorName]Company) AND (AREA[Phase]PHASE2)"


def test_env_prefers_curl_respects_false_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLINICALTRIALS_PREFER_CURL", "false")

    source = ClinicalTrialsSource()

    assert source._prefer_curl is False
