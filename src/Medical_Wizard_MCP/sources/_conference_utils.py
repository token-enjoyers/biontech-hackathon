from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Any


DEFAULT_CONFERENCE_SERIES = ("ASCO", "AACR", "ESMO", "SITC")

CONFERENCE_ALIASES: dict[str, tuple[str, ...]] = {
    "ASCO": (
        "asco",
        "american society of clinical oncology",
        "asco annual meeting",
        "asco gastrointestinal cancers symposium",
    ),
    "AACR": (
        "aacr",
        "american association for cancer research",
        "aacr annual meeting",
        "aacr special conference",
    ),
    "ESMO": (
        "esmo",
        "european society for medical oncology",
        "esmo congress",
        "esmo immuno-oncology congress",
    ),
    "SITC": (
        "sitc",
        "society for immunotherapy of cancer",
        "sitc annual meeting",
    ),
}

CONFERENCE_QUERY_HINTS: dict[str, str] = {
    "ASCO": "ASCO Annual Meeting",
    "AACR": "AACR Annual Meeting",
    "ESMO": "ESMO Congress",
    "SITC": "SITC Annual Meeting",
}

PRESENTATION_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\blate[- ]breaking\b", re.I), "late-breaking abstract"),
    (re.compile(r"\bmini[- ]oral\b", re.I), "mini-oral presentation"),
    (re.compile(r"\boral\b", re.I), "oral presentation"),
    (re.compile(r"\bposter\b", re.I), "poster"),
    (re.compile(r"\bplenary\b", re.I), "plenary"),
    (re.compile(r"\babstract\b", re.I), "abstract"),
)

ABSTRACT_NUMBER_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:abstract|abs\.?)\s*#?\s*([A-Z]?\d{2,6}[A-Z]?)\b", re.I),
    re.compile(r"\b([A-Z]{1,3}\d{2,5})\b"),
)


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return " ".join(value.split())
    return str(value).strip()


def first_text(value: Any) -> str | None:
    if isinstance(value, list):
        for item in value:
            text = clean_text(item)
            if text:
                return text
        return None
    text = clean_text(value)
    return text or None


def strip_tags(text: str | None) -> str:
    if not text:
        return ""
    return clean_text(re.sub(r"<[^>]+>", " ", text))


def normalize_conference_series(series: list[str] | None) -> list[str]:
    if not series:
        return list(DEFAULT_CONFERENCE_SERIES)

    normalized: list[str] = []
    for item in series:
        text = clean_text(item).upper()
        if not text:
            continue
        if text in CONFERENCE_ALIASES:
            normalized.append(text)
            continue
        lowered = text.lower()
        for canonical, aliases in CONFERENCE_ALIASES.items():
            if lowered == canonical.lower() or any(alias in lowered for alias in aliases):
                normalized.append(canonical)
                break

    return list(dict.fromkeys(normalized)) or list(DEFAULT_CONFERENCE_SERIES)


def conference_query_variants(query: str, conference_series: list[str] | None) -> list[str]:
    base_query = clean_text(query)
    if not base_query:
        return []

    series = normalize_conference_series(conference_series)
    variants = [base_query]
    for canonical in series:
        hint = CONFERENCE_QUERY_HINTS.get(canonical, canonical)
        variants.append(f"{base_query} {hint}".strip())
    return list(dict.fromkeys(variants))


def detect_conference_series(*texts: Any, allowed_series: list[str] | None = None) -> str | None:
    haystack = " ".join(clean_text(text).lower() for text in texts if clean_text(text))
    if not haystack:
        return None

    candidates = normalize_conference_series(allowed_series)
    for canonical in candidates:
        aliases = CONFERENCE_ALIASES.get(canonical, ())
        if any(alias in haystack for alias in aliases):
            return canonical
    return None


def looks_like_conference_record(*texts: Any, allowed_series: list[str] | None = None) -> bool:
    return detect_conference_series(*texts, allowed_series=allowed_series) is not None


def infer_presentation_type(*texts: Any) -> str | None:
    haystack = " ".join(clean_text(text) for text in texts if clean_text(text))
    if not haystack:
        return None
    for pattern, label in PRESENTATION_PATTERNS:
        if pattern.search(haystack):
            return label
    return None


def extract_abstract_number(*texts: Any) -> str | None:
    haystack = " ".join(clean_text(text) for text in texts if clean_text(text))
    if not haystack:
        return None
    for pattern in ABSTRACT_NUMBER_PATTERNS:
        match = pattern.search(haystack)
        if match is not None:
            return clean_text(match.group(1)) or None
    return None


def has_conference_artifact_signal(*texts: Any) -> bool:
    haystack = " ".join(clean_text(text).lower() for text in texts if clean_text(text))
    if not haystack:
        return False
    artifact_terms = (
        "abstract",
        "poster",
        "oral",
        "presentation",
        "late-breaking",
        "proceedings",
    )
    return any(term in haystack for term in artifact_terms)


def split_author_string(raw_authors: Any) -> list[str]:
    text = clean_text(raw_authors)
    if not text:
        return []
    separator = ";" if ";" in text else ","
    return [item.strip() for item in text.split(separator) if item.strip()]


def date_from_parts(value: Any) -> str | None:
    if not isinstance(value, list) or not value:
        return None
    first = value[0]
    if not isinstance(first, list) or not first:
        return None
    try:
        year = int(first[0])
        month = int(first[1]) if len(first) > 1 else 1
        day = int(first[2]) if len(first) > 2 else 1
        return date(year, month, day).isoformat()
    except (TypeError, ValueError):
        return None


def normalize_date(value: Any) -> str | None:
    text = clean_text(value)
    if not text:
        return None
    for pattern in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            parsed = datetime.strptime(text, pattern)
            return parsed.date().isoformat()
        except ValueError:
            continue
    return None


def normalize_doi(value: Any) -> str | None:
    text = clean_text(value)
    if not text:
        return None
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if text.lower().startswith(prefix):
            return text[len(prefix):]
    return text


def normalize_year(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    text = clean_text(value)
    if len(text) == 4 and text.isdigit():
        return int(text)
    return None


def year_from_date(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value[:4])
    except (TypeError, ValueError):
        return None


def keep_if_recent(publication_year: int | None, *, year_from: int | None) -> bool:
    if year_from is None:
        return True
    if publication_year is None:
        return False
    return publication_year >= year_from


def current_year_utc() -> int:
    return datetime.now(UTC).year
