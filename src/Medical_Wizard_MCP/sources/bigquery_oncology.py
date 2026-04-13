from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass
from typing import Any

from ..models import OncologyBurdenRecord
from .base import BaseSource

logger = logging.getLogger(__name__)

SOURCE_NAME = "bigquery_oncology"
_TABLE_REF_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
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
    "leukaemia": "Leukaemia",
    "leukemia": "Leukaemia",
}


@dataclass(frozen=True)
class BurdenQuery:
    site: str | None
    country: str | None
    sex: str | None
    indicator: str | None
    year: int | None
    age_min: int | None
    age_max: int | None
    max_results: int
    match_mode: str = "exact"


def _load_bigquery_module() -> Any:
    try:
        from google.cloud import bigquery
    except ImportError as exc:
        raise RuntimeError(
            "google-cloud-bigquery is not installed. Add the dependency and sync the environment."
        ) from exc
    return bigquery


class BigQueryOncologySource(BaseSource):
    name = SOURCE_NAME
    capabilities = frozenset({"oncology_burden_search"})

    def __init__(self) -> None:
        self._client: Any | None = None
        self._project_id: str | None = None
        self._location: str | None = None
        self._table_ref: str | None = None

    async def initialize(self) -> None:
        self._project_id = self._required_env("BIGQUERY_PROJECT_ID")
        self._location = os.getenv("BIGQUERY_LOCATION") or None
        self._table_ref = self._resolve_table_ref()

        bigquery = _load_bigquery_module()
        self._client = bigquery.Client(project=self._project_id, location=self._location)
        logger.info("Configured BigQuery oncology view: %s", self._table_ref)

    async def close(self) -> None:
        self._client = None

    async def search_oncology_burden(
        self,
        *,
        site: str | None = None,
        country: str | None = None,
        sex: str | None = None,
        indicator: str | None = None,
        year: int | None = None,
        age_min: int | None = None,
        age_max: int | None = None,
        max_results: int = 10,
    ) -> list[OncologyBurdenRecord]:
        if self._client is None or self._table_ref is None:
            raise RuntimeError("BigQuery oncology source is not initialized.")

        normalized_query = BurdenQuery(
            site=self._normalize_site(site),
            country=self._clean_text(country),
            sex=self._normalize_sex(sex),
            indicator=self._normalize_indicator(indicator),
            year=self._coerce_int(year, "year"),
            age_min=self._coerce_int(age_min, "age_min"),
            age_max=self._coerce_int(age_max, "age_max"),
            max_results=max(1, min(int(max_results), 100)),
            match_mode="exact",
        )
        if not any((normalized_query.site, normalized_query.country, normalized_query.indicator)):
            raise RuntimeError("Provide at least one of site, country, or indicator.")

        queries = [normalized_query]
        if normalized_query.site is not None:
            queries.append(BurdenQuery(**{**normalized_query.__dict__, "match_mode": "site_contains"}))

        last_results: list[OncologyBurdenRecord] = []
        for query in queries:
            sql, query_parameters = self._build_query(query)
            results = await asyncio.to_thread(self._execute_query, sql, query_parameters)
            if results:
                return results
            last_results = results

        return last_results

    def _required_env(self, name: str) -> str:
        value = os.getenv(name, "").strip()
        if not value:
            raise RuntimeError(f"Missing required environment variable {name}.")
        return value

    def _resolve_table_ref(self) -> str:
        configured_view = os.getenv("BIGQUERY_ONCOLOGY_VIEW", "").strip()
        dataset = os.getenv("BIGQUERY_DATASET", "").strip()

        if configured_view:
            parts = configured_view.split(".")
            if len(parts) == 3:
                table_ref = configured_view
            elif len(parts) == 2:
                table_ref = f"{self._project_id}.{configured_view}"
            else:
                if not dataset:
                    raise RuntimeError(
                        "Set BIGQUERY_DATASET when BIGQUERY_ONCOLOGY_VIEW is not fully qualified."
                    )
                table_ref = f"{self._project_id}.{dataset}.{configured_view}"
        else:
            if not dataset:
                raise RuntimeError(
                    "Configure BIGQUERY_ONCOLOGY_VIEW or BIGQUERY_DATASET for the oncology view."
                )
            table_ref = f"{self._project_id}.{dataset}.oncology_burden_search"

        if not _TABLE_REF_PATTERN.match(table_ref):
            raise RuntimeError(f"Invalid BigQuery table reference: {table_ref}")
        return table_ref

    def _build_query(self, query: BurdenQuery) -> tuple[str, list[Any]]:
        bigquery = _load_bigquery_module()
        where_clauses: list[str] = []
        query_parameters: list[Any] = []

        def add_scalar_filter(name: str, value: Any, type_name: str, clause: str) -> None:
            if value is None:
                return
            where_clauses.append(clause)
            query_parameters.append(bigquery.ScalarQueryParameter(name, type_name, value))

        if query.site is not None:
            if query.match_mode == "site_contains":
                where_clauses.append("LOWER(site) LIKE @site_pattern")
                query_parameters.append(
                    bigquery.ScalarQueryParameter("site_pattern", "STRING", self._build_site_pattern(query.site))
                )
            else:
                add_scalar_filter("site", self._casefold(query.site), "STRING", "LOWER(site) = @site")

        add_scalar_filter("country", self._casefold(query.country), "STRING", "LOWER(country) = @country")
        add_scalar_filter("sex", self._casefold(query.sex), "STRING", "LOWER(sex) = @sex")
        add_scalar_filter(
            "indicator",
            self._casefold(query.indicator),
            "STRING",
            "LOWER(indicator) = @indicator",
        )
        add_scalar_filter("year", query.year, "INT64", "year = @year")
        add_scalar_filter("age_min", query.age_min, "INT64", "age_min >= @age_min")
        add_scalar_filter("age_max", query.age_max, "INT64", "age_max <= @age_max")
        query_parameters.append(bigquery.ScalarQueryParameter("max_results", "INT64", query.max_results))

        where_sql = ""
        if where_clauses:
            where_sql = "WHERE " + " AND ".join(where_clauses)

        sql = f"""
SELECT
  dataset,
  study,
  registry,
  country,
  sex,
  site,
  indicator,
  geo_code,
  year,
  age_min,
  age_max,
  cases,
  population
FROM `{self._table_ref}`
{where_sql}
ORDER BY
  CASE
    WHEN LOWER(registry) LIKE '%national%' THEN 0
    WHEN LOWER(registry) LIKE '%country%' THEN 1
    ELSE 2
  END ASC,
  year DESC,
  cases DESC,
  country ASC,
  site ASC
LIMIT @max_results
""".strip()
        return sql, query_parameters

    def _execute_query(self, sql: str, query_parameters: list[Any]) -> list[OncologyBurdenRecord]:
        if self._client is None:
            raise RuntimeError("BigQuery oncology source is not initialized.")

        bigquery = _load_bigquery_module()
        job_config = bigquery.QueryJobConfig(query_parameters=query_parameters)
        job = self._client.query(sql, job_config=job_config)
        return [self._map_row(row) for row in job.result()]

    def _map_row(self, row: Any) -> OncologyBurdenRecord:
        return OncologyBurdenRecord(
            source=SOURCE_NAME,
            dataset=self._row_value(row, "dataset") or "oncology_burden_search",
            study=self._row_value(row, "study"),
            registry=self._row_value(row, "registry"),
            country=self._row_value(row, "country"),
            sex=self._row_value(row, "sex"),
            site=self._row_value(row, "site") or "",
            indicator=self._row_value(row, "indicator"),
            geo_code=self._row_value(row, "geo_code"),
            year=self._row_value(row, "year"),
            age_min=self._row_value(row, "age_min"),
            age_max=self._row_value(row, "age_max"),
            cases=self._row_value(row, "cases"),
            population=self._row_value(row, "population"),
        )

    def _row_value(self, row: Any, key: str) -> Any:
        if hasattr(row, "get"):
            return row.get(key)
        try:
            return row[key]
        except Exception:
            return getattr(row, key, None)

    def _clean_text(self, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    def _normalize_site(self, value: str | None) -> str | None:
        cleaned = self._clean_text(value)
        if cleaned is None:
            return None
        lowered = self._casefold(cleaned)
        alias = _SITE_ALIAS_MAP.get(lowered)
        if alias:
            return alias
        if lowered.endswith(" cancer"):
            trimmed = cleaned[: -len(" cancer")].strip()
            if trimmed:
                return trimmed
        if lowered.endswith(" tumour"):
            trimmed = cleaned[: -len(" tumour")].strip()
            if trimmed:
                return trimmed
        if lowered.endswith(" tumor"):
            trimmed = cleaned[: -len(" tumor")].strip()
            if trimmed:
                return trimmed
        return cleaned

    def _normalize_indicator(self, value: str | None) -> str | None:
        cleaned = self._clean_text(value)
        if cleaned is None:
            return None
        lowered = self._casefold(cleaned)
        if lowered in {"mortality", "death", "deaths"}:
            return "Mortality"
        if lowered in {"incidence", "case", "cases", "new cases"}:
            return "Incidence"
        return cleaned

    def _normalize_sex(self, value: str | None) -> str | None:
        cleaned = self._clean_text(value)
        if cleaned is None:
            return None
        lowered = self._casefold(cleaned)
        if lowered in {"female", "women", "woman"}:
            return "Female"
        if lowered in {"male", "men", "man"}:
            return "Male"
        return cleaned

    def _coerce_int(self, value: Any, field_name: str) -> int | None:
        if value is None or value == "":
            return None
        if isinstance(value, bool):
            raise RuntimeError(f"{field_name} must be an integer.")
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return None
            try:
                return int(stripped)
            except ValueError as exc:
                raise RuntimeError(f"{field_name} must be an integer.") from exc
        raise RuntimeError(f"{field_name} must be an integer.")

    def _casefold(self, value: str | None) -> str | None:
        if value is None:
            return None
        return value.casefold()

    def _build_site_pattern(self, site: str) -> str:
        tokens = [token for token in re.split(r"[^a-z0-9]+", site.casefold()) if token and token != "cancer"]
        if not tokens:
            return f"%{site.casefold()}%"
        return "%" + "%".join(tokens) + "%"
