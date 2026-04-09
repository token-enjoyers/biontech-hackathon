from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import Publication, TrialDetail, TrialSummary, TrialTimeline


class BaseSource(ABC):
    """Abstract base class for all data sources.

    Each source overrides only the methods it supports.
    Default implementations return empty results (not NotImplementedError).
    """

    name: str

    @abstractmethod
    async def initialize(self) -> None:
        """Set up HTTP client and validate connectivity."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Clean up resources (e.g. close HTTP client)."""
        ...

    async def search_trials(
        self,
        condition: str,
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
