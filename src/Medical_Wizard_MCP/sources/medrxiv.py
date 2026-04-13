from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

from ..models import Publication
from ._network import SourceTimeoutError, build_http_timeout
from .base import BaseSource

BASE_URL = "https://api.medrxiv.org"
SOURCE_NAME = "medrxiv"
DEFAULT_LOOKBACK_DAYS = 365
PAGE_SIZE = 100
MAX_SCAN_PAGES = 10


def utc_today() -> date:
    return datetime.now(UTC).date()


class MedRxivSource(BaseSource):
    """medRxiv API source for recent preprints."""

    name = SOURCE_NAME
    capabilities = frozenset({"preprint_search"})

    async def initialize(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            timeout=build_http_timeout(),
            headers={"User-Agent": "clinical-trials-mcp/0.1.0"},
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def search_preprints(
        self,
        query: str,
        max_results: int = 10,
        year_from: int | None = None,
    ) -> list[Publication]:
        max_results = max(1, max_results)
        end_date = utc_today()
        start_date = date(year_from, 1, 1) if year_from else end_date - timedelta(days=DEFAULT_LOOKBACK_DAYS)

        results: list[Publication] = []
        cursor = 0

        for _ in range(MAX_SCAN_PAGES):
            payload = await self._fetch_details_page(start_date, end_date, cursor)
            collection = payload.get("collection", [])
            if not isinstance(collection, list) or not collection:
                break

            for record in collection:
                publication = self._normalize_record(record)
                if publication is None or not self._matches_query(record, query):
                    continue
                results.append(publication)
                if len(results) >= max_results:
                    return results[:max_results]

            next_cursor = cursor + len(collection)
            total_count = self._extract_total(payload)
            if total_count is not None and next_cursor >= total_count:
                break
            cursor = next_cursor

        return results[:max_results]

    async def _fetch_details_page(
        self,
        start_date: date,
        end_date: date,
        cursor: int,
    ) -> dict[str, Any]:
        path = f"/details/medrxiv/{start_date.isoformat()}/{end_date.isoformat()}/{cursor}/json"
        try:
            response = await self._client.get(path)
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException as exc:
            raise SourceTimeoutError("medRxiv details timed out") from exc
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"medRxiv details failed with status {exc.response.status_code}"
            ) from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(f"medRxiv details request failed: {exc}") from exc
        except ValueError as exc:
            raise RuntimeError("medRxiv details returned invalid JSON") from exc

        if not isinstance(payload, dict):
            raise RuntimeError("medRxiv details returned unexpected payload shape")
        return payload

    def _normalize_record(self, record: Any) -> Publication | None:
        if not isinstance(record, dict):
            return None

        if self._is_published(record.get("published")):
            return None

        title = self._clean_text(record.get("title"))
        if not title:
            return None

        category = self._clean_text(record.get("category"))
        return Publication(
            source=SOURCE_NAME,
            pmid=None,
            title=title,
            authors=self._parse_authors(record.get("authors")),
            journal="medRxiv",
            pub_date=self._clean_text(record.get("date")),
            abstract=self._clean_text(record.get("abstract")),
            doi=self._clean_text(record.get("doi")) or None,
            mesh_terms=[category] if category else [],
        )

    def _matches_query(self, record: Any, query: str) -> bool:
        if not isinstance(record, dict):
            return False

        haystack = " ".join(
            self._clean_text(record.get(field))
            for field in ("title", "abstract", "category", "authors")
        ).lower()
        normalized_query = self._clean_text(query).lower()
        if normalized_query and normalized_query in haystack:
            return True

        tokens = [
            token
            for token in re.split(r"[^a-z0-9]+", normalized_query)
            if len(token) >= 3
        ]
        if not tokens:
            return bool(normalized_query)
        return all(token in haystack for token in dict.fromkeys(tokens))

    def _extract_total(self, payload: dict[str, Any]) -> int | None:
        messages = payload.get("messages")
        if not isinstance(messages, list) or not messages:
            return None
        first_message = messages[0]
        if not isinstance(first_message, dict):
            return None
        raw_total = first_message.get("total")
        try:
            return int(raw_total)
        except (TypeError, ValueError):
            return None

    def _parse_authors(self, raw_authors: Any) -> list[str]:
        authors_text = self._clean_text(raw_authors)
        if not authors_text:
            return []
        separator = ";" if ";" in authors_text else ","
        return [author.strip() for author in authors_text.split(separator) if author.strip()]

    def _is_published(self, published_field: Any) -> bool:
        published_value = self._clean_text(published_field).lower()
        return published_value not in {"", "na", "n/a", "none", "null"}

    def _clean_text(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return " ".join(value.split())
        return str(value).strip()
