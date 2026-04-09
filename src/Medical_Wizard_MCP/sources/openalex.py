from __future__ import annotations

from typing import Any

import httpx

from ..models import ConferenceAbstract
from ._conference_utils import (
    clean_text,
    conference_query_variants,
    detect_conference_series,
    extract_abstract_number,
    first_text,
    infer_presentation_type,
    keep_if_recent,
    looks_like_conference_record,
    normalize_conference_series,
    normalize_date,
    normalize_doi,
    year_from_date,
)
from .base import BaseSource

BASE_URL = "https://api.openalex.org"


def _rebuild_abstract(index: Any) -> str:
    if not isinstance(index, dict) or not index:
        return ""

    positions: dict[int, str] = {}
    for token, raw_positions in index.items():
        if not isinstance(token, str) or not isinstance(raw_positions, list):
            continue
        for raw_position in raw_positions:
            if isinstance(raw_position, int):
                positions[raw_position] = token

    if not positions:
        return ""

    return " ".join(positions[position] for position in sorted(positions))


class OpenAlexConferenceSource(BaseSource):
    name = "openalex"
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
            raise RuntimeError("OpenAlex source not initialized.")

        allowed_series = normalize_conference_series(conference_series)
        results: list[ConferenceAbstract] = []
        seen_ids: set[str] = set()
        for variant in conference_query_variants(query, allowed_series):
            params = {
                "search": variant,
                "per-page": min(max_results * 5, 50),
                "mailto": "medical-wizard-mcp@example.com",
            }
            if year_from is not None:
                params["filter"] = f"from_publication_date:{int(year_from)}-01-01"

            try:
                response = await self._client.get("/works", params=params)
                response.raise_for_status()
                payload = response.json()
            except httpx.HTTPStatusError as exc:
                raise RuntimeError(f"OpenAlex works search failed with status {exc.response.status_code}") from exc
            except httpx.HTTPError as exc:
                raise RuntimeError(f"OpenAlex works request failed: {exc}") from exc
            except ValueError as exc:
                raise RuntimeError("OpenAlex works returned invalid JSON") from exc

            for item in payload.get("results", []):
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

        title = clean_text(item.get("display_name"))
        venue = clean_text(((item.get("primary_location") or {}).get("source") or {}).get("display_name"))
        abstract = clean_text(_rebuild_abstract(item.get("abstract_inverted_index")))
        conference = detect_conference_series(title, venue, abstract, allowed_series=allowed_series)
        if conference is None or not looks_like_conference_record(title, venue, abstract, allowed_series=allowed_series):
            return None

        publication_date = normalize_date(item.get("publication_date"))
        publication_year = item.get("publication_year")
        if not isinstance(publication_year, int):
            publication_year = year_from_date(publication_date)
        if not keep_if_recent(publication_year, year_from=year_from):
            return None

        authors = [
            clean_text(((authorship.get("author") or {}).get("display_name")))
            for authorship in item.get("authorships", [])
            if isinstance(authorship, dict)
        ]
        authors = [author for author in authors if author]
        doi = normalize_doi(item.get("doi"))
        source_id = clean_text(item.get("id")) or doi
        if not source_id or not title:
            return None

        url = clean_text(((item.get("primary_location") or {}).get("landing_page_url"))) or clean_text(item.get("id")) or None
        return ConferenceAbstract(
            source=self.name,
            source_id=source_id,
            title=title,
            authors=authors,
            conference_name=first_text([venue, conference]) or conference,
            conference_series=conference,
            presentation_type=infer_presentation_type(title, venue, abstract),
            abstract_number=extract_abstract_number(title, abstract),
            publication_year=publication_year,
            publication_date=publication_date,
            abstract=abstract,
            doi=doi,
            url=url,
            journal=venue or None,
        )
