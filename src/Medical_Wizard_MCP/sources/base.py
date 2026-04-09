from __future__ import annotations

from abc import ABC, abstractmethod

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
