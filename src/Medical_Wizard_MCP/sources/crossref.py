from __future__ import annotations

from typing import Any

import httpx

from ..models import ConferenceAbstract
from ._conference_utils import (
    clean_text,
    conference_query_variants,
    date_from_parts,
    detect_conference_series,
    extract_abstract_number,
    first_text,
    has_conference_artifact_signal,
    infer_presentation_type,
    keep_if_recent,
    looks_like_conference_record,
    normalize_conference_series,
    strip_tags,
    year_from_date,
)
from .base import BaseSource

BASE_URL = "https://api.crossref.org"


class CrossrefConferenceSource(BaseSource):
    name = "crossref"
    capabilities = frozenset({"conference_abstract_search"})

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    async def initialize(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            timeout=30.0,
            headers={"User-Agent": "medical-wizard-mcp/0.1.0"},
        )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    async def search_conference_abstracts(
        self,
        query: str,
        conference_series: list[str] | None = None,
        max_results: int = 10,
        year_from: int | None = None,
    ) -> list[ConferenceAbstract]:
        if self._client is None:
            raise RuntimeError("Crossref source not initialized.")

        allowed_series = normalize_conference_series(conference_series)
        results: list[ConferenceAbstract] = []
        seen_ids: set[str] = set()
        for variant in conference_query_variants(query, allowed_series):
            params = {
                "query.bibliographic": variant,
                "rows": min(max_results * 5, 50),
                "mailto": "medical-wizard-mcp@example.com",
            }
            filters: list[str] = []
            if year_from is not None:
                filters.append(f"from-pub-date:{int(year_from)}-01-01")
            if filters:
                params["filter"] = ",".join(filters)

            try:
                response = await self._client.get("/works", params=params)
                response.raise_for_status()
                payload = response.json()
            except httpx.HTTPStatusError as exc:
                raise RuntimeError(f"Crossref works search failed with status {exc.response.status_code}") from exc
            except httpx.HTTPError as exc:
                raise RuntimeError(f"Crossref works request failed: {exc}") from exc
            except ValueError as exc:
                raise RuntimeError("Crossref works returned invalid JSON") from exc

            for item in (payload.get("message") or {}).get("items", []):
                abstract = self._normalize_item(item, allowed_series=allowed_series, year_from=year_from)
                if abstract is None or abstract.source_id in seen_ids:
                    continue
                seen_ids.add(abstract.source_id)
                results.append(abstract)
                if len(results) >= max_results:
                    return results[:max_results]
        return results

    def _normalize_item(
        self,
        item: Any,
        *,
        allowed_series: list[str],
        year_from: int | None,
    ) -> ConferenceAbstract | None:
        if not isinstance(item, dict):
            return None

        title = first_text(item.get("title"))
        event = clean_text((item.get("event") or {}).get("name"))
        container_title = first_text(item.get("container-title"))
        abstract = strip_tags(clean_text(item.get("abstract")))
        conference = detect_conference_series(title, event, container_title, abstract, allowed_series=allowed_series)
        if conference is None or not looks_like_conference_record(title, event, container_title, abstract, allowed_series=allowed_series):
            return None
        if not (
            event
            or abstract
            or extract_abstract_number(title, item.get("article-number"), abstract)
            or has_conference_artifact_signal(title, container_title)
        ):
            return None

        publication_date = date_from_parts((item.get("published-print") or {}).get("date-parts"))
        publication_date = publication_date or date_from_parts((item.get("published-online") or {}).get("date-parts"))
        publication_date = publication_date or date_from_parts((item.get("issued") or {}).get("date-parts"))
        publication_year = year_from_date(publication_date)
        if not keep_if_recent(publication_year, year_from=year_from):
            return None

        doi = clean_text(item.get("DOI")) or None
        source_id = doi or clean_text(item.get("URL"))
        if not source_id or not title:
            return None

        authors = []
        for author in item.get("author", []):
            if not isinstance(author, dict):
                continue
            given = clean_text(author.get("given"))
            family = clean_text(author.get("family"))
            full_name = " ".join(part for part in [given, family] if part)
            if full_name:
                authors.append(full_name)

        conference_name = first_text([event, container_title, conference]) or conference
        return ConferenceAbstract(
            source=self.name,
            source_id=source_id,
            title=title,
            authors=authors,
            conference_name=conference_name,
            conference_series=conference,
            presentation_type=infer_presentation_type(title, event, container_title, abstract),
            abstract_number=extract_abstract_number(title, item.get("article-number"), abstract),
            publication_year=publication_year,
            publication_date=publication_date,
            abstract=abstract,
            doi=doi,
            url=clean_text(item.get("URL")) or None,
            journal=container_title or None,
        )
