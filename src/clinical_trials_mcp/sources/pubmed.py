from __future__ import annotations

import os

import httpx

from clinical_trials_mcp.models import Publication
from clinical_trials_mcp.sources.base import BaseSource

BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


class PubMedSource(BaseSource):
    """PubMed E-utilities data source."""

    name = "pubmed"

    async def initialize(self) -> None:
        self._client = httpx.AsyncClient(base_url=BASE_URL, timeout=30.0)
        self._api_key = os.getenv("PUBMED_API_KEY")
        self._email = os.getenv("PUBMED_EMAIL", "clinical-trials-mcp@example.com")

    async def close(self) -> None:
        await self._client.aclose()

    async def search_publications(
        self,
        query: str,
        max_results: int = 10,
    ) -> list[Publication]:
        # TODO: Implement esearch + efetch two-step flow
        raise NotImplementedError
