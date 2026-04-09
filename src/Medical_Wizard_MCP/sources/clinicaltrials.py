from __future__ import annotations

from typing import Any

import httpx

from ..models import TrialDetail, TrialSummary, TrialTimeline
from .base import BaseSource

BASE_URL = "https://clinicaltrials.gov/api/v2"


class ClinicalTrialsSource(BaseSource):
    """ClinicalTrials.gov API v2 data source."""

    name = "clinicaltrials_gov"

    async def initialize(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            timeout=30.0,
            headers={"User-Agent": "clinical-trials-mcp/0.1.0"},
        )

    async def close(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------
    # Normalization helpers: map nested API v2 JSON → flat model dicts
    # ------------------------------------------------------------------

    def _phase_str(self, design: dict[str, Any]) -> str | None:
        phases = design.get("phases", [])
        if not phases:
            return None
        return "/".join(p.replace("PHASE", "Phase ") for p in phases)

    def _normalize_summary(self, study: dict[str, Any]) -> dict[str, Any]:
        proto = study.get("protocolSection", {})
        ident = proto.get("identificationModule", {})
        status = proto.get("statusModule", {})
        design = proto.get("designModule", {})
        sponsor = proto.get("sponsorCollaboratorsModule", {})
        interventions_mod = proto.get("interventionsModule", {})
        outcomes = proto.get("outcomesModule", {})

        return {
            "source": self.name,
            "nct_id": ident.get("nctId", ""),
            "brief_title": ident.get("briefTitle", ""),
            "phase": self._phase_str(design),
            "overall_status": status.get("overallStatus", ""),
            "lead_sponsor": sponsor.get("leadSponsor", {}).get("name", ""),
            "interventions": [
                i.get("name", "") for i in interventions_mod.get("interventions", [])
            ],
            "primary_outcomes": [
                o.get("measure", "") for o in outcomes.get("primaryOutcomes", [])
            ],
            "enrollment_count": design.get("enrollmentInfo", {}).get("count"),
        }

    def _normalize_detail(self, study: dict[str, Any]) -> dict[str, Any]:
        proto = study.get("protocolSection", {})
        ident = proto.get("identificationModule", {})
        eligibility = proto.get("eligibilityModule", {})
        design = proto.get("designModule", {})
        conditions_mod = proto.get("conditionsModule", {})
        arms_mod = proto.get("armsInterventionsModule", {})
        outcomes = proto.get("outcomesModule", {})

        data = self._normalize_summary(study)
        data.update({
            "official_title": ident.get("officialTitle"),
            "eligibility_criteria": eligibility.get("eligibilityCriteria"),
            "arms": [a.get("label", "") for a in arms_mod.get("armGroups", [])],
            "secondary_outcomes": [
                o.get("measure", "") for o in outcomes.get("secondaryOutcomes", [])
            ],
            "study_type": design.get("studyType"),
            "conditions": conditions_mod.get("conditions", []),
        })
        return data

    def _normalize_timeline(self, study: dict[str, Any]) -> dict[str, Any]:
        proto = study.get("protocolSection", {})
        ident = proto.get("identificationModule", {})
        status = proto.get("statusModule", {})
        design = proto.get("designModule", {})
        sponsor = proto.get("sponsorCollaboratorsModule", {})

        return {
            "source": self.name,
            "nct_id": ident.get("nctId", ""),
            "brief_title": ident.get("briefTitle", ""),
            "phase": self._phase_str(design),
            "lead_sponsor": sponsor.get("leadSponsor", {}).get("name", ""),
            "start_date": status.get("startDateStruct", {}).get("date"),
            "primary_completion_date": status.get("primaryCompletionDateStruct", {}).get("date"),
            "completion_date": status.get("completionDateStruct", {}).get("date"),
            "enrollment_count": design.get("enrollmentInfo", {}).get("count"),
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def search_trials(
        self,
        condition: str,
        phase: str | None = None,
        status: str | None = None,
        sponsor: str | None = None,
        intervention: str | None = None,
        max_results: int = 10,
    ) -> list[TrialSummary]:
        params: dict[str, Any] = {
            "query.cond": condition,
            "pageSize": max_results,
            "format": "json",
        }

        if phase:
            params["filter.phase"] = phase.upper().replace(" ", "")
        if status:
            params["filter.overallStatus"] = status.upper()
        if sponsor:
            params["query.term"] = sponsor
        if intervention:
            params["query.intr"] = intervention

        response = await self._client.get("/studies", params=params)
        response.raise_for_status()
        data = response.json()

        return [
            TrialSummary(**self._normalize_summary(study))
            for study in data.get("studies", [])
        ]

    async def get_trial_details(self, nct_id: str) -> TrialDetail | None:
        response = await self._client.get(f"/studies/{nct_id}")

        if response.status_code == 404:
            return None

        response.raise_for_status()
        study = response.json()

        return TrialDetail(**self._normalize_detail(study))

    async def get_trial_timelines(
        self,
        condition: str,
        sponsor: str | None = None,
        max_results: int = 15,
    ) -> list[TrialTimeline]:
        params: dict[str, Any] = {
            "query.cond": condition,
            "pageSize": max_results,
            "format": "json",
        }

        if sponsor:
            params["query.term"] = sponsor

        response = await self._client.get("/studies", params=params)
        response.raise_for_status()
        data = response.json()

        return [
            TrialTimeline(**self._normalize_timeline(study))
            for study in data.get("studies", [])
        ]
