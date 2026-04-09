from __future__ import annotations

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


def canonical_phase(phase: str | None) -> str | None:
    if not phase:
        return None
    normalized = phase.upper().replace("-", " ").replace("/", "/")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    normalized = normalized.replace("PHASE ", "PHASE ")
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
