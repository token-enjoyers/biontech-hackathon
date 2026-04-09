from __future__ import annotations

from collections import Counter
from typing import Any

from .._mcp import mcp
from ..sources import registry
from ._evidence_extraction import (
    build_document,
    classify_claim_passage,
    extract_structured_findings,
    find_matching_passages,
)
from ._evidence_quality import annotate_evidence_quality, summarize_evidence_quality
from ._responses import detail_response, list_response


def _warning_dicts(*warning_lists: list[Any]) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    for warning_list in warning_lists:
        for warning in warning_list:
            if hasattr(warning, "as_dict"):
                warnings.append(warning.as_dict())
            elif isinstance(warning, dict):
                warnings.append(warning)
    return warnings


def _trace_step(
    step: str,
    *,
    sources: list[str] | None,
    note: str,
    filters: dict[str, Any] | None,
    output_kind: str,
    refs: Any = None,
) -> dict[str, Any]:
    trace = {
        "step": step,
        "sources": sorted(set(sources or [])),
        "note": note,
        "filters": {
            key: value
            for key, value in (filters or {}).items()
            if value is not None and value != "" and value != []
        },
        "output_kind": output_kind,
    }
    if refs is not None:
        trace["refs"] = refs
    return trace


def _payload(item: Any) -> dict[str, Any] | None:
    if hasattr(item, "model_dump"):
        value = item.model_dump()
        return value if isinstance(value, dict) else None
    if isinstance(item, dict):
        return item
    return None


def _dedupe_payloads(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[tuple[str, str], dict[str, Any]] = {}
    passthrough: list[dict[str, Any]] = []
    for item in items:
        source = str(item.get("source") or "")
        identifier = (
            str(item.get("nct_id") or "")
            or str(item.get("pmid") or "")
            or str(item.get("doi") or "")
            or str(item.get("approval_id") or "")
        )
        if source and identifier:
            deduped[(source, identifier)] = item
        else:
            passthrough.append(item)
    return list(deduped.values()) + passthrough


async def _collect_documents(
    *,
    query: str | None,
    indication: str | None,
    intervention: str | None,
    nct_id: str | None,
    include_preprints: bool,
    include_approvals: bool,
    max_documents: int,
) -> tuple[list[dict[str, Any]], list[dict[str, str]], list[str], list[dict[str, Any]]]:
    documents: list[dict[str, Any]] = []
    warnings: list[dict[str, str]] = []
    queried_sources: set[str] = set()
    trace: list[dict[str, Any]] = []

    trial_detail = None
    search_query = " ".join(part for part in [query, intervention, indication] if part).strip()

    if nct_id:
        detail = await registry.get_trial_details(nct_id)
        warnings.extend(_warning_dicts(detail.warnings))
        queried_sources.update(detail.queried_sources)
        if detail.item is not None:
            trial_detail = detail.item.model_dump()
            documents.append(trial_detail)
            trace.append(
                _trace_step(
                    "fetch_trial_detail",
                    sources=detail.queried_sources,
                    note="Loaded the requested trial detail as an auditable source document.",
                    filters={"nct_id": nct_id},
                    output_kind="raw",
                    refs=[trial_detail],
                )
            )
            if not indication and trial_detail.get("conditions"):
                conditions = trial_detail.get("conditions")
                if isinstance(conditions, list) and conditions:
                    indication = str(conditions[0])
            if not intervention and trial_detail.get("interventions"):
                interventions = trial_detail.get("interventions")
                if isinstance(interventions, list) and interventions:
                    intervention = str(interventions[0])
            search_query = " ".join(
                part
                for part in [query, nct_id, intervention, indication]
                if isinstance(part, str) and part.strip()
            ).strip()

    if search_query:
        publication_response = await registry.search_publications(
            query=search_query,
            max_results=max_documents,
            year_from=2018,
        )
        publication_payload = [_payload(item) for item in publication_response.items]
        publication_payload = [item for item in publication_payload if item is not None]
        documents.extend(publication_payload)
        warnings.extend(_warning_dicts(publication_response.warnings))
        queried_sources.update(publication_response.queried_sources)
        trace.append(
            _trace_step(
                "search_publications",
                sources=publication_response.queried_sources,
                note="Fetched peer-reviewed documents for audit and evidence extraction.",
                filters={"query": search_query, "year_from": 2018, "max_results": max_documents},
                output_kind="raw",
                refs=publication_payload,
            )
        )

        if include_preprints:
            preprint_response = await registry.search_preprints(
                query=search_query,
                max_results=max_documents,
                year_from=2022,
            )
            preprint_payload = [_payload(item) for item in preprint_response.items]
            preprint_payload = [item for item in preprint_payload if item is not None]
            documents.extend(preprint_payload)
            warnings.extend(_warning_dicts(preprint_response.warnings))
            queried_sources.update(preprint_response.queried_sources)
            trace.append(
                _trace_step(
                    "search_preprints",
                    sources=preprint_response.queried_sources,
                    note="Fetched preprints for early-signal audit context.",
                    filters={"query": search_query, "year_from": 2022, "max_results": max_documents},
                    output_kind="raw",
                    refs=preprint_payload,
                )
            )

    if include_approvals and indication:
        approval_response = await registry.search_approved_drugs(
            indication=indication,
            intervention=intervention,
            max_results=max_documents,
        )
        approval_payload = [_payload(item) for item in approval_response.items]
        approval_payload = [item for item in approval_payload if item is not None]
        documents.extend(approval_payload)
        warnings.extend(_warning_dicts(approval_response.warnings))
        queried_sources.update(approval_response.queried_sources)
        trace.append(
            _trace_step(
                "search_approved_drugs",
                sources=approval_response.queried_sources,
                note="Fetched approved-drug label documents for comparative evidence and safety context.",
                filters={"indication": indication, "intervention": intervention, "max_results": max_documents},
                output_kind="raw",
                refs=approval_payload,
            )
        )

    return _dedupe_payloads(documents), warnings, sorted(queried_sources), trace


@mcp.tool()
async def get_document_passages(
    query: str,
    indication: str | None = None,
    intervention: str | None = None,
    nct_id: str | None = None,
    include_preprints: bool = True,
    include_approvals: bool = True,
    max_documents: int = 5,
    max_passages: int = 8,
) -> dict[str, Any]:
    """On-demand passage retrieval for claim audits and follow-up questions.

Use this only when the user explicitly asks where a statement comes from, wants supporting passages, or needs a drilldown into the retrieved documents.
    """
    documents, warnings, queried_sources, trace = await _collect_documents(
        query=query,
        indication=indication,
        intervention=intervention,
        nct_id=nct_id,
        include_preprints=include_preprints,
        include_approvals=include_approvals,
        max_documents=max_documents,
    )

    passages: list[dict[str, Any]] = []
    for document in (build_document(item) for item in documents):
        passages.extend(
            find_matching_passages(document, query=query, max_passages=max_passages)
        )

    passages.sort(
        key=lambda item: (
            -float(item.get("relevance_score", 0)),
            -float(item.get("evidence_quality_score", 0)),
            str(item.get("document_id") or ""),
        )
    )
    passages = passages[:max_passages]

    return list_response(
        tool_name="get_document_passages",
        data_type="document_passages",
        items=passages,
        quality_note="Passages are selected by lexical query matching over the text that is directly available from registry, abstract, or label fields.",
        coverage="ClinicalTrials.gov detail text, PubMed abstracts, medRxiv abstracts, and OpenFDA label text when available.",
        queried_sources=queried_sources,
        warnings=warnings,
        evidence_sources=queried_sources,
        evidence_trace=[
            *trace,
            _trace_step(
                "rank_matching_passages",
                sources=queried_sources,
                note="Ranked passages using lexical overlap between the user query and available document text.",
                filters={
                    "query": query,
                    "indication": indication,
                    "intervention": intervention,
                    "nct_id": nct_id,
                    "max_documents": max_documents,
                    "max_passages": max_passages,
                },
                output_kind="derived",
                refs=passages,
            ),
        ],
        requested_filters={
            "query": query,
            "indication": indication,
            "intervention": intervention,
            "nct_id": nct_id,
            "include_preprints": include_preprints,
            "include_approvals": include_approvals,
            "max_documents": max_documents,
            "max_passages": max_passages,
        },
    )


@mcp.tool()
async def extract_structured_evidence(
    query: str | None = None,
    indication: str | None = None,
    intervention: str | None = None,
    nct_id: str | None = None,
    include_preprints: bool = True,
    include_approvals: bool = True,
    max_documents: int = 5,
) -> dict[str, Any]:
    """Structured evidence extraction from auditable source text.

Use this when the user explicitly wants atomic findings such as endpoints, percentages, durations, hazard ratios, biomarker mentions, or safety signals instead of only raw documents.
    """
    if not any(value for value in [query, indication, intervention, nct_id]):
        return detail_response(
            tool_name="extract_structured_evidence",
            data_type="structured_evidence",
            item=None,
            quality_note="Structured extraction needs either a query, an indication/intervention scope, or a concrete NCT ID.",
            coverage="ClinicalTrials.gov detail text, PubMed abstracts, medRxiv abstracts, and OpenFDA label text when available.",
            missing_message="Provide at least one of `query`, `indication`, `intervention`, or `nct_id`.",
            warnings=[
                {
                    "source": "tool_validation",
                    "stage": "validate_scope",
                    "error": "No scope was provided for structured evidence extraction.",
                }
            ],
            requested_filters={
                "query": query,
                "indication": indication,
                "intervention": intervention,
                "nct_id": nct_id,
            },
            evidence_sources=["tool_validation"],
            evidence_trace=[
                _trace_step(
                    "validate_extraction_scope",
                    sources=["tool_validation"],
                    note="Rejected the request because no extraction scope was provided.",
                    filters={"query": query, "indication": indication, "intervention": intervention, "nct_id": nct_id},
                    output_kind="raw",
                    refs=[],
                )
            ],
        )

    documents, warnings, queried_sources, trace = await _collect_documents(
        query=query,
        indication=indication,
        intervention=intervention,
        nct_id=nct_id,
        include_preprints=include_preprints,
        include_approvals=include_approvals,
        max_documents=max_documents,
    )
    built_documents = [build_document(item) for item in documents]
    built_documents.sort(
        key=lambda item: (
            -float(item.get("evidence_quality_score", 0)),
            str(item.get("document_id") or ""),
        )
    )
    findings: list[dict[str, Any]] = []
    for document in built_documents[:max_documents]:
        findings.extend(extract_structured_findings(document))

    endpoint_counter = Counter(str(item.get("endpoint_name") or "unknown") for item in findings)
    type_counter = Counter(str(item.get("endpoint_type") or "unknown") for item in findings)
    result = {
        "scope": {
            "query": query,
            "indication": indication,
            "intervention": intervention,
            "nct_id": nct_id,
        },
        "documents_analyzed": [
            {
                "source": document.get("source"),
                "document_id": document.get("document_id"),
                "document_label": document.get("document_label"),
                "document_url": document.get("document_url"),
                "evidence_quality_tier": document.get("evidence_quality_tier"),
                "evidence_quality_score": document.get("evidence_quality_score"),
            }
            for document in built_documents[:max_documents]
        ],
        "evidence_quality_summary": summarize_evidence_quality(
            [
                {
                    "source": document.get("source"),
                    "document_id": document.get("document_id"),
                    "evidence_quality_tier": document.get("evidence_quality_tier"),
                    "evidence_quality_score": document.get("evidence_quality_score"),
                }
                for document in built_documents[:max_documents]
            ]
        ),
        "finding_summary": {
            "finding_count": len(findings),
            "top_endpoints": [
                {"endpoint_name": endpoint, "count": count}
                for endpoint, count in endpoint_counter.most_common(8)
            ],
            "counts_by_type": dict(type_counter),
        },
        "findings": findings[:50],
    }

    return detail_response(
        tool_name="extract_structured_evidence",
        data_type="structured_evidence",
        item=result,
        quality_note="Structured findings are extracted deterministically from the text that is directly available in registry, abstract, or label fields. They are useful for audit and summarization but do not replace full manual review.",
        coverage="ClinicalTrials.gov detail text, PubMed abstracts, medRxiv abstracts, and OpenFDA label text when available.",
        queried_sources=queried_sources,
        warnings=warnings,
        evidence_sources=queried_sources,
        evidence_trace=[
            *trace,
            _trace_step(
                "extract_structured_findings",
                sources=queried_sources,
                note="Parsed endpoint, value, biomarker, and safety-like findings from the directly available source text using deterministic patterns.",
                filters={
                    "query": query,
                    "indication": indication,
                    "intervention": intervention,
                    "nct_id": nct_id,
                    "max_documents": max_documents,
                },
                output_kind="derived",
                refs=result["findings"],
            ),
        ],
        requested_filters={
            "query": query,
            "indication": indication,
            "intervention": intervention,
            "nct_id": nct_id,
            "include_preprints": include_preprints,
            "include_approvals": include_approvals,
            "max_documents": max_documents,
        },
    )


@mcp.tool()
async def verify_claim_evidence(
    claim: str,
    indication: str | None = None,
    intervention: str | None = None,
    nct_id: str | None = None,
    include_preprints: bool = True,
    include_approvals: bool = True,
    max_documents: int = 6,
    max_passages: int = 10,
) -> dict[str, Any]:
    """Claim verifier / evidence binder.

Use this only when the user explicitly asks where a claim is supported, contradicted, or anchored in the available evidence.
    """
    documents, warnings, queried_sources, trace = await _collect_documents(
        query=claim,
        indication=indication,
        intervention=intervention,
        nct_id=nct_id,
        include_preprints=include_preprints,
        include_approvals=include_approvals,
        max_documents=max_documents,
    )
    passages: list[dict[str, Any]] = []
    for document in (build_document(item) for item in documents):
        for passage in find_matching_passages(document, query=claim, max_passages=max_passages):
            passage["classification"] = classify_claim_passage(claim, passage["passage"])
            passages.append(passage)

    passages.sort(
        key=lambda item: (
            {"supporting": 0, "conflicting": 1, "unclear": 2}.get(str(item.get("classification")), 3),
            -float(item.get("relevance_score", 0)),
            -float(item.get("evidence_quality_score", 0)),
        )
    )
    passages = passages[:max_passages]

    supporting = [item for item in passages if item.get("classification") == "supporting"]
    conflicting = [item for item in passages if item.get("classification") == "conflicting"]
    unclear = [item for item in passages if item.get("classification") == "unclear"]

    if supporting and conflicting:
        verdict = "mixed"
    elif supporting:
        verdict = "supported"
    elif conflicting:
        verdict = "not_supported"
    else:
        verdict = "insufficient_evidence"

    evidence_documents = annotate_evidence_quality(documents, sort_desc=True)
    result = {
        "claim": claim,
        "verdict": verdict,
        "verification_method": "lexical_overlap_plus_direction_rules",
        "scope": {
            "indication": indication,
            "intervention": intervention,
            "nct_id": nct_id,
        },
        "evidence_quality_summary": summarize_evidence_quality(evidence_documents),
        "supporting_evidence": supporting,
        "conflicting_evidence": conflicting,
        "unclear_evidence": unclear,
        "documents_considered": evidence_documents[:max_documents],
    }

    return detail_response(
        tool_name="verify_claim_evidence",
        data_type="claim_verification",
        item=result,
        quality_note="Claim verification is deterministic and conservative: it binds the claim to matching passages and uses simple direction rules, so the output should be treated as an audit aid rather than a final scientific judgment.",
        coverage="ClinicalTrials.gov detail text, PubMed abstracts, medRxiv abstracts, and OpenFDA label text when available.",
        queried_sources=queried_sources,
        warnings=warnings,
        evidence_sources=queried_sources,
        evidence_trace=[
            *trace,
            _trace_step(
                "bind_claim_to_passages",
                sources=queried_sources,
                note="Matched the claim against available passages and assigned supporting, conflicting, or unclear labels using deterministic direction rules.",
                filters={
                    "claim": claim,
                    "indication": indication,
                    "intervention": intervention,
                    "nct_id": nct_id,
                    "max_documents": max_documents,
                    "max_passages": max_passages,
                },
                output_kind="derived",
                refs=passages,
            ),
        ],
        requested_filters={
            "claim": claim,
            "indication": indication,
            "intervention": intervention,
            "nct_id": nct_id,
            "include_preprints": include_preprints,
            "include_approvals": include_approvals,
            "max_documents": max_documents,
            "max_passages": max_passages,
        },
    )
