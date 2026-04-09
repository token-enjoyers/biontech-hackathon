from __future__ import annotations

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
