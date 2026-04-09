from __future__ import annotations

import math
from abc import ABC, abstractmethod


from ._network import SOURCE_CALL_TIMEOUT_SECONDS
from ..models import (
    ApprovedDrug,
    ConferenceAbstract,
    OncologyBurdenRecord,
    Publication,
    TrialDetail,
    TrialSummary,
    TrialTimeline,
)


class BaseSource(ABC):
    """Abstract base class for all data sources.

    Each source overrides only the methods it supports.
    Default implementations return empty results (not NotImplementedError).
    """

    name: str
    capabilities: frozenset[str] = frozenset()

    @abstractmethod
    async def initialize(self) -> None:
        """Set up HTTP client and validate connectivity."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Clean up resources (e.g. close HTTP client)."""
        ...

    def supports(self, capability: str) -> bool:
        return capability in self.capabilities

    def expand_max_results(self, *, stage: str, requested_max_results: int) -> int:
        requested = max(1, requested_max_results)
        stage_config = {
            "search_trials": (2.0, 50),
            "get_trial_timelines": (2.0, 60),
            "search_publications": (2.0, 30),
            "search_preprints": (2.0, 30),
            "search_approved_drugs": (2.5, 40),
        }
        multiplier, cap = stage_config.get(stage, (1.0, requested))
        expanded = max(requested, math.ceil(requested * multiplier))
        return min(expanded, cap)

    def call_timeout_seconds(
        self,
        *,
        stage: str,
        requested_max_results: int | None = None,
    ) -> float:
        timeout = SOURCE_CALL_TIMEOUT_SECONDS
        if requested_max_results is None:
            return timeout

        per_result = {
            "search_trials": 0.30,
            "get_trial_timelines": 0.30,
            "search_publications": 0.20,
            "search_preprints": 0.20,
            "search_approved_drugs": 0.25,
            "search_conference_abstracts": 0.20,
        }.get(stage, 0.0)
        timeout += per_result * min(max(requested_max_results, 1), 60)
        return round(timeout, 1)

    async def search_trials(
        self,
        condition: str,
        query: str | None = None,
        phase: str | None = None,
        status: str | None = None,
        sponsor: str | None = None,
        intervention: str | None = None,
        max_results: int = 10,
    ) -> list[TrialSummary]:
        return []

    async def get_trial_details(self, nct_id: str) -> TrialDetail | None:
        return None

    async def get_trial_timelines(
        self,
        condition: str,
        sponsor: str | None = None,
        phase: str | None = None,
        status: str | None = None,
        max_results: int = 15,
    ) -> list[TrialTimeline]:
        return []

    async def search_publications(
        self,
        query: str,
        max_results: int = 10,
        year_from: int | None = None,
    ) -> list[Publication]:
        return []

    async def search_preprints(
        self,
        query: str,
        max_results: int = 10,
        year_from: int | None = None,
    ) -> list[Publication]:
        return []

    async def search_approved_drugs(
        self,
        indication: str,
        sponsor: str | None = None,
        intervention: str | None = None,
        max_results: int = 10,
    ) -> list[ApprovedDrug]:
        return []

    async def search_conference_abstracts(
        self,
        query: str,
        conference_series: list[str] | None = None,
        max_results: int = 10,
        year_from: int | None = None,
    ) -> list[ConferenceAbstract]:
        return []

    async def search_oncology_burden(
        self,
        *,
        site: str | None = None,
        country: str | None = None,
        sex: str | None = None,
        indicator: str | None = None,
        year: int | None = None,
        age_min: int | None = None,
        age_max: int | None = None,
        max_results: int = 10,
    ) -> list[OncologyBurdenRecord]:
        return []
