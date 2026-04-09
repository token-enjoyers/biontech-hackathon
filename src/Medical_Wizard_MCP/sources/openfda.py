from __future__ import annotations

import logging

import httpx

from Medical_Wizard_MCP.models import TrialSummary
from Medical_Wizard_MCP.sources.base import BaseSource

logger = logging.getLogger(__name__)

BASE_URL = "https://api.fda.gov"

_LUCENE_SPECIAL = set(r'+-&|!(){}[]^"~*?:\/')


def _escape_lucene(value: str) -> str:
    """Escape Lucene special characters for safe query interpolation."""
    return "".join(f"\\{c}" if c in _LUCENE_SPECIAL else c for c in value)


def _build_search_query(
    condition: str,
    sponsor: str | None = None,
    intervention: str | None = None,
) -> str:
    """Build an OpenFDA Lucene query string.

    Uses drug/label.json fields:
      - indications_and_usage: free-text condition/indication field
      - openfda.manufacturer_name: sponsor filter
      - openfda.substance_name: intervention filter

    phase and status are not applicable to FDA drug labels and are ignored.
    """
    clauses: list[str] = [f"indications_and_usage:{_escape_lucene(condition)}"]

    if sponsor:
        clauses.append(f'openfda.manufacturer_name:"{_escape_lucene(sponsor)}"')

    if intervention:
        clauses.append(f'openfda.substance_name:"{_escape_lucene(intervention)}"')

    return " AND ".join(clauses)


def _first_text(label: dict, field: str) -> str | None:
    """Return the first string from a label list field, or None if absent."""
    values = label.get(field, [])
    return values[0] if values else None


def _map_label_to_summary(label: dict) -> TrialSummary | None:
    """Map an OpenFDA drug label entry to a TrialSummary."""
    openfda = label.get("openfda", {})

    app_numbers = openfda.get("application_number", [])
    brand_names = openfda.get("brand_name", [])
    generic_names = openfda.get("generic_name", [])
    manufacturer = openfda.get("manufacturer_name", [])
    substances = openfda.get("substance_name", [])
    routes = openfda.get("route", [])
    product_types = openfda.get("product_type", [])

    identifier = app_numbers[0] if app_numbers else None
    if not identifier:
        return None

    title_parts = brand_names or generic_names or [identifier]
    brief_title = f"FDA {identifier}: {', '.join(title_parts[:3])}"

    return TrialSummary(
        source="openfda",
        nct_id=f"FDA:{identifier}",
        brief_title=brief_title,
        phase=None,
        overall_status="Approved",
        lead_sponsor=manufacturer[0] if manufacturer else "Unknown",
        interventions=list(substances[:5]),
        primary_outcomes=[],
        enrollment_count=None,
        route=list(routes),
        product_type=product_types[0] if product_types else None,
        mechanism_of_action=_first_text(label, "mechanism_of_action"),
        pharmacodynamics=_first_text(label, "pharmacodynamics"),
        pharmacokinetics=_first_text(label, "pharmacokinetics"),
        clinical_pharmacology=_first_text(label, "clinical_pharmacology"),
        clinical_studies_summary=_first_text(label, "clinical_studies"),
        dosage_and_administration=_first_text(label, "dosage_and_administration"),
        dosage_forms_and_strengths=_first_text(label, "dosage_forms_and_strengths"),
        warnings=_first_text(label, "warnings_and_cautions"),
        adverse_reactions=_first_text(label, "adverse_reactions"),
        contraindications=_first_text(label, "contraindications"),
        drug_interactions=_first_text(label, "drug_interactions"),
    )


class OpenFDASource(BaseSource):
    """OpenFDA API data source.

    Searches FDA drug labels (drug/label.json) by indication/condition.
    Supports search_trials only; other methods fall back to default no-ops.
    """

    name = "openfda"

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    async def initialize(self) -> None:
        self._client = httpx.AsyncClient(base_url=BASE_URL, timeout=30.0)

    async def close(self) -> None:
        if self._client is not None:
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
        if self._client is None:
            logger.warning("OpenFDA source not initialized, skipping")
            return []

        search_query = _build_search_query(
            condition=condition,
            sponsor=sponsor,
            intervention=intervention,
        )

        params: dict[str, str | int] = {
            "search": search_query,
            "limit": min(max_results, 100),
        }

        try:
            response = await self._client.get("/drug/label.json", params=params)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return []
            logger.error("OpenFDA API error %s for query: %s", exc.response.status_code, search_query)
            return []
        except httpx.RequestError:
            logger.exception("OpenFDA request failed")
            return []

        try:
            data = response.json()
        except ValueError:
            logger.error("OpenFDA returned non-JSON response")
            return []

        results: list[TrialSummary] = []
        for label in data.get("results", []):
            summary = _map_label_to_summary(label)
            if summary is not None:
                results.append(summary)

        return results[:max_results]
