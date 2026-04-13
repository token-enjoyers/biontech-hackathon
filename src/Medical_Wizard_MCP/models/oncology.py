from pydantic import BaseModel


class OncologyBurdenRecord(BaseModel):
    source: str
    dataset: str
    study: str | None = None
    registry: str | None = None
    country: str | None = None
    sex: str | None = None
    site: str
    indicator: str | None = None
    geo_code: str | None = None
    year: int | None = None
    age_min: int | None = None
    age_max: int | None = None
    cases: float | None = None
    population: float | None = None
