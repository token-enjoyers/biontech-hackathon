from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Generic, TypeVar

from ..models import ApprovedDrug, Publication, TrialDetail, TrialSummary, TrialTimeline
from .base import BaseSource

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class SourceWarning:
    source: str
    stage: str
    error: str

    def as_dict(self) -> dict[str, str]:
        return {
            "source": self.source,
            "stage": self.stage,
            "error": self.error,
        }


@dataclass
class ListQueryResult(Generic[T]):
    items: list[T]
    queried_sources: list[str]
    warnings: list[SourceWarning] = field(default_factory=list)


@dataclass
class DetailQueryResult(Generic[T]):
    item: T | None
    queried_sources: list[str]
    warnings: list[SourceWarning] = field(default_factory=list)


class SourceRegistry:
    """Central registry that tools call. Fans out to registered sources and merges results."""

    def __init__(self) -> None:
        self._sources: list[BaseSource] = []
        self._active_sources: list[BaseSource] = []
        self._initialization_warnings: list[SourceWarning] = []
        self._initialized = False

    def register(self, source: BaseSource) -> None:
        self._sources.append(source)

    async def initialize_all(self) -> None:
        if self._initialized:
            return

        self._active_sources = []
        self._initialization_warnings = []

        for source in self._sources:
            try:
                await source.initialize()
                self._active_sources.append(source)
                logger.info("Initialized source: %s", source.name)
            except Exception as exc:
                warning = SourceWarning(
                    source=source.name,
                    stage="initialize",
                    error=str(exc) or exc.__class__.__name__,
                )
                self._initialization_warnings.append(warning)
                logger.exception("Failed to initialize source: %s", source.name)

        self._initialized = True

    async def close_all(self) -> None:
        for source in self._active_sources:
            try:
                await source.close()
            except Exception:
                logger.exception("Failed to close source: %s", source.name)

    def _sources_for(self, capability: str) -> tuple[list[BaseSource], list[SourceWarning]]:
        eligible_sources = [source for source in self._active_sources if source.supports(capability)]
        init_warnings = [
            warning
            for warning in self._initialization_warnings
            if any(source.name == warning.source and source.supports(capability) for source in self._sources)
        ]
        return eligible_sources, list(init_warnings)

    async def search_trials(
        self,
        condition: str,
        phase: str | None = None,
        status: str | None = None,
        sponsor: str | None = None,
        intervention: str | None = None,
        max_results: int = 10,
    ) -> ListQueryResult[TrialSummary]:
        await self.initialize_all()
        sources, warnings = self._sources_for("trial_search")

        results: list[TrialSummary] = []
        outcomes = await asyncio.gather(
            *[
                source.search_trials(
                    condition=condition,
                    phase=phase,
                    status=status,
                    sponsor=sponsor,
                    intervention=intervention,
                    max_results=max_results,
                )
                for source in sources
            ],
            return_exceptions=True,
        )

        for source, outcome in zip(sources, outcomes):
            if isinstance(outcome, Exception):
                warnings.append(
                    SourceWarning(
                        source=source.name,
                        stage="search_trials",
                        error=str(outcome) or outcome.__class__.__name__,
                    )
                )
                logger.error("Source %s failed during search_trials: %s", source.name, outcome)
                continue

            results.extend(outcome)

        return ListQueryResult(
            items=results[:max_results],
            queried_sources=[source.name for source in sources],
            warnings=warnings,
        )

    async def get_trial_details(self, nct_id: str) -> DetailQueryResult[TrialDetail]:
        await self.initialize_all()
        sources, warnings = self._sources_for("trial_details")

        for source in sources:
            try:
                detail = await source.get_trial_details(nct_id)
                if detail is not None:
                    return DetailQueryResult(
                        item=detail,
                        queried_sources=[item.name for item in sources],
                        warnings=warnings,
                    )
            except Exception as exc:
                warnings.append(
                    SourceWarning(
                        source=source.name,
                        stage="get_trial_details",
                        error=str(exc) or exc.__class__.__name__,
                    )
                )
                logger.exception("Source %s failed during get_trial_details", source.name)

        return DetailQueryResult(
            item=None,
            queried_sources=[source.name for source in sources],
            warnings=warnings,
        )

    async def get_trial_timelines(
        self,
        condition: str,
        sponsor: str | None = None,
        phase: str | None = None,
        status: str | None = None,
        max_results: int = 15,
    ) -> ListQueryResult[TrialTimeline]:
        await self.initialize_all()
        sources, warnings = self._sources_for("trial_timelines")

        results: list[TrialTimeline] = []
        outcomes = await asyncio.gather(
            *[
                source.get_trial_timelines(
                    condition=condition,
                    sponsor=sponsor,
                    phase=phase,
                    status=status,
                    max_results=max_results,
                )
                for source in sources
            ],
            return_exceptions=True,
        )

        for source, outcome in zip(sources, outcomes):
            if isinstance(outcome, Exception):
                warnings.append(
                    SourceWarning(
                        source=source.name,
                        stage="get_trial_timelines",
                        error=str(outcome) or outcome.__class__.__name__,
                    )
                )
                logger.error("Source %s failed during get_trial_timelines: %s", source.name, outcome)
                continue

            results.extend(outcome)

        return ListQueryResult(
            items=results[:max_results],
            queried_sources=[source.name for source in sources],
            warnings=warnings,
        )

    async def search_publications(
        self,
        query: str,
        max_results: int = 10,
        year_from: int | None = None,
    ) -> ListQueryResult[Publication]:
        await self.initialize_all()
        sources, warnings = self._sources_for("publication_search")

        results: list[Publication] = []
        outcomes = await asyncio.gather(
            *[
                source.search_publications(
                    query=query,
                    max_results=max_results,
                    year_from=year_from,
                )
                for source in sources
            ],
            return_exceptions=True,
        )

        for source, outcome in zip(sources, outcomes):
            if isinstance(outcome, Exception):
                warnings.append(
                    SourceWarning(
                        source=source.name,
                        stage="search_publications",
                        error=str(outcome) or outcome.__class__.__name__,
                    )
                )
                logger.error("Source %s failed during search_publications: %s", source.name, outcome)
                continue

            results.extend(outcome)

        return ListQueryResult(
            items=results[:max_results],
            queried_sources=[source.name for source in sources],
            warnings=warnings,
        )

    async def search_preprints(
        self,
        query: str,
        max_results: int = 10,
        year_from: int | None = None,
    ) -> ListQueryResult[Publication]:
        await self.initialize_all()
        sources, warnings = self._sources_for("preprint_search")

        results: list[Publication] = []
        outcomes = await asyncio.gather(
            *[
                source.search_preprints(
                    query=query,
                    max_results=max_results,
                    year_from=year_from,
                )
                for source in sources
            ],
            return_exceptions=True,
        )

        for source, outcome in zip(sources, outcomes):
            if isinstance(outcome, Exception):
                warnings.append(
                    SourceWarning(
                        source=source.name,
                        stage="search_preprints",
                        error=str(outcome) or outcome.__class__.__name__,
                    )
                )
                logger.error("Source %s failed during search_preprints: %s", source.name, outcome)
                continue

            results.extend(outcome)

        return ListQueryResult(
            items=results[:max_results],
            queried_sources=[source.name for source in sources],
            warnings=warnings,
        )

    async def search_approved_drugs(
        self,
        indication: str,
        sponsor: str | None = None,
        intervention: str | None = None,
        max_results: int = 10,
    ) -> ListQueryResult[ApprovedDrug]:
        await self.initialize_all()
        sources, warnings = self._sources_for("approved_drug_search")

        results: list[ApprovedDrug] = []
        outcomes = await asyncio.gather(
            *[
                source.search_approved_drugs(
                    indication=indication,
                    sponsor=sponsor,
                    intervention=intervention,
                    max_results=max_results,
                )
                for source in sources
            ],
            return_exceptions=True,
        )

        for source, outcome in zip(sources, outcomes):
            if isinstance(outcome, Exception):
                warnings.append(
                    SourceWarning(
                        source=source.name,
                        stage="search_approved_drugs",
                        error=str(outcome) or outcome.__class__.__name__,
                    )
                )
                logger.error("Source %s failed during search_approved_drugs: %s", source.name, outcome)
                continue

            results.extend(outcome)

        return ListQueryResult(
            items=results[:max_results],
            queried_sources=[source.name for source in sources],
            warnings=warnings,
        )


# Global singleton — sources registered at startup in __main__.py
registry = SourceRegistry()
