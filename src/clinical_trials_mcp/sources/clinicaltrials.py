from __future__ import annotations

import httpx

from clinical_trials_mcp.models import TrialDetail, TrialSummary, TrialTimeline
from clinical_trials_mcp.sources.base import BaseSource

BASE_URL = "https://clinicaltrials.gov/api/v2"


class ClinicalTrialsSource(BaseSource):
    """ClinicalTrials.gov API v2 data source."""

    name = "clinicaltrials_gov"

    async def initialize(self) -> None:
        self._client = httpx.AsyncClient(base_url=BASE_URL, timeout=30.0)

    async def close(self) -> None:
        await self._client.aclose()

    async def search_trials(
        self,
        condition: str,
        phase: str | None = None,
        status: str | None = None,
        sponsor: str | None = None,
        intervention: str | None = None,
        max_results: int = 10,
    ) -> list[TrialSummary]:
        # TODO: Implement API call + response minimization
        raise NotImplementedError

    async def get_trial_details(self, nct_id: str) -> TrialDetail | None:
        # TODO: Implement GET /studies/{nct_id}
        raise NotImplementedError

    async def get_trial_timelines(
        self,
        condition: str,
        sponsor: str | None = None,
        max_results: int = 15,
    ) -> list[TrialTimeline]:
        # TODO: Implement timeline data extraction
        raise NotImplementedError
