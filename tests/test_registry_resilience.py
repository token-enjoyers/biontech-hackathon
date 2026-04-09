from __future__ import annotations

import asyncio
import importlib

import pytest

from Medical_Wizard_MCP.models import ApprovedDrug
from Medical_Wizard_MCP.sources.base import BaseSource
from Medical_Wizard_MCP.sources._network import SourceTimeoutError
from Medical_Wizard_MCP.sources.registry import SourceRegistry

registry_module = importlib.import_module("Medical_Wizard_MCP.sources.registry")


class SlowApprovedDrugSource(BaseSource):
    name = "slow_openfda"
    capabilities = frozenset({"approved_drug_search"})

    async def initialize(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def search_approved_drugs(
        self,
        indication: str,
        sponsor: str | None = None,
        intervention: str | None = None,
        max_results: int = 10,
    ) -> list[object]:
        await asyncio.sleep(0.05)
        return []


@pytest.mark.asyncio
async def test_registry_converts_source_timeout_into_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        registry_module,
        "SOURCE_TIMEOUT_RETRIES",
        0,
    )
    monkeypatch.setattr(
        SlowApprovedDrugSource,
        "call_timeout_seconds",
        lambda self, *, stage, requested_max_results=None: 0.01,
    )

    registry = SourceRegistry()
    registry.register(SlowApprovedDrugSource())

    response = await registry.search_approved_drugs(
        indication="NSCLC",
        intervention="pembrolizumab",
        max_results=5,
    )

    assert response.items == []
    assert response.queried_sources == ["slow_openfda"]
    assert len(response.warnings) == 1
    assert response.warnings[0].source == "slow_openfda"
    assert response.warnings[0].stage == "search_approved_drugs"
    assert "timed out" in response.warnings[0].error


class RecordingApprovedDrugSource(BaseSource):
    name = "recording_openfda"
    capabilities = frozenset({"approved_drug_search"})

    def __init__(self) -> None:
        self.observed_max_results: int | None = None

    async def initialize(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def search_approved_drugs(
        self,
        indication: str,
        sponsor: str | None = None,
        intervention: str | None = None,
        max_results: int = 10,
    ) -> list[ApprovedDrug]:
        self.observed_max_results = max_results
        return [
            ApprovedDrug(
                source=self.name,
                approval_id=f"APP-{index}",
                brand_name=f"Drug {index}",
                generic_name=f"generic-{index}",
                indication=indication,
                sponsor="Example",
                route=["IV"],
                product_type="HUMAN PRESCRIPTION DRUG",
                substance_names=[f"substance-{index}"],
            )
            for index in range(max_results)
        ]


@pytest.mark.asyncio
async def test_registry_expands_source_limits_before_trimming() -> None:
    registry = SourceRegistry()
    source = RecordingApprovedDrugSource()
    registry.register(source)

    response = await registry.search_approved_drugs(
        indication="NSCLC",
        intervention="pembrolizumab",
        max_results=4,
    )

    assert source.observed_max_results is not None
    assert source.observed_max_results > 4
    assert len(response.items) == 4


class FlakyApprovedDrugSource(BaseSource):
    name = "flaky_openfda"
    capabilities = frozenset({"approved_drug_search"})

    def __init__(self) -> None:
        self.calls = 0

    async def initialize(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def search_approved_drugs(
        self,
        indication: str,
        sponsor: str | None = None,
        intervention: str | None = None,
        max_results: int = 10,
    ) -> list[ApprovedDrug]:
        self.calls += 1
        if self.calls == 1:
            raise SourceTimeoutError("temporary upstream timeout")
        return [
            ApprovedDrug(
                source=self.name,
                approval_id="APP-1",
                brand_name="Drug 1",
                generic_name="generic-1",
                indication=indication,
                sponsor="Example",
                route=["IV"],
                product_type="HUMAN PRESCRIPTION DRUG",
                substance_names=["substance-1"],
            )
        ]


@pytest.mark.asyncio
async def test_registry_retries_timeout_failures_before_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        registry_module,
        "SOURCE_TIMEOUT_RETRIES",
        1,
    )
    monkeypatch.setattr(
        registry_module,
        "timeout_backoff_seconds",
        lambda attempt_number: 0.0,
    )

    registry = SourceRegistry()
    source = FlakyApprovedDrugSource()
    registry.register(source)

    response = await registry.search_approved_drugs(
        indication="NSCLC",
        intervention="pembrolizumab",
        max_results=3,
    )

    assert source.calls == 2
    assert len(response.items) == 1
    assert response.warnings == []
