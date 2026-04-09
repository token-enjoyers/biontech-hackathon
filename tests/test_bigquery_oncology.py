from __future__ import annotations

import pytest

from Medical_Wizard_MCP.sources.bigquery_oncology import BigQueryOncologySource


class FakeScalarQueryParameter:
    def __init__(self, name: str, type_name: str, value: object) -> None:
        self.name = name
        self.type_name = type_name
        self.value = value


class FakeQueryJobConfig:
    def __init__(self, query_parameters: list[FakeScalarQueryParameter]) -> None:
        self.query_parameters = query_parameters


class FakeJob:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def result(self) -> list[dict[str, object]]:
        return self._rows


class FakeClient:
    def __init__(self, *, project: str, location: str | None = None) -> None:
        self.project = project
        self.location = location
        self.responses: list[list[dict[str, object]]] = []
        self.sql_history: list[str] = []
        self.job_config_history: list[FakeQueryJobConfig] = []

    def query(self, sql: str, job_config: FakeQueryJobConfig) -> FakeJob:
        self.sql_history.append(sql)
        self.job_config_history.append(job_config)
        rows = self.responses.pop(0) if self.responses else []
        return FakeJob(rows)


class FakeBigQueryModule:
    ScalarQueryParameter = FakeScalarQueryParameter
    QueryJobConfig = FakeQueryJobConfig

    def __init__(self) -> None:
        self.created_clients: list[FakeClient] = []

    def Client(self, *, project: str, location: str | None = None) -> FakeClient:
        client = FakeClient(project=project, location=location)
        self.created_clients.append(client)
        return client


@pytest.mark.asyncio
async def test_bigquery_oncology_source_builds_casefolded_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_bigquery = FakeBigQueryModule()
    monkeypatch.setattr(
        "Medical_Wizard_MCP.sources.bigquery_oncology._load_bigquery_module",
        lambda: fake_bigquery,
    )
    monkeypatch.setenv("BIGQUERY_PROJECT_ID", "demo-project")
    monkeypatch.setenv("BIGQUERY_DATASET", "oncology")
    monkeypatch.setenv("BIGQUERY_ONCOLOGY_VIEW", "oncology_burden_search")
    monkeypatch.setenv("BIGQUERY_LOCATION", "EU")

    source = BigQueryOncologySource()
    await source.initialize()
    source._client.responses = [
        [
            {
                "dataset": "deaths_light",
                "study": "Historical data",
                "registry": "National Cancer Registry of Austria",
                "country": "Austria",
                "sex": "Male",
                "site": "Lung",
                "indicator": "Mortality",
                "geo_code": None,
                "year": 1983,
                "age_min": 0,
                "age_max": 4,
                "cases": 0.0,
                "population": 229620.0,
            }
        ]
    ]

    records = await source.search_oncology_burden(
        site="lung cancer",
        country="Austria",
        indicator="deaths",
        sex="men",
        year="1983",
        max_results=5,
    )

    assert len(records) == 1
    assert records[0].country == "Austria"
    assert records[0].site == "Lung"
    sql = source._client.sql_history[0]
    assert "FROM `demo-project.oncology.oncology_burden_search`" in sql
    assert "LOWER(site) = @site" in sql
    assert "LOWER(country) = @country" in sql
    assert "LOWER(indicator) = @indicator" in sql
    assert "LOWER(sex) = @sex" in sql

    params = {
        parameter.name: (parameter.type_name, parameter.value)
        for parameter in source._client.job_config_history[0].query_parameters
    }
    assert params["site"] == ("STRING", "lung")
    assert params["country"] == ("STRING", "austria")
    assert params["indicator"] == ("STRING", "mortality")
    assert params["sex"] == ("STRING", "male")
    assert params["year"] == ("INT64", 1983)
    assert params["max_results"] == ("INT64", 5)


@pytest.mark.asyncio
async def test_bigquery_oncology_source_retries_with_site_contains(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_bigquery = FakeBigQueryModule()
    monkeypatch.setattr(
        "Medical_Wizard_MCP.sources.bigquery_oncology._load_bigquery_module",
        lambda: fake_bigquery,
    )
    monkeypatch.setenv("BIGQUERY_PROJECT_ID", "demo-project")
    monkeypatch.setenv("BIGQUERY_DATASET", "oncology")

    source = BigQueryOncologySource()
    await source.initialize()
    source._client.responses = [
        [],
        [
            {
                "dataset": "deaths_light",
                "study": "Historical data",
                "registry": "Cancer Registry of Veneto",
                "country": "Italy",
                "sex": "Male",
                "site": "All cancer entities excluding keratinocytic skin cancers",
                "indicator": "Incidence",
                "geo_code": None,
                "year": 2021,
                "age_min": 70,
                "age_max": 74,
                "cases": 3024.0,
                "population": 128420.0,
            }
        ],
    ]

    records = await source.search_oncology_burden(
        site="all cancer entities",
        country="Italy",
        indicator="Incidence",
        max_results=3,
    )

    assert len(records) == 1
    assert len(source._client.sql_history) == 2
    assert "LOWER(site) = @site" in source._client.sql_history[0]
    assert "LOWER(site) LIKE @site_pattern" in source._client.sql_history[1]

    fallback_params = {
        parameter.name: (parameter.type_name, parameter.value)
        for parameter in source._client.job_config_history[1].query_parameters
    }
    assert fallback_params["site_pattern"] == ("STRING", "%all%entities%")


@pytest.mark.asyncio
async def test_bigquery_oncology_source_requires_core_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_bigquery = FakeBigQueryModule()
    monkeypatch.setattr(
        "Medical_Wizard_MCP.sources.bigquery_oncology._load_bigquery_module",
        lambda: fake_bigquery,
    )
    monkeypatch.setenv("BIGQUERY_PROJECT_ID", "demo-project")
    monkeypatch.setenv("BIGQUERY_DATASET", "oncology")

    source = BigQueryOncologySource()
    await source.initialize()

    with pytest.raises(RuntimeError, match="Provide at least one of site, country, or indicator."):
        await source.search_oncology_burden(sex="Female", max_results=5)
