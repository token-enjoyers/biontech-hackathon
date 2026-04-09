from __future__ import annotations

import asyncio
import json
import os
import shutil
from typing import Any
from urllib.parse import urlencode

import httpx

from ..models import TrialDetail, TrialSummary, TrialTimeline
from .base import BaseSource

BASE_URL = "https://clinicaltrials.gov/api/v2"
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/123.0.0.0 Safari/537.36"
)


class ClinicalTrialsSource(BaseSource):
    """ClinicalTrials.gov API v2 data source."""

    name = "clinicaltrials_gov"
    capabilities = frozenset({"trial_search", "trial_details", "trial_timelines"})

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._prefer_curl = self._env_prefers_curl()

    async def initialize(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            timeout=30.0,
            follow_redirects=True,
            headers=self._base_headers(),
        )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    def _base_headers(self) -> dict[str, str]:
        return {
            "User-Agent": os.getenv("CLINICALTRIALS_USER_AGENT", "medical-wizard-mcp/0.1.0"),
            "Accept": "application/json, text/plain, */*",
        }

    def _env_prefers_curl(self) -> bool:
        raw = os.getenv("CLINICALTRIALS_PREFER_CURL")
        if raw is None:
            # ClinicalTrials.gov currently blocks httpx consistently in this environment,
            # while curl succeeds against the same API and query parameters.
            return True
        return raw.strip().lower() not in {"0", "false", "no", "off"}

    def _browser_headers(self, params: dict[str, Any]) -> dict[str, str]:
        referer_query = {}
        if params.get("query.cond"):
            referer_query["cond"] = params["query.cond"]
        if params.get("query.term"):
            referer_query["term"] = params["query.term"]
        referer = "https://clinicaltrials.gov/search"
        if referer_query:
            referer = f"{referer}?{urlencode(referer_query)}"

        return {
            "User-Agent": os.getenv("CLINICALTRIALS_BROWSER_USER_AGENT", BROWSER_USER_AGENT),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": referer,
        }

    def _apply_phase_filter(self, params: dict[str, Any], phase: str) -> None:
        normalized_phase = phase.upper().replace(" ", "")
        phase_filter = f"AREA[Phase]{normalized_phase}"
        existing_filter = params.get("filter.advanced")
        if existing_filter:
            params["filter.advanced"] = f"({existing_filter}) AND ({phase_filter})"
        else:
            params["filter.advanced"] = phase_filter

    async def _get_json_via_curl(
        self,
        path: str,
        *,
        params: dict[str, Any],
        stage: str,
        allow_not_found: bool = False,
    ) -> dict[str, Any] | None:
        curl_path = shutil.which("curl")
        if not curl_path:
            raise RuntimeError(
                f"ClinicalTrials.gov blocked {stage} with status 403 and curl fallback is unavailable. "
                "Install curl or run from an environment where the Python HTTP client is not blocked."
            )

        url = f"{BASE_URL}{path}"
        if params:
            url = f"{url}?{urlencode(params)}"

        headers = self._browser_headers(params)
        process = await asyncio.create_subprocess_exec(
            curl_path,
            "-sS",
            "-L",
            "--compressed",
            "-H",
            f"User-Agent: {headers['User-Agent']}",
            "-H",
            f"Accept: {headers['Accept']}",
            "-H",
            f"Accept-Language: {headers['Accept-Language']}",
            "-H",
            f"Referer: {headers['Referer']}",
            "-w",
            "\n%{http_code}",
            url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=35)

        if process.returncode != 0:
            error = stderr.decode().strip() or f"curl exited with status {process.returncode}"
            raise RuntimeError(f"ClinicalTrials.gov {stage} curl fallback failed: {error}")

        body, separator, status_line = stdout.rpartition(b"\n")
        if not separator:
            raise RuntimeError(
                f"ClinicalTrials.gov {stage} curl fallback returned an unreadable response"
            )

        try:
            http_status = int(status_line.decode().strip())
        except ValueError as exc:
            raise RuntimeError(
                f"ClinicalTrials.gov {stage} curl fallback returned an unreadable status code"
            ) from exc

        if http_status == 404 and allow_not_found:
            return None
        if http_status >= 400:
            raise RuntimeError(
                f"ClinicalTrials.gov {stage} curl fallback failed with status {http_status}"
            )

        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            snippet = body.decode(errors="replace").strip()[:200] or "empty response"
            raise RuntimeError(
                f"ClinicalTrials.gov {stage} curl fallback returned invalid JSON: {snippet}"
            ) from exc

        if not isinstance(payload, dict):
            raise RuntimeError(
                f"ClinicalTrials.gov {stage} curl fallback returned unexpected payload shape"
            )
        return payload

    async def _get_json(
        self,
        path: str,
        *,
        params: dict[str, Any],
        stage: str,
        allow_not_found: bool = False,
    ) -> dict[str, Any] | None:
        if self._prefer_curl:
            return await self._get_json_via_curl(
                path,
                params=params,
                stage=stage,
                allow_not_found=allow_not_found,
            )

        if self._client is None:
            raise RuntimeError("ClinicalTrials.gov client is not initialized")

        response = await self._client.get(path, params=params)
        if response.status_code == 403:
            # ClinicalTrials.gov blocks httpx in some environments even with browser headers.
            # Once we observe that, switch the process to curl to avoid repeated 403s and log spam.
            self._prefer_curl = True
            return await self._get_json_via_curl(
                path,
                params=params,
                stage=stage,
                allow_not_found=allow_not_found,
            )

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404 and allow_not_found:
                return None
            raise RuntimeError(
                f"ClinicalTrials.gov {stage} failed with status {exc.response.status_code}"
            ) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError(f"ClinicalTrials.gov {stage} returned invalid JSON") from exc

        if not isinstance(payload, dict):
            raise RuntimeError(f"ClinicalTrials.gov {stage} returned unexpected payload shape")
        return payload

    # ------------------------------------------------------------------
    # Normalization helpers: map nested API v2 JSON → flat model dicts
    # ------------------------------------------------------------------

    def _phase_str(self, design: dict[str, Any]) -> str | None:
        phases = design.get("phases", [])
        if not phases:
            return None
        return "/".join(p.replace("PHASE", "Phase ") for p in phases)

    async def _fetch_studies(self, params: dict[str, Any], limit: int) -> list[dict[str, Any]]:
        studies: list[dict[str, Any]] = []
        page_token: str | None = None

        while len(studies) < limit:
            request_params = dict(params)
            request_params["pageSize"] = min(max(limit - len(studies), 1), 100)
            if page_token:
                request_params["pageToken"] = page_token

            data = await self._get_json(
                "/studies",
                params=request_params,
                stage="search_trials",
            )

            batch = data.get("studies", [])
            if not batch:
                break

            studies.extend(batch)
            page_token = data.get("nextPageToken")
            if not page_token:
                break

        return studies[:limit]

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
            "start_date": status.get("startDateStruct", {}).get("date"),
            "primary_completion_date": status.get("primaryCompletionDateStruct", {}).get("date"),
            "completion_date": status.get("completionDateStruct", {}).get("date"),
        }

    def _normalize_detail(self, study: dict[str, Any]) -> dict[str, Any]:
        proto = study.get("protocolSection", {})
        ident = proto.get("identificationModule", {})
        eligibility = proto.get("eligibilityModule", {})
        design = proto.get("designModule", {})
        conditions_mod = proto.get("conditionsModule", {})
        arms_mod = proto.get("armsInterventionsModule", {})
        outcomes = proto.get("outcomesModule", {})
        contacts_locations = proto.get("contactsLocationsModule", {})
        locations = contacts_locations.get("locations", [])
        overall_officials = contacts_locations.get("overallOfficials", [])

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
            "why_stopped": proto.get("statusModule", {}).get("whyStopped"),
            "facility_names": [
                location.get("facility", "")
                for location in locations
                if isinstance(location, dict) and location.get("facility")
            ],
            "facility_cities": [
                location.get("city", "")
                for location in locations
                if isinstance(location, dict) and location.get("city")
            ],
            "facility_states": [
                location.get("state", "")
                for location in locations
                if isinstance(location, dict) and location.get("state")
            ],
            "location_countries": [
                location.get("country", "")
                for location in locations
                if isinstance(location, dict) and location.get("country")
            ],
            "overall_officials": [
                official.get("name", "")
                for official in overall_officials
                if isinstance(official, dict) and official.get("name")
            ],
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
            "overall_status": status.get("overallStatus", ""),
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
            "format": "json",
        }

        if phase:
            self._apply_phase_filter(params, phase)
        if status:
            params["filter.overallStatus"] = status.upper()
        if sponsor:
            params["query.term"] = sponsor
        if intervention:
            params["query.intr"] = intervention

        return [
            TrialSummary(**self._normalize_summary(study))
            for study in await self._fetch_studies(params, max_results)
        ]

    async def get_trial_details(self, nct_id: str) -> TrialDetail | None:
        study = await self._get_json(
            f"/studies/{nct_id}",
            params={"format": "json"},
            stage="get_trial_details",
            allow_not_found=True,
        )
        if study is None:
            return None
        return TrialDetail(**self._normalize_detail(study))

    async def get_trial_timelines(
        self,
        condition: str,
        sponsor: str | None = None,
        phase: str | None = None,
        status: str | None = None,
        max_results: int = 15,
    ) -> list[TrialTimeline]:
        params: dict[str, Any] = {
            "query.cond": condition,
            "format": "json",
        }

        if sponsor:
            params["query.term"] = sponsor
        if phase:
            self._apply_phase_filter(params, phase)
        if status:
            params["filter.overallStatus"] = status.upper()

        return [
            TrialTimeline(**self._normalize_timeline(study))
            for study in await self._fetch_studies(params, max_results)
        ]
