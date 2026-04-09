from __future__ import annotations

import calendar
from collections import Counter
from datetime import UTC, datetime
from statistics import median
import re


ACTIVE_STATUSES = {"RECRUITING", "NOT_YET_RECRUITING", "ACTIVE_NOT_RECRUITING"}
TERMINAL_STATUSES = {"TERMINATED", "WITHDRAWN", "SUSPENDED"}

PHASE_ORDER = {
    "EARLY PHASE 1": 0,
    "PHASE 1": 1,
    "PHASE 1/PHASE 2": 2,
    "PHASE 2": 3,
    "PHASE 2/PHASE 3": 4,
    "PHASE 3": 5,
    "PHASE 4": 6,
}

MECHANISM_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bmrna\b|\bneoantigen\b|\brna vaccine\b", re.I), "mRNA vaccine"),
    (re.compile(r"\bpd-1\b|\bpembrolizumab\b|\bnivolumab\b|\bcemiplimab\b", re.I), "PD-1 inhibitor"),
    (re.compile(r"\bpd-l1\b|\batezolizumab\b|\bdurvalumab\b|\bavelumab\b", re.I), "PD-L1 inhibitor"),
    (re.compile(r"\bctla-4\b|\bipilimumab\b", re.I), "CTLA-4 inhibitor"),
    (re.compile(r"\bcar[- ]?t\b", re.I), "CAR-T"),
    (re.compile(r"\bbispecific\b", re.I), "bispecific antibody"),
    (re.compile(r"\badc\b|\bantibody-drug conjugate\b", re.I), "antibody-drug conjugate"),
    (re.compile(r"\boncolytic\b|\bvirus\b", re.I), "oncolytic virus"),
    (re.compile(r"\bvaccine\b", re.I), "cancer vaccine"),
    (re.compile(r"\bchemotherapy\b|\bcisplatin\b|\bcarboplatin\b|\bpaclitaxel\b", re.I), "chemotherapy combo"),
    (re.compile(r"\bcell therapy\b", re.I), "cell therapy"),
]

BIOMARKER_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\btmb\b|tumou?r mutational burden", re.I), "TMB-high"),
    (re.compile(r"\bpd-l1\b", re.I), "PD-L1 positive"),
    (re.compile(r"\begfr\b", re.I), "EGFR"),
    (re.compile(r"\balk\b", re.I), "ALK"),
    (re.compile(r"\bmsi\b|\bmicrosatellite instability\b", re.I), "MSI-high"),
    (re.compile(r"\bhla[- ]?[a-z0-9*]+\b", re.I), "HLA-selected"),
    (re.compile(r"\bmgmt\b", re.I), "MGMT"),
]

ENDPOINT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\boverall survival\b|\bos\b", re.I), "overall survival"),
    (re.compile(r"\bprogression[- ]free survival\b|\bpfs\b", re.I), "progression-free survival"),
    (re.compile(r"\bobjective response rate\b|\borr\b", re.I), "objective response rate"),
    (re.compile(r"\bduration of response\b|\bdor\b", re.I), "duration of response"),
    (re.compile(r"\bdisease control rate\b|\bdcr\b", re.I), "disease control rate"),
    (re.compile(r"\bsafety\b|\btolerability\b|\bdose[- ]limiting toxicity\b|\bdlt\b", re.I), "safety / tolerability"),
    (re.compile(r"\bmaximum tolerated dose\b|\bmtd\b|\brecommended phase 2 dose\b|\brp2d\b", re.I), "dose finding"),
    (re.compile(r"\bpharmacokinetic\b|\bpk\b", re.I), "pharmacokinetics"),
    (re.compile(r"\bpharmacodynamic\b|\bpd\b", re.I), "pharmacodynamics"),
    (re.compile(r"\bcomplete response\b|\bpathologic complete response\b|\bpcr\b", re.I), "response depth"),
    (re.compile(r"\bbiomarker\b|\bimmune response\b", re.I), "biomarker / translational"),
]

INCLUSION_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b18 years|\bage\s*>=?\s*18|\badult", re.I), "adult patients"),
    (re.compile(r"\becog\b.{0,12}\b0[- ]?1\b", re.I), "ECOG 0-1"),
    (re.compile(r"\becog\b.{0,12}\b0[- ]?2\b", re.I), "ECOG 0-2"),
    (re.compile(r"\bmeasurable disease\b", re.I), "measurable disease"),
    (re.compile(r"\badequate organ function\b", re.I), "adequate organ function"),
    (re.compile(r"\bhistologically|cytologically confirmed\b", re.I), "pathology-confirmed disease"),
    (re.compile(r"\bprogress(ed|ion) after\b|\bfailed prior\b|\bafter prior therapy\b", re.I), "prior therapy required"),
]

EXCLUSION_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bactive autoimmune\b", re.I), "active autoimmune disease"),
    (re.compile(r"\bsystemic corticosteroid|\bimmunosuppressive", re.I), "systemic immunosuppression"),
    (re.compile(r"\buntreated cns\b|\buntreated brain\b", re.I), "untreated CNS metastases"),
    (re.compile(r"\buncontrolled infection\b", re.I), "uncontrolled infection"),
    (re.compile(r"\binterstitial lung disease\b|\bpneumonitis\b", re.I), "ILD / pneumonitis history"),
    (re.compile(r"\bprior (pd-1|pd-l1|ctla-4|checkpoint)\b", re.I), "prior checkpoint therapy"),
]

PATIENT_SEGMENT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bfirst[- ]line\b|1l\b", re.I), "first-line"),
    (re.compile(r"\bsecond[- ]line\b|2l\b", re.I), "second-line"),
    (re.compile(r"\bthird[- ]line\b|\blater[- ]line\b|3l\b", re.I), "later-line"),
    (re.compile(r"\bmaintenance\b", re.I), "maintenance"),
    (re.compile(r"\brelapsed\b|\brefractory\b", re.I), "relapsed / refractory"),
    (re.compile(r"\badvanced\b|\bmetastatic\b", re.I), "advanced / metastatic"),
    (re.compile(r"\blocally advanced\b|\bunresectable\b", re.I), "locally advanced / unresectable"),
    (re.compile(r"\badjuvant\b", re.I), "adjuvant"),
    (re.compile(r"\bneoadjuvant\b", re.I), "neoadjuvant"),
    (re.compile(r"\bcns metastases\b|\bbrain metastases\b", re.I), "brain metastases"),
]

SAFETY_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bcytokine release syndrome\b|\bcrs\b", re.I), "cytokine release syndrome"),
    (re.compile(r"\bpneumonitis\b", re.I), "pneumonitis"),
    (re.compile(r"\bcolitis\b", re.I), "colitis"),
    (re.compile(r"\bhepatotoxicity\b|\btransaminase\b|\balt\b|\bast\b", re.I), "hepatic toxicity"),
    (re.compile(r"\bneutropenia\b|\banemia\b|\bthrombocytopenia\b", re.I), "hematologic toxicity"),
    (re.compile(r"\brash\b|\bdermatitis\b", re.I), "skin toxicity"),
    (re.compile(r"\bfatigue\b", re.I), "fatigue"),
    (re.compile(r"\bnausea\b|\bvomiting\b", re.I), "gastrointestinal toxicity"),
    (re.compile(r"\binfusion-related\b|\binfusion reaction\b", re.I), "infusion-related reaction"),
    (re.compile(r"\bimmune-related adverse event\b|\birae\b", re.I), "immune-related toxicity"),
]

COMPARATOR_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bplacebo\b", re.I), "placebo-controlled"),
    (re.compile(r"\bstandard of care\b|\bsoc\b", re.I), "standard of care comparator"),
    (re.compile(r"\bphysician'?s choice\b", re.I), "physician's choice"),
    (re.compile(r"\bchemotherapy\b", re.I), "chemotherapy comparator"),
]


def canonical_phase(phase: str | None) -> str | None:
    if not phase:
        return None
    normalized = phase.upper().replace("-", " ").replace("/", "/")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    normalized = normalized.replace("EARLYPHASE", "EARLY PHASE ")
    normalized = re.sub(r"PHASE(?=\d)", "PHASE ", normalized)
    return normalized


def phase_code(phase: str | None) -> str | None:
    canonical = canonical_phase(phase)
    return canonical.replace(" ", "") if canonical else None


def phase_rank(phase: str | None) -> int:
    canonical = canonical_phase(phase)
    if canonical is None:
        return -1
    return PHASE_ORDER.get(canonical, -1)


def furthest_phase(phases: list[str]) -> str | None:
    ranked = sorted((phase for phase in phases if phase), key=phase_rank)
    return ranked[-1] if ranked else None


def parse_partial_date(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            parsed = datetime.strptime(value, fmt)
            return parsed.replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def months_between(start: str | None, end: str | None) -> float | None:
    start_dt = parse_partial_date(start)
    end_dt = parse_partial_date(end)
    if start_dt is None or end_dt is None or end_dt < start_dt:
        return None
    delta_days = (end_dt - start_dt).days
    return round(delta_days / 30.44, 1)


def now_utc() -> datetime:
    return datetime.now(UTC)


def months_since(date_str: str | None) -> float | None:
    start_dt = parse_partial_date(date_str)
    if start_dt is None:
        return None
    return round((now_utc() - start_dt).days / 30.44, 1)


def months_until(date_str: str | None) -> float | None:
    target_dt = parse_partial_date(date_str)
    if target_dt is None:
        return None
    return round((target_dt - now_utc()).days / 30.44, 1)


def add_months_to_date(date_str: str | None, months: int) -> str | None:
    start_dt = parse_partial_date(date_str)
    if start_dt is None:
        return None

    month_index = start_dt.month - 1 + months
    year = start_dt.year + month_index // 12
    month = month_index % 12 + 1
    day = min(start_dt.day, calendar.monthrange(year, month)[1])
    return f"{year:04d}-{month:02d}-{day:02d}"


def classify_mechanisms(*texts: str | None) -> list[str]:
    haystack = " ".join(text for text in texts if text).strip()
    if not haystack:
        return []

    found: list[str] = []
    for pattern, label in MECHANISM_PATTERNS:
        if pattern.search(haystack):
            found.append(label)

    if not found and haystack:
        found.append("other / unspecified")

    return list(dict.fromkeys(found))


def extract_biomarkers(*texts: str | None) -> list[str]:
    haystack = " ".join(text for text in texts if text).strip()
    if not haystack:
        return []

    found: list[str] = []
    for pattern, label in BIOMARKER_PATTERNS:
        if pattern.search(haystack):
            found.append(label)
    return list(dict.fromkeys(found))


def classify_endpoint(endpoint_text: str | None) -> str:
    haystack = (endpoint_text or "").strip()
    if not haystack:
        return "other / unspecified"
    for pattern, label in ENDPOINT_PATTERNS:
        if pattern.search(haystack):
            return label
    return "other / unspecified"


def extract_eligibility_features(criteria_text: str | None) -> tuple[list[str], list[str]]:
    haystack = criteria_text or ""
    inclusions = [label for pattern, label in INCLUSION_PATTERNS if pattern.search(haystack)]
    exclusions = [label for pattern, label in EXCLUSION_PATTERNS if pattern.search(haystack)]
    return list(dict.fromkeys(inclusions)), list(dict.fromkeys(exclusions))


def extract_patient_segments(*texts: str | None) -> list[str]:
    haystack = " ".join(text for text in texts if text).strip()
    if not haystack:
        return []

    segments = [label for pattern, label in PATIENT_SEGMENT_PATTERNS if pattern.search(haystack)]
    segments.extend(extract_biomarkers(haystack))
    return list(dict.fromkeys(segments))


def extract_safety_signals(*texts: str | None) -> list[str]:
    haystack = " ".join(text for text in texts if text).strip()
    if not haystack:
        return []

    signals = [label for pattern, label in SAFETY_PATTERNS if pattern.search(haystack)]
    return list(dict.fromkeys(signals))


def extract_comparator_signals(*texts: str | None) -> list[str]:
    haystack = " ".join(text for text in texts if text).strip()
    if not haystack:
        return []

    comparators = [label for pattern, label in COMPARATOR_PATTERNS if pattern.search(haystack)]
    return list(dict.fromkeys(comparators))


def top_counts(items: list[str], limit: int = 5) -> list[tuple[str, int]]:
    counter = Counter(item for item in items if item)
    return counter.most_common(limit)


def median_enrollment(values: list[int | None], fallback: int) -> int:
    numbers = [value for value in values if isinstance(value, int) and value > 0]
    if not numbers:
        return fallback
    return int(round(median(numbers)))


def unique_nonempty(items: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in items if item))


def infer_primary_endpoint(condition: str, recommended_phase: str) -> str:
    condition_lower = condition.lower()
    if recommended_phase == "PHASE1":
        return "Dose-limiting toxicity and safety"
    if recommended_phase == "PHASE3":
        return "Overall survival"
    if "glioblastoma" in condition_lower or condition_lower == "gbm":
        return "Progression-free survival at 6 months"
    return "Objective response rate"


def infer_signal_strength(active_count: int, terminated_count: int) -> str:
    if active_count <= 2 and terminated_count == 0:
        return "HIGH"
    if active_count <= 5:
        return "MEDIUM"
    return "LOW"


def sponsor_saturation_score(total_trials: int, unique_sponsors: int) -> str:
    if total_trials >= 50 or unique_sponsors >= 15:
        return "HIGH"
    if total_trials >= 20 or unique_sponsors >= 8:
        return "MEDIUM"
    return "LOW"
