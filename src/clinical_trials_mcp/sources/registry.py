from __future__ import annotations

import asyncio
import logging

from clinical_trials_mcp.models import Publication, TrialDetail, TrialSummary, TrialTimeline
from clinical_trials_mcp.sources.base import BaseSource

logger = logging.getLogger(__name__)


class SourceRegistry:
    """Central registry that tools call. Fans out to all registered sources and merges results."""

    def __init__(self) -> None:
        self._sources: list[BaseSource] = []
        self._initialized = False

    def register(self, source: BaseSource) -> None:
        self._sources.append(source)

    async def initialize_all(self) -> None:
        if self._initialized:
            return
        for source in self._sources:
            try:
                await source.initialize()
                logger.info("Initialized source: %s", source.name)
            except Exception:
                logger.exception("Failed to initialize source: %s", source.name)
        self._initialized = True

    async def close_all(self) -> None:
        for source in self._sources:
            try:
                await source.close()
            except Exception:
                logger.exception("Failed to close source: %s", source.name)

    async def search_trials(
        self,
        condition: str,
        phase: str | None = None,
        status: str | None = None,
        sponsor: str | None = None,
        intervention: str | None = None,
        max_results: int = 10,
    ) -> list[TrialSummary]:
        await self.initialize_all()
        tasks = [
            source.search_trials(
                condition=condition,
                phase=phase,
                status=status,
                sponsor=sponsor,
                intervention=intervention,
                max_results=max_results,
            )
            for source in self._sources
        ]
        results: list[TrialSummary] = []
        for coro in asyncio.as_completed(tasks):
            try:
                results.extend(await coro)
            except Exception:
                logger.exception("Source failed during search_trials")
        return results[:max_results]

    async def get_trial_details(self, nct_id: str) -> TrialDetail | None:
        await self.initialize_all()
        for source in self._sources:
            try:
                detail = await source.get_trial_details(nct_id)
                if detail is not None:
                    return detail
            except Exception:
                logger.exception("Source %s failed during get_trial_details", source.name)
        return None

    async def get_trial_timelines(
        self,
        condition: str,
        sponsor: str | None = None,
        max_results: int = 15,
    ) -> list[TrialTimeline]:
        await self.initialize_all()
        tasks = [
            source.get_trial_timelines(
                condition=condition,
                sponsor=sponsor,
                max_results=max_results,
            )
            for source in self._sources
        ]
        results: list[TrialTimeline] = []
        for coro in asyncio.as_completed(tasks):
            try:
                results.extend(await coro)
            except Exception:
                logger.exception("Source failed during get_trial_timelines")
        return results[:max_results]

    async def search_publications(
        self,
        query: str,
        max_results: int = 10,
    ) -> list[Publication]:
        await self.initialize_all()
        tasks = [
            source.search_publications(query=query, max_results=max_results)
            for source in self._sources
        ]
        results: list[Publication] = []
        for coro in asyncio.as_completed(tasks):
            try:
                results.extend(await coro)
            except Exception:
                logger.exception("Source failed during search_publications")
        return results[:max_results]


# Global singleton — sources registered at startup in __main__.py
registry = SourceRegistry()
