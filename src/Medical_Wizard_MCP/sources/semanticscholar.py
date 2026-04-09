from __future__ import annotations

import os
from typing import Any

import httpx

from ..models import ConferenceAbstract
from ._conference_utils import (
    clean_text,
    conference_query_variants,
    detect_conference_series,
    extract_abstract_number,
    infer_presentation_type,
    keep_if_recent,
    looks_like_conference_record,
    normalize_conference_series,
)
from .base import BaseSource

BASE_URL = "https://api.semanticscholar.org/graph/v1"


class SemanticScholarConferenceSource(BaseSource):
    name = "semantic_scholar"
    capabilities = frozenset({"conference_abstract_search"})

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    async def initialize(self) -> None:
        headers = {"User-Agent": "medical-wizard-mcp/0.1.0"}
        api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY")
        if api_key:
            headers["x-api-key"] = api_key
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            timeout=30.0,
            headers=headers,
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
            raise RuntimeError("Semantic Scholar source not initialized.")

        allowed_series = normalize_conference_series(conference_series)
        results: list[ConferenceAbstract] = []
        seen_ids: set[str] = set()
        for variant in conference_query_variants(query, allowed_series):
            params = {
                "query": variant,
                "limit": min(max_results * 5, 50),
                "fields": ",".join(
                    [
                        "title",
                        "abstract",
                        "year",
                        "venue",
                        "authors",
                        "publicationTypes",
                        "externalIds",
                        "paperId",
                        "url",
                    ]
                ),
            }

            try:
                response = await self._client.get("/paper/search", params=params)
                response.raise_for_status()
                payload = response.json()
            except httpx.HTTPStatusError as exc:
                raise RuntimeError(f"Semantic Scholar search failed with status {exc.response.status_code}") from exc
            except httpx.HTTPError as exc:
                raise RuntimeError(f"Semantic Scholar request failed: {exc}") from exc
            except ValueError as exc:
                raise RuntimeError("Semantic Scholar search returned invalid JSON") from exc

            for item in payload.get("data", []):
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

        title = clean_text(item.get("title"))
        venue = clean_text(item.get("venue"))
        abstract = clean_text(item.get("abstract"))
        publication_types = item.get("publicationTypes")
        type_text = " ".join(publication_types) if isinstance(publication_types, list) else clean_text(publication_types)
        conference = detect_conference_series(title, venue, abstract, type_text, allowed_series=allowed_series)
        if conference is None:
            return None
        if not (
            looks_like_conference_record(title, venue, abstract, allowed_series=allowed_series)
            or "conference" in type_text.lower()
        ):
            return None

        publication_year = item.get("year")
        if not keep_if_recent(publication_year if isinstance(publication_year, int) else None, year_from=year_from):
            return None

        source_id = clean_text(item.get("paperId")) or clean_text((item.get("externalIds") or {}).get("CorpusId"))
        if not source_id or not title:
            return None

        authors = [
            clean_text(author.get("name"))
            for author in item.get("authors", [])
            if isinstance(author, dict) and clean_text(author.get("name"))
        ]
        doi = clean_text((item.get("externalIds") or {}).get("DOI")) or None

        return ConferenceAbstract(
            source=self.name,
            source_id=source_id,
            title=title,
            authors=authors,
            conference_name=venue or conference,
            conference_series=conference,
            presentation_type=infer_presentation_type(title, venue, abstract, type_text),
            abstract_number=extract_abstract_number(title, abstract),
            publication_year=publication_year if isinstance(publication_year, int) else None,
            publication_date=None,
            abstract=abstract,
            doi=doi,
            url=clean_text(item.get("url")) or None,
            journal=venue or None,
        )
