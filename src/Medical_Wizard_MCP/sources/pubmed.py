from __future__ import annotations

import asyncio
import os
import xml.etree.ElementTree as ET
from typing import Any

import httpx

from ..models import Publication
from .base import BaseSource

BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
SOURCE_NAME = "pubmed"
RATE_LIMIT_DELAY = 0.4

MONTH_LOOKUP = {
    "jan": "01",
    "feb": "02",
    "mar": "03",
    "apr": "04",
    "may": "05",
    "jun": "06",
    "jul": "07",
    "aug": "08",
    "sep": "09",
    "sept": "09",
    "oct": "10",
    "nov": "11",
    "dec": "12",
}


class PubMedSource(BaseSource):
    """PubMed E-utilities data source."""

    name = SOURCE_NAME
    capabilities = frozenset({"publication_search"})

    async def initialize(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            timeout=30.0,
            headers={"User-Agent": "medical-wizard-mcp/0.1.0"},
        )
        self._api_key = os.getenv("PUBMED_API_KEY")
        self._email = os.getenv("PUBMED_EMAIL", "medical-wizard-mcp@example.com")

    async def close(self) -> None:
        await self._client.aclose()

    async def search(self, query: str, **kwargs: Any) -> list[dict]:
        max_results = max(1, int(kwargs.get("max_results", 20)))
        year_from = kwargs.get("year_from")

        params = {
            "db": "pubmed",
            "term": query,
            "retmax": max_results,
            "retmode": "json",
            "sort": "relevance",
            **self._base_params(),
        }
        if year_from is not None:
            params["mindate"] = f"{int(year_from)}/01/01"
            params["datetype"] = "pdat"

        try:
            response = await self._client.get("/esearch.fcgi", params=params)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"PubMed esearch failed with status {exc.response.status_code}"
            ) from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(f"PubMed esearch request failed: {exc}") from exc
        except ValueError as exc:
            raise RuntimeError("PubMed esearch returned invalid JSON") from exc

        pmids = payload.get("esearchresult", {}).get("idlist", [])
        if not pmids:
            return []

        await asyncio.sleep(RATE_LIMIT_DELAY)
        return await self._fetch_by_pmids(pmids)

    async def search_publications(
        self,
        query: str,
        max_results: int = 10,
        year_from: int | None = None,
    ) -> list[Publication]:
        results = await self.search(
            query,
            max_results=max_results,
            year_from=year_from,
        )
        return [Publication.model_validate(result) for result in results]

    async def _fetch_by_pmids(self, pmids: list[str]) -> list[dict]:
        if not pmids:
            return []

        params = {
            "db": "pubmed",
            "id": ",".join(pmids),
            "retmode": "xml",
            **self._base_params(),
        }

        try:
            response = await self._client.get("/efetch.fcgi", params=params)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"PubMed efetch failed with status {exc.response.status_code}"
            ) from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(f"PubMed efetch request failed: {exc}") from exc

        try:
            root = ET.fromstring(response.text)
        except ET.ParseError as exc:
            raise RuntimeError("PubMed efetch returned invalid XML") from exc

        normalized: dict[str, dict] = {}
        for article in root.findall(".//PubmedArticle"):
            publication = self._normalize_article(article)
            if publication is not None:
                normalized[publication["pmid"]] = publication

        return [normalized[pmid] for pmid in pmids if pmid in normalized]

    def _normalize_article(self, article: ET.Element) -> dict[str, Any] | None:
        medline = article.find("MedlineCitation")
        article_node = medline.find("Article") if medline is not None else None
        if medline is None or article_node is None:
            return None

        pmid = self._extract_text(medline.find("PMID"))
        title = self._extract_text(article_node.find("ArticleTitle"))
        if not pmid or not title:
            return None

        return {
            "source": SOURCE_NAME,
            "pmid": pmid,
            "title": title,
            "authors": self._extract_authors(article_node),
            "journal": self._extract_journal(article_node),
            "pub_date": self._extract_pub_date(article, article_node),
            "abstract": self._extract_abstract(article_node),
            "doi": self._extract_doi(article),
            "mesh_terms": self._extract_mesh_terms(medline),
        }

    def _base_params(self) -> dict[str, str]:
        params = {"tool": "medical-wizard-mcp"}
        if self._api_key:
            params["api_key"] = self._api_key
        if self._email:
            params["email"] = self._email
        return params

    def _extract_authors(self, article_node: ET.Element) -> list[str]:
        authors: list[str] = []
        for author in article_node.findall("AuthorList/Author"):
            collective_name = self._extract_text(author.find("CollectiveName"))
            if collective_name:
                authors.append(collective_name)
                continue

            fore_name = self._extract_text(author.find("ForeName"))
            last_name = self._extract_text(author.find("LastName"))
            initials = self._extract_text(author.find("Initials"))

            full_name = " ".join(part for part in [fore_name or initials, last_name] if part)
            if full_name:
                authors.append(full_name)
        return authors

    def _extract_journal(self, article_node: ET.Element) -> str:
        return self._extract_text(article_node.find("Journal/Title")) or self._extract_text(
            article_node.find("Journal/ISOAbbreviation")
        )

    def _extract_pub_date(self, article: ET.Element, article_node: ET.Element) -> str:
        article_date = article_node.find("ArticleDate")
        formatted_article_date = self._format_structured_date(article_date)
        if formatted_article_date:
            return formatted_article_date

        pub_date = article_node.find("Journal/JournalIssue/PubDate")
        formatted_pub_date = self._format_structured_date(pub_date)
        if formatted_pub_date:
            return formatted_pub_date

        fallback_date = article.find(".//PubMedPubDate[@PubStatus='pubmed']")
        return self._format_structured_date(fallback_date)

    def _extract_abstract(self, article_node: ET.Element) -> str:
        parts: list[str] = []
        for abstract_text in article_node.findall("Abstract/AbstractText"):
            text = self._extract_text(abstract_text)
            if not text:
                continue
            label = abstract_text.attrib.get("Label")
            if label:
                parts.append(f"{label}: {text}")
            else:
                parts.append(text)
        return "\n\n".join(parts)

    def _extract_doi(self, article: ET.Element) -> str | None:
        for node in article.findall(".//PubmedData/ArticleIdList/ArticleId"):
            if node.attrib.get("IdType") == "doi":
                doi = self._extract_text(node)
                if doi:
                    return doi
        return None

    def _extract_mesh_terms(self, medline: ET.Element) -> list[str]:
        terms: list[str] = []
        for mesh_heading in medline.findall("MeshHeadingList/MeshHeading"):
            descriptor = self._extract_text(mesh_heading.find("DescriptorName"))
            if descriptor:
                terms.append(descriptor)
        return terms

    def _format_structured_date(self, node: ET.Element | None) -> str:
        if node is None:
            return ""

        medline_date = self._extract_text(node.find("MedlineDate"))
        if medline_date:
            return medline_date

        year = self._extract_text(node.find("Year"))
        month = self._normalize_month(self._extract_text(node.find("Month")))
        day = self._extract_text(node.find("Day"))

        if not year:
            return ""
        if month and day:
            return f"{year}-{month}-{day.zfill(2)}"
        if month:
            return f"{year}-{month}"
        return year

    def _normalize_month(self, month: str) -> str:
        if not month:
            return ""
        stripped = month.strip()
        if stripped.isdigit():
            return stripped.zfill(2)
        return MONTH_LOOKUP.get(stripped[:4].lower(), "")

    def _extract_text(self, node: ET.Element | None) -> str:
        if node is None:
            return ""
        return " ".join(part.strip() for part in node.itertext() if part and part.strip())
