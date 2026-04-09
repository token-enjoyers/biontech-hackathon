from __future__ import annotations

import re
from typing import Any


def coalesce_indication(
    *,
    indication: str | None = None,
    condition: str | None = None,
) -> str | None:
    for value in (indication, condition):
        if isinstance(value, str):
            stripped = value.strip()
            if stripped:
                return stripped
    return None


def coalesce_query(
    *,
    query: str | None = None,
    term: str | None = None,
) -> str | None:
    for value in (query, term):
        if isinstance(value, str):
            stripped = value.strip()
            if stripped:
                return stripped
    return None


_TRIAL_QUERY_STOPWORDS = (
    "clinical trial",
    "clinical study",
    "study",
    "trial",
)


def build_trial_query_variants(query: str | None) -> list[str]:
    if not isinstance(query, str):
        return []

    original = " ".join(query.split()).strip()
    if not original:
        return []

    variants: list[str] = [original]
    lowered = original.lower()

    cleaned = lowered
    # Remove longer phrases before shorter suffixes like "trial" so
    # inputs such as "ROSETTA Lung clinical trial" normalize cleanly.
    for stopword in _TRIAL_QUERY_STOPWORDS:
        cleaned = re.sub(rf"\b{re.escape(stopword)}\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    base_forms = [original]
    if cleaned and cleaned != lowered:
        base_forms.append(_reapply_title_case(cleaned, original))

    for base in base_forms:
        variants.append(base)
        if "-" in base:
            variants.append(base.replace("-", " "))
        if " " in base:
            variants.append(re.sub(r"\s+", "-", base))

        normalized_compact = re.sub(r"[-\s]+", "", base)
        if normalized_compact and normalized_compact != base:
            variants.append(normalized_compact)

    return list(dict.fromkeys(variant.strip() for variant in variants if variant.strip()))


def _reapply_title_case(cleaned_lower: str, original: str) -> str:
    original_tokens = re.split(r"(\s+|-)", original)
    normalized_original = "".join(token.lower() for token in original_tokens if token.strip())
    normalized_cleaned = re.sub(r"[-\s]+", "", cleaned_lower)
    if normalized_cleaned and normalized_cleaned in normalized_original:
        acronym_matches = re.findall(r"[A-Z0-9][A-Za-z0-9-]*", original)
        for match in acronym_matches:
            if re.sub(r"[-\s]+", "", match).lower() == normalized_cleaned:
                return match
    return " ".join(part.capitalize() if part.isalpha() else part for part in cleaned_lower.split())


def build_literature_query(
    *,
    query: str | None = None,
    term: str | None = None,
    indication: str | None = None,
    intervention: str | None = None,
    nct_id: str | None = None,
) -> tuple[str | None, dict[str, Any]]:
    parts = [
        value.strip()
        for value in (query, term, intervention, indication, nct_id)
        if isinstance(value, str) and value.strip()
    ]
    effective_query = " ".join(dict.fromkeys(parts)) if parts else None
    requested_filters = {
        "query": query,
        "term": term,
        "indication": indication,
        "intervention": intervention,
        "nct_id": nct_id,
        "effective_query": effective_query,
    }
    return effective_query, requested_filters
