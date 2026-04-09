from pydantic import BaseModel


class TrialSummary(BaseModel):
    source: str
    nct_id: str
    brief_title: str
    phase: str | None = None
    overall_status: str
    lead_sponsor: str
    interventions: list[str] = []
    primary_outcomes: list[str] = []
    enrollment_count: int | None = None


class TrialDetail(TrialSummary):
    official_title: str | None = None
    eligibility_criteria: str | None = None
    arms: list[str] = []
    secondary_outcomes: list[str] = []
    study_type: str | None = None
    conditions: list[str] = []


class TrialTimeline(BaseModel):
    source: str
    nct_id: str
    brief_title: str
    phase: str | None = None
    lead_sponsor: str
    start_date: str | None = None
    primary_completion_date: str | None = None
    completion_date: str | None = None
    enrollment_count: int | None = None


class Publication(BaseModel):
    source: str
    pmid: str
    title: str
    authors: list[str] = []
    journal: str
    pub_date: str
    abstract: str = ""
