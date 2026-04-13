from __future__ import annotations

from typing import Any

import httpx

from ..models import ConferenceAbstract
from ._network import SourceTimeoutError, build_http_timeout
from ._conference_utils import (
    clean_text,
    conference_query_variants,
    detect_conference_series,
    extract_abstract_number,
    infer_presentation_type,
    keep_if_recent,
    looks_like_conference_record,
    normalize_conference_series,
    normalize_date,
    split_author_string,
    year_from_date,
)
from .base import BaseSource

BASE_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest"


class EuropePMCConferenceSource(BaseSource):
    name = "europe_pmc"
    capabilities = frozenset({"conference_abstract_search"})

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    async def initialize(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            timeout=build_http_timeout(),
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
            raise RuntimeError("Europe PMC source not initialized.")

        allowed_series = normalize_conference_series(conference_series)
        results: list[ConferenceAbstract] = []
        seen_ids: set[str] = set()
        for variant in conference_query_variants(query, allowed_series):
            params = {
                "query": variant,
                "format": "json",
                "pageSize": min(max_results * 5, 50),
                "sort": "RELEVANCE",
                "resultType": "core",
            }

            try:
                response = await self._client.get("/search", params=params)
                response.raise_for_status()
                payload = response.json()
            except httpx.TimeoutException as exc:
                raise SourceTimeoutError("Europe PMC search timed out") from exc
            except httpx.HTTPStatusError as exc:
                raise RuntimeError(f"Europe PMC search failed with status {exc.response.status_code}") from exc
            except httpx.HTTPError as exc:
                raise RuntimeError(f"Europe PMC request failed: {exc}") from exc
            except ValueError as exc:
                raise RuntimeError("Europe PMC search returned invalid JSON") from exc

            for item in ((payload.get("resultList") or {}).get("result") or []):
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
        journal = clean_text(item.get("journalTitle"))
        abstract = clean_text(item.get("abstractText"))
        conference = detect_conference_series(title, journal, abstract, allowed_series=allowed_series)
        if conference is None or not looks_like_conference_record(title, journal, abstract, allowed_series=allowed_series):
            return None

        publication_date = normalize_date(item.get("firstPublicationDate")) or normalize_date(item.get("pubYear"))
        publication_year = year_from_date(publication_date) or (int(item["pubYear"]) if str(item.get("pubYear", "")).isdigit() else None)
        if not keep_if_recent(publication_year, year_from=year_from):
            return None

        source_id = clean_text(item.get("id")) or clean_text(item.get("pmid")) or clean_text(item.get("doi"))
        if not source_id or not title:
            return None

        doi = clean_text(item.get("doi")) or None
        url = clean_text(item.get("fullTextUrl")) or None
        if not url and clean_text(item.get("pmid")):
            url = f"https://europepmc.org/article/MED/{clean_text(item.get('pmid'))}"

        return ConferenceAbstract(
            source=self.name,
            source_id=source_id,
            title=title,
            authors=split_author_string(item.get("authorString")),
            conference_name=journal or conference,
            conference_series=conference,
            presentation_type=infer_presentation_type(title, journal, abstract),
            abstract_number=extract_abstract_number(title, abstract),
            publication_year=publication_year,
            publication_date=publication_date,
            abstract=abstract,
            doi=doi,
            url=url,
            journal=journal or None,
        )
