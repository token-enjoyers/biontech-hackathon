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
    start_date: str | None = None
    primary_completion_date: str | None = None
    completion_date: str | None = None


class TrialDetail(TrialSummary):
    official_title: str | None = None
    eligibility_criteria: str | None = None
    arms: list[str] = []
    secondary_outcomes: list[str] = []
    study_type: str | None = None
    conditions: list[str] = []
    why_stopped: str | None = None
    facility_names: list[str] = []
    facility_cities: list[str] = []
    facility_states: list[str] = []
    location_countries: list[str] = []
    overall_officials: list[str] = []


class TrialTimeline(BaseModel):
    source: str
    nct_id: str
    brief_title: str
    phase: str | None = None
    lead_sponsor: str
    overall_status: str = ""
    start_date: str | None = None
    primary_completion_date: str | None = None
    completion_date: str | None = None
    enrollment_count: int | None = None


class Publication(BaseModel):
    source: str
    pmid: str | None = None
    title: str
    authors: list[str] = []
    journal: str
    pub_date: str
    abstract: str = ""
    doi: str | None = None
    mesh_terms: list[str] = []


class ConferenceAbstract(BaseModel):
    source: str
    source_id: str
    title: str
    authors: list[str] = []
    conference_name: str
    conference_series: str | None = None
    presentation_type: str | None = None
    abstract_number: str | None = None
    publication_year: int | None = None
    publication_date: str | None = None
    abstract: str = ""
    doi: str | None = None
    url: str | None = None
    journal: str | None = None


class ApprovedDrug(BaseModel):
    source: str
    approval_id: str
    brand_name: str | None = None
    generic_name: str | None = None
    indication: str | None = None
    sponsor: str | None = None
    route: list[str] = []
    product_type: str | None = None
    substance_names: list[str] = []
    mechanism_of_action: str | None = None
    pharmacodynamics: str | None = None
    pharmacokinetics: str | None = None
    clinical_pharmacology: str | None = None
    clinical_studies_summary: str | None = None
    dosage_and_administration: str | None = None
    dosage_forms_and_strengths: str | None = None
    warnings: str | None = None
    adverse_reactions: str | None = None
    contraindications: str | None = None
    drug_interactions: str | None = None
