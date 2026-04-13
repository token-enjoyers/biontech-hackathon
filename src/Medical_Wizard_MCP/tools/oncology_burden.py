from __future__ import annotations

from typing import Any

from .._mcp import mcp
from ..sources import registry
from ._inputs import coalesce_indication
from ._responses import list_response

_SITE_ALIAS_MAP = {
    "breast cancer": "Breast",
    "breast tumour": "Breast",
    "breast tumor": "Breast",
    "lung cancer": "Lung",
    "lung tumour": "Lung",
    "lung tumor": "Lung",
    "brain cancer": "Central Nervous system",
    "brain tumour": "Central Nervous system",
    "brain tumor": "Central Nervous system",
    "colorectal cancer": "Colon, rectum, anus",
    "colon cancer": "Colon",
    "rectal cancer": "Rectum",
    "prostate cancer": "Prostate",
    "pancreatic cancer": "Pancreas",
    "pancreas cancer": "Pancreas",
    "leukemia": "Leukaemia",
}


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _normalize_site(value: str | None) -> str | None:
    cleaned = _clean_text(value)
    if cleaned is None:
        return None
    lowered = cleaned.casefold()
    alias = _SITE_ALIAS_MAP.get(lowered)
    if alias:
        return alias
    for suffix in (" cancer", " tumour", " tumor"):
        if lowered.endswith(suffix):
            trimmed = cleaned[: -len(suffix)].strip()
            if trimmed:
                return trimmed
    return cleaned


def _normalize_indicator(value: str | None) -> str | None:
    cleaned = _clean_text(value)
    if cleaned is None:
        return None
    lowered = cleaned.casefold()
    if lowered in {"mortality", "death", "deaths"}:
        return "Mortality"
    if lowered in {"incidence", "case", "cases", "new cases"}:
        return "Incidence"
    return cleaned


def _normalize_sex(value: str | None) -> str | None:
    cleaned = _clean_text(value)
    if cleaned is None:
        return None
    lowered = cleaned.casefold()
    if lowered in {"female", "women", "woman"}:
        return "Female"
    if lowered in {"male", "men", "man"}:
        return "Male"
    return cleaned


def _coerce_int(value: int | str | None, field_name: str) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer.")
    if isinstance(value, int):
        return value
    stripped = value.strip()
    if not stripped:
        return None
    return int(stripped)


@mcp.tool()
async def search_oncology_burden(
    site: str | None = None,
    indication: str | None = None,
    country: str | None = None,
    sex: str | None = None,
    indicator: str | None = None,
    year: int | str | None = None,
    age_min: int | str | None = None,
    age_max: int | str | None = None,
    max_results: int = 10,
) -> dict[str, Any]:
    """Structured oncology burden lookup from the configured BigQuery view.

Use this when you need country-level oncology burden rows such as deaths or cases by cancer entity, sex, year, or age band.

Avoid this when you need trial, publication, or approved-drug evidence rather than epidemiology-style burden data.

Returns a standardized list envelope with `_meta`, `count`, and `results`.
Each result row includes: dataset, study, registry, country, sex, site, indicator, geo_code, year, age_min, age_max, cases, population, source.

Args:
    site: Canonical cancer entity label to filter on.
    indication: Backward-compatible alias for `site`.
    country: Country filter.
    sex: Sex filter.
    indicator: Metric name such as Mortality.
    year: Exact year filter.
    age_min: Minimum lower bound for the returned age band.
    age_max: Maximum upper bound for the returned age band.
    max_results: Number of rows to return (default 10, max 100).
    """
    resolved_site = _normalize_site(coalesce_indication(indication=site, condition=indication))
    resolved_country = _clean_text(country)
    resolved_sex = _normalize_sex(sex)
    resolved_indicator = _normalize_indicator(indicator)
    max_results = min(max_results, 100)

    try:
        resolved_year = _coerce_int(year, "year")
        resolved_age_min = _coerce_int(age_min, "age_min")
        resolved_age_max = _coerce_int(age_max, "age_max")
    except ValueError as exc:
        return list_response(
            tool_name="search_oncology_burden",
            data_type="oncology_burden_results",
            items=[],
            quality_note="Oncology burden discovery requires numeric year and age filters when provided.",
            coverage="Configured BigQuery oncology burden view.",
            warnings=[
                {
                    "source": "tool_validation",
                    "stage": "validate_numeric_filters",
                    "error": str(exc),
                }
            ],
            requested_filters={
                "site": resolved_site,
                "indication": indication,
                "country": resolved_country,
                "sex": resolved_sex,
                "indicator": resolved_indicator,
                "year": year,
                "age_min": age_min,
                "age_max": age_max,
                "max_results": max_results,
            },
            evidence_sources=["tool_validation"],
            evidence_trace=[
                {
                    "step": "validate_numeric_filters",
                    "sources": ["tool_validation"],
                    "note": "Rejected the request because one of the numeric filters could not be parsed as an integer.",
                    "filters": {
                        "year": year,
                        "age_min": age_min,
                        "age_max": age_max,
                    },
                    "output_kind": "raw",
                    "refs": [],
                }
            ],
        )

    if not any(value is not None for value in (resolved_site, resolved_country, resolved_indicator)):
        return list_response(
            tool_name="search_oncology_burden",
            data_type="oncology_burden_results",
            items=[],
            quality_note="Oncology burden discovery requires at least one of site, country, or indicator.",
            coverage="Configured BigQuery oncology burden view.",
            warnings=[
                {
                    "source": "tool_validation",
                    "stage": "validate_filters",
                    "error": "Provide at least one of `site`, `indication`, `country`, or `indicator`.",
                }
            ],
            requested_filters={
                "site": site,
                "indication": indication,
                "country": country,
                "sex": sex,
                "indicator": indicator,
                "year": year,
                "age_min": age_min,
                "age_max": age_max,
                "max_results": max_results,
            },
            evidence_sources=["tool_validation"],
            evidence_trace=[
                {
                    "step": "validate_oncology_filters",
                    "sources": ["tool_validation"],
                    "note": "Rejected the request because no site, country, or indicator filter was provided.",
                    "filters": {
                        "site": site,
                        "indication": indication,
                        "country": resolved_country,
                        "indicator": resolved_indicator,
                    },
                    "output_kind": "raw",
                    "refs": [],
                }
            ],
        )

    response = await registry.search_oncology_burden(
        site=resolved_site,
        country=resolved_country,
        sex=resolved_sex,
        indicator=resolved_indicator,
        year=resolved_year,
        age_min=resolved_age_min,
        age_max=resolved_age_max,
        max_results=max_results,
    )
    payload = [record.model_dump() for record in response.items]
    return list_response(
        tool_name="search_oncology_burden",
        data_type="oncology_burden_results",
        items=payload,
        quality_note="Rows are returned directly from the configured BigQuery oncology burden view after lightweight query normalization.",
        coverage="Prepared oncology burden view in BigQuery, currently backed by the loaded oncology burden dataset.",
        queried_sources=response.queried_sources,
        warnings=[warning.as_dict() for warning in response.warnings],
        evidence_sources=response.queried_sources,
        evidence_trace=[
            {
                "step": "query_bigquery_oncology_view",
                "sources": response.queried_sources,
                "note": "Fetched oncology burden rows from the configured BigQuery view using the requested structured filters.",
                "filters": {
                    "site": resolved_site,
                    "country": resolved_country,
                    "sex": resolved_sex,
                    "indicator": resolved_indicator,
                    "year": resolved_year,
                    "age_min": resolved_age_min,
                    "age_max": resolved_age_max,
                    "max_results": max_results,
                },
                "output_kind": "raw",
                "refs": payload,
            }
        ],
        requested_filters={
            "site": resolved_site,
            "indication": indication,
            "country": resolved_country,
            "sex": resolved_sex,
            "indicator": resolved_indicator,
            "year": resolved_year,
            "age_min": resolved_age_min,
            "age_max": resolved_age_max,
            "max_results": max_results,
        },
    )
