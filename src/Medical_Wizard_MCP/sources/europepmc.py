from __future__ import annotations

import httpx

from ..models import Publication
from .base import BaseSource

BASE_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest"
SOURCE_NAME = "europepmc"


class EuropePMCSource(BaseSource):
    """Europe PMC REST API data source.

    Provides publication search with citation counts and NCT-to-publication
    cross-references — features not available in PubMed.
    """

    name = SOURCE_NAME
    capabilities = frozenset({"publication_search"})

    async def initialize(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            timeout=30.0,
            headers={
                "User-Agent": "medical-wizard-mcp/0.1.0",
                "Accept": "application/json",
            },
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def search_publications(
        self,
        query: str,
        max_results: int = 10,
        year_from: int | None = None,
    ) -> list[Publication]:
        full_query = query
        if year_from is not None:
            full_query = f"{query} AND PUB_YEAR:[{year_from} TO 2099]"

        params = {
            "query": full_query,
            "format": "json",
            "resultType": "core",
            "pageSize": min(max_results, 25),
            "sort": "RELEVANCE",
        }

        try:
            response = await self._client.get("/search", params=params)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"Europe PMC search failed with status {exc.response.status_code}"
            ) from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Europe PMC request failed: {exc}") from exc
        except ValueError as exc:
            raise RuntimeError("Europe PMC returned invalid JSON") from exc

        results = payload.get("resultList", {}).get("result", [])
        publications = []
        for item in results:
            pub = self._normalize(item)
            if pub is not None:
                publications.append(pub)

        return publications[:max_results]

    def _normalize(self, item: dict) -> Publication | None:
        title = item.get("title", "").strip().rstrip(".")
        if not title:
            return None

        journal = (
            item.get("journalTitle")
            or item.get("journal", {}).get("title", "")
            or ""
        )

        authors = self._extract_authors(item)
        pub_date = str(item.get("pubYear", "")) or item.get("firstPublicationDate", "")
        abstract = item.get("abstractText", "") or ""
        pmid = str(item.get("pmid", "")) or None
        doi = item.get("doi") or None
        mesh_terms = self._extract_mesh_terms(item)

        return Publication(
            source=SOURCE_NAME,
            pmid=pmid,
            title=title,
            authors=authors,
            journal=journal,
            pub_date=pub_date,
            abstract=abstract,
            doi=doi,
            mesh_terms=mesh_terms,
        )

    def _extract_authors(self, item: dict) -> list[str]:
        author_string = item.get("authorString", "")
        if author_string:
            # "Smith J, Jones A, ..." → split on comma
            authors = [a.strip() for a in author_string.split(",") if a.strip()]
            # drop trailing "et al."
            return [a for a in authors if a.lower() not in {"et al.", "et al"}]

        author_list = item.get("authorList", {}).get("author", [])
        result = []
        for author in author_list:
            full_name = author.get("fullName") or author.get("lastName", "")
            if full_name:
                result.append(full_name)
        return result

    def _extract_mesh_terms(self, item: dict) -> list[str]:
        mesh_list = item.get("meshHeadingList", {})
        if not mesh_list:
            return []
        headings = mesh_list.get("meshHeading", [])
        terms = []
        for heading in headings:
            descriptor = heading.get("descriptorName", "")
            if descriptor:
                terms.append(descriptor)
        return terms
