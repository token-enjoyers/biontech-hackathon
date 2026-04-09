from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Generic, TypeVar

from ..models import (
    ApprovedDrug,
    ConferenceAbstract,
    OncologyBurdenRecord,
    Publication,
    TrialDetail,
    TrialSummary,
    TrialTimeline,
)
from .base import BaseSource
from ._network import (
    SOURCE_TIMEOUT_RETRIES,
    SourceTimeoutError,
    format_source_timeout_message,
    timeout_backoff_seconds,
)

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

    def _source_priority(self, sources: list[BaseSource]) -> dict[str, int]:
        return {source.name: index for index, source in enumerate(sources)}

    def _completeness_score(self, item: Any) -> int:
        if hasattr(item, "model_dump"):
            payload = item.model_dump()
        elif isinstance(item, dict):
            payload = item
        else:
            return 0

        score = 0
        for value in payload.values():
            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                continue
            if isinstance(value, (list, dict)) and not value:
                continue
            score += 1
        return score

    def _prefer_candidate(self, current: T, candidate: T, source_priority: dict[str, int]) -> bool:
        current_source = getattr(current, "source", "")
        candidate_source = getattr(candidate, "source", "")
        current_rank = source_priority.get(current_source, len(source_priority))
        candidate_rank = source_priority.get(candidate_source, len(source_priority))
        if candidate_rank != current_rank:
            return candidate_rank < current_rank
        return self._completeness_score(candidate) > self._completeness_score(current)

    def _merge_list_items(
        self,
        items: list[T],
        *,
        sources: list[BaseSource],
        key_fn: Callable[[T], str | None],
    ) -> list[T]:
        source_priority = self._source_priority(sources)
        deduped_by_key: dict[str, T] = {}
        ordered_keys: list[str] = []
        passthrough_items: list[T] = []

        for item in items:
            merge_key = key_fn(item)
            if not merge_key:
                passthrough_items.append(item)
                continue

            existing = deduped_by_key.get(merge_key)
            if existing is None:
                deduped_by_key[merge_key] = item
                ordered_keys.append(merge_key)
                continue

            if self._prefer_candidate(existing, item, source_priority):
                deduped_by_key[merge_key] = item

        return [deduped_by_key[key] for key in ordered_keys] + passthrough_items

    async def _run_source_call(
        self,
        *,
        source: BaseSource,
        stage: str,
        requested_max_results: int | None = None,
        operation_factory: Callable[[], Awaitable[T]],
    ) -> T:
        timeout_seconds = source.call_timeout_seconds(
            stage=stage,
            requested_max_results=requested_max_results,
        )
        last_timeout_error: Exception | None = None
        for attempt in range(SOURCE_TIMEOUT_RETRIES + 1):
            try:
                return await asyncio.wait_for(operation_factory(), timeout=timeout_seconds)
            except asyncio.TimeoutError as exc:
                last_timeout_error = exc
                if attempt >= SOURCE_TIMEOUT_RETRIES:
                    break
                delay = timeout_backoff_seconds(attempt + 1)
                logger.warning(
                    "Retrying %s %s after outer timeout on attempt %s/%s in %.2fs",
                    source.name,
                    stage,
                    attempt + 1,
                    SOURCE_TIMEOUT_RETRIES + 1,
                    delay,
                )
                await asyncio.sleep(delay)
            except SourceTimeoutError as exc:
                last_timeout_error = exc
                if attempt >= SOURCE_TIMEOUT_RETRIES:
                    raise
                delay = timeout_backoff_seconds(attempt + 1)
                logger.warning(
                    "Retrying %s %s after source timeout on attempt %s/%s in %.2fs: %s",
                    source.name,
                    stage,
                    attempt + 1,
                    SOURCE_TIMEOUT_RETRIES + 1,
                    delay,
                    exc,
                )
                await asyncio.sleep(delay)
        raise RuntimeError(format_source_timeout_message(source.name, stage, timeout_seconds)) from last_timeout_error

    async def search_trials(
        self,
        condition: str,
        query: str | None = None,
        phase: str | None = None,
        status: str | None = None,
        sponsor: str | None = None,
        intervention: str | None = None,
        max_results: int = 10,
    ) -> ListQueryResult[TrialSummary]:
        await self.initialize_all()
        sources, warnings = self._sources_for("trial_search")

        results: list[TrialSummary] = []
        tasks = []
        for source in sources:
            source_max_results = source.expand_max_results(
                stage="search_trials",
                requested_max_results=max_results,
            )
            tasks.append(
                self._run_source_call(
                    source=source,
                    stage="search_trials",
                    requested_max_results=source_max_results,
                    operation_factory=lambda source=source, source_max_results=source_max_results: source.search_trials(
                        condition=condition,
                        query=query,
                        phase=phase,
                        status=status,
                        sponsor=sponsor,
                        intervention=intervention,
                        max_results=source_max_results,
                    ),
                )
            )
        outcomes = await asyncio.gather(
            *tasks,
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

        merged_results = self._merge_list_items(
            results,
            sources=sources,
            key_fn=lambda trial: getattr(trial, "nct_id", None),
        )

        return ListQueryResult(
            items=merged_results[:max_results],
            queried_sources=[source.name for source in sources],
            warnings=warnings,
        )

    async def get_trial_details(self, nct_id: str) -> DetailQueryResult[TrialDetail]:
        await self.initialize_all()
        sources, warnings = self._sources_for("trial_details")
        attempted_sources: list[str] = []

        for source in sources:
            attempted_sources.append(source.name)
            try:
                detail = await self._run_source_call(
                    source=source,
                    stage="get_trial_details",
                    requested_max_results=None,
                    operation_factory=lambda source=source: source.get_trial_details(nct_id),
                )
                if detail is not None:
                    return DetailQueryResult(
                        item=detail,
                        queried_sources=list(attempted_sources),
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
            queried_sources=list(attempted_sources),
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
        tasks = []
        for source in sources:
            source_max_results = source.expand_max_results(
                stage="get_trial_timelines",
                requested_max_results=max_results,
            )
            tasks.append(
                self._run_source_call(
                    source=source,
                    stage="get_trial_timelines",
                    requested_max_results=source_max_results,
                    operation_factory=lambda source=source, source_max_results=source_max_results: source.get_trial_timelines(
                        condition=condition,
                        sponsor=sponsor,
                        phase=phase,
                        status=status,
                        max_results=source_max_results,
                    ),
                )
            )
        outcomes = await asyncio.gather(
            *tasks,
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

        merged_results = self._merge_list_items(
            results,
            sources=sources,
            key_fn=lambda trial: getattr(trial, "nct_id", None),
        )

        return ListQueryResult(
            items=merged_results[:max_results],
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
        tasks = []
        for source in sources:
            source_max_results = source.expand_max_results(
                stage="search_publications",
                requested_max_results=max_results,
            )
            tasks.append(
                self._run_source_call(
                    source=source,
                    stage="search_publications",
                    requested_max_results=source_max_results,
                    operation_factory=lambda source=source, source_max_results=source_max_results: source.search_publications(
                        query=query,
                        max_results=source_max_results,
                        year_from=year_from,
                    ),
                )
            )
        outcomes = await asyncio.gather(
            *tasks,
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

        merged_results = self._merge_list_items(
            results,
            sources=sources,
            key_fn=lambda publication: getattr(publication, "pmid", None)
            or getattr(publication, "doi", None)
            or getattr(publication, "title", None),
        )

        return ListQueryResult(
            items=merged_results[:max_results],
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
        tasks = []
        for source in sources:
            source_max_results = source.expand_max_results(
                stage="search_preprints",
                requested_max_results=max_results,
            )
            tasks.append(
                self._run_source_call(
                    source=source,
                    stage="search_preprints",
                    requested_max_results=source_max_results,
                    operation_factory=lambda source=source, source_max_results=source_max_results: source.search_preprints(
                        query=query,
                        max_results=source_max_results,
                        year_from=year_from,
                    ),
                )
            )
        outcomes = await asyncio.gather(
            *tasks,
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

        merged_results = self._merge_list_items(
            results,
            sources=sources,
            key_fn=lambda publication: getattr(publication, "doi", None)
            or getattr(publication, "title", None),
        )

        return ListQueryResult(
            items=merged_results[:max_results],
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
        tasks = []
        for source in sources:
            source_max_results = source.expand_max_results(
                stage="search_approved_drugs",
                requested_max_results=max_results,
            )
            tasks.append(
                self._run_source_call(
                    source=source,
                    stage="search_approved_drugs",
                    requested_max_results=source_max_results,
                    operation_factory=lambda source=source, source_max_results=source_max_results: source.search_approved_drugs(
                        indication=indication,
                        sponsor=sponsor,
                        intervention=intervention,
                        max_results=source_max_results,
                    ),
                )
            )
        outcomes = await asyncio.gather(
            *tasks,
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

        merged_results = self._merge_list_items(
            results,
            sources=sources,
            key_fn=lambda drug: getattr(drug, "approval_id", None)
            or getattr(drug, "generic_name", None)
            or getattr(drug, "brand_name", None),
        )

        return ListQueryResult(
            items=merged_results[:max_results],
            queried_sources=[source.name for source in sources],
            warnings=warnings,
        )

    async def search_conference_abstracts(
        self,
        query: str,
        conference_series: list[str] | None = None,
        max_results: int = 10,
        year_from: int | None = None,
    ) -> ListQueryResult[ConferenceAbstract]:
        await self.initialize_all()
        sources, warnings = self._sources_for("conference_abstract_search")

        results: list[ConferenceAbstract] = []
        tasks = []
        for source in sources:
            source_max_results = source.expand_max_results(
                stage="search_conference_abstracts",
                requested_max_results=max_results,
            )
            tasks.append(
                self._run_source_call(
                    source=source,
                    stage="search_conference_abstracts",
                    requested_max_results=source_max_results,
                    operation_factory=lambda source=source, source_max_results=source_max_results: source.search_conference_abstracts(
                        query=query,
                        conference_series=conference_series,
                        max_results=source_max_results,
                        year_from=year_from,
                    ),
                )
            )
        outcomes = await asyncio.gather(
            *tasks,
            return_exceptions=True,
        )

        for source, outcome in zip(sources, outcomes):
            if isinstance(outcome, Exception):
                warnings.append(
                    SourceWarning(
                        source=source.name,
                        stage="search_conference_abstracts",
                        error=str(outcome) or outcome.__class__.__name__,
                    )
                )
                logger.error("Source %s failed during search_conference_abstracts: %s", source.name, outcome)
                continue

            results.extend(outcome)

        merged_results = self._merge_list_items(
            results,
            sources=sources,
            key_fn=lambda item: getattr(item, "doi", None)
            or "|".join(
                part
                for part in [
                    getattr(item, "conference_series", None) or getattr(item, "conference_name", None),
                    getattr(item, "title", None),
                    str(getattr(item, "publication_year", "") or ""),
                ]
                if part
            ).lower()
            or getattr(item, "source_id", None),
        )

        return ListQueryResult(
            items=merged_results[:max_results],
            queried_sources=[source.name for source in sources],
            warnings=warnings,
        )

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
    ) -> ListQueryResult[OncologyBurdenRecord]:
        await self.initialize_all()
        sources, warnings = self._sources_for("oncology_burden_search")

        results: list[OncologyBurdenRecord] = []
        outcomes = await asyncio.gather(
            *[
                source.search_oncology_burden(
                    site=site,
                    country=country,
                    sex=sex,
                    indicator=indicator,
                    year=year,
                    age_min=age_min,
                    age_max=age_max,
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
                        stage="search_oncology_burden",
                        error=str(outcome) or outcome.__class__.__name__,
                    )
                )
                logger.error("Source %s failed during search_oncology_burden: %s", source.name, outcome)
                continue

            results.extend(outcome)

        merged_results = self._merge_list_items(
            results,
            sources=sources,
            key_fn=lambda record: "|".join(
                [
                    str(getattr(record, "dataset", "") or ""),
                    str(getattr(record, "country", "") or ""),
                    str(getattr(record, "sex", "") or ""),
                    str(getattr(record, "site", "") or ""),
                    str(getattr(record, "indicator", "") or ""),
                    str(getattr(record, "geo_code", "") or ""),
                    str(getattr(record, "year", "") or ""),
                    str(getattr(record, "age_min", "") or ""),
                    str(getattr(record, "age_max", "") or ""),
                ]
            ),
        )

        return ListQueryResult(
            items=merged_results[:max_results],
            queried_sources=[source.name for source in sources],
            warnings=warnings,
        )


# Global singleton — sources registered at startup in __main__.py
registry = SourceRegistry()
