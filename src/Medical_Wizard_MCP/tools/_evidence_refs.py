from __future__ import annotations

from collections.abc import Iterable
from typing import Any
from urllib.parse import quote


def make_document_ref(
    *,
    source: str,
    doc_id: str,
    label: str,
    url: str,
) -> dict[str, str]:
    return {
        "source": source,
        "id": doc_id,
        "label": label,
        "url": url,
    }


def _clean_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _clinicaltrials_ref(payload: dict[str, Any]) -> dict[str, str] | None:
    nct_id = _clean_string(payload.get("nct_id"))
    if not nct_id:
        return None
    label = (
        _clean_string(payload.get("brief_title"))
        or _clean_string(payload.get("official_title"))
        or nct_id
    )
    return make_document_ref(
        source="clinicaltrials_gov",
        doc_id=nct_id,
        label=label,
        url=f"https://clinicaltrials.gov/study/{quote(nct_id)}",
    )


def _pubmed_ref(payload: dict[str, Any]) -> dict[str, str] | None:
    pmid = _clean_string(payload.get("pmid"))
    doi = _clean_string(payload.get("doi"))
    title = _clean_string(payload.get("title")) or pmid or doi
    if pmid:
        return make_document_ref(
            source="pubmed",
            doc_id=pmid,
            label=title or pmid,
            url=f"https://pubmed.ncbi.nlm.nih.gov/{quote(pmid)}/",
        )
    if doi:
        return make_document_ref(
            source="pubmed",
            doc_id=doi,
            label=title or doi,
            url=f"https://doi.org/{quote(doi, safe='/')}",
        )
    return None


def _medrxiv_ref(payload: dict[str, Any]) -> dict[str, str] | None:
    doi = _clean_string(payload.get("doi"))
    title = _clean_string(payload.get("title")) or doi
    if not doi:
        return None
    return make_document_ref(
        source="medrxiv",
        doc_id=doi,
        label=title or doi,
        url=f"https://doi.org/{quote(doi, safe='/')}",
    )


def _openfda_ref(payload: dict[str, Any]) -> dict[str, str] | None:
    approval_id = _clean_string(payload.get("approval_id"))
    if not approval_id:
        return None
    label = (
        _clean_string(payload.get("brand_name"))
        or _clean_string(payload.get("generic_name"))
        or approval_id
    )
    query = quote(f'openfda.application_number:"{approval_id}"', safe="")
    return make_document_ref(
        source="openfda",
        doc_id=approval_id,
        label=label,
        url=f"https://api.fda.gov/drug/label.json?search={query}",
    )


def _generic_source_ref(payload: dict[str, Any]) -> dict[str, str] | None:
    source = _clean_string(payload.get("source"))
    source_id = _clean_string(payload.get("source_id")) or _clean_string(payload.get("doi"))
    label = _clean_string(payload.get("title")) or _clean_string(payload.get("conference_name")) or source_id
    doi = _clean_string(payload.get("doi"))
    url = (
        _clean_string(payload.get("url"))
        or (
            doi
            if doi and doi.startswith(("https://doi.org/", "http://doi.org/"))
            else f"https://doi.org/{quote(doi, safe='/')}"
            if doi
            else None
        )
    )
    if not source or not source_id or not label or not url:
        return None
    return make_document_ref(
        source=source,
        doc_id=source_id,
        label=label,
        url=url,
    )


def document_ref_from_payload(payload: dict[str, Any]) -> dict[str, str] | None:
    source = _clean_string(payload.get("source"))
    if source == "clinicaltrials_gov":
        return _clinicaltrials_ref(payload)
    if source == "pubmed":
        return _pubmed_ref(payload)
    if source == "medrxiv":
        return _medrxiv_ref(payload)
    if source == "openfda":
        return _openfda_ref(payload)

    if payload.get("nct_id"):
        return _clinicaltrials_ref(payload)
    if payload.get("pmid"):
        return _pubmed_ref(payload)
    if payload.get("doi") and _clean_string(payload.get("journal")) == "medRxiv":
        return _medrxiv_ref(payload)
    if payload.get("approval_id"):
        return _openfda_ref(payload)
    return _generic_source_ref(payload)


def _walk_for_document_refs(value: Any, refs: dict[tuple[str, str], dict[str, str]]) -> None:
    if isinstance(value, dict):
        ref = document_ref_from_payload(value)
        if ref is not None:
            refs[(ref["source"], ref["id"])] = ref
        for nested in value.values():
            _walk_for_document_refs(nested, refs)
        return

    if isinstance(value, list):
        for item in value:
            _walk_for_document_refs(item, refs)


def document_refs_from_nested_data(value: Any) -> list[dict[str, str]]:
    refs: dict[tuple[str, str], dict[str, str]] = {}
    _walk_for_document_refs(value, refs)
    return sorted(refs.values(), key=lambda ref: (ref["source"], ref["id"]))


def document_refs_from_models(items: Iterable[Any]) -> list[dict[str, str]]:
    payloads: list[dict[str, Any]] = []
    for item in items:
        if hasattr(item, "model_dump"):
            payload = item.model_dump()
        elif isinstance(item, dict):
            payload = item
        else:
            continue
        if isinstance(payload, dict):
            payloads.append(payload)
    return document_refs_from_nested_data(payloads)
