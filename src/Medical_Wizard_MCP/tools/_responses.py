from __future__ import annotations

import json
import logging
import time
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

from ._evidence_refs import document_refs_from_nested_data
from ._tool_catalog import OUTPUT_KIND_NOTES, get_tool_metadata


conversation_id_var: ContextVar[str | None] = ContextVar("conversation_id", default=None)
request_start_var: ContextVar[float] = ContextVar("request_start", default=0.0)

_audit_logger = logging.getLogger("gxp.audit")
if not _audit_logger.handlers:
    _handler = logging.FileHandler("audit.log", mode="a", encoding="utf-8")
    _handler.setFormatter(logging.Formatter("%(message)s"))
    _audit_logger.addHandler(_handler)
    _audit_logger.setLevel(logging.INFO)
    _audit_logger.propagate = False


def _write_audit_log(
    *,
    tool_name: str,
    requested_filters: dict[str, Any] | None,
    queried_sources: list[str] | None,
    result_count: int,
    warnings: list[dict[str, str]] | None,
) -> None:
    start = request_start_var.get()
    duration_ms = int((time.perf_counter() - start) * 1000) if start else None
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "conversation_id": conversation_id_var.get(),
        "tool": tool_name,
        "inputs": {k: v for k, v in (requested_filters or {}).items() if v is not None},
        "queried_sources": queried_sources or [],
        "result_count": result_count,
        "partial_failures": len(warnings or []),
        "status": "partial" if warnings else "success",
        "duration_ms": duration_ms,
    }
    _audit_logger.info(json.dumps(entry, ensure_ascii=False))


def _unique_sources(items: list[dict[str, Any]]) -> list[str]:
    return sorted(
        {
            item.get("source")
            for item in items
            if isinstance(item, dict) and isinstance(item.get("source"), str) and item["source"]
        }
    )


def _compact_filters(filters: dict[str, Any] | None) -> dict[str, Any]:
    if not filters:
        return {}
    return {
        key: value
        for key, value in filters.items()
        if value is not None and value != ""
    }


def _normalize_source_list(sources: list[str] | None) -> list[str]:
    return sorted({source for source in (sources or []) if isinstance(source, str) and source})


def _normalize_evidence_trace(
    trace: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in trace or []:
        if not isinstance(item, dict):
            continue
        step = item.get("step")
        if not isinstance(step, str) or not step:
            continue

        entry: dict[str, Any] = {"step": step}
        sources = _normalize_source_list(item.get("sources"))
        if sources:
            entry["sources"] = sources

        if isinstance(item.get("note"), str) and item["note"]:
            entry["note"] = item["note"]

        filters = _compact_filters(item.get("filters"))
        if filters:
            entry["filters"] = filters

        if isinstance(item.get("output_kind"), str) and item["output_kind"]:
            entry["output_kind"] = item["output_kind"]

        raw_refs = item.get("refs")
        refs = document_refs_from_nested_data(raw_refs)
        if not refs and isinstance(raw_refs, list):
            normalized_refs = []
            for ref in raw_refs:
                if not isinstance(ref, dict):
                    continue
                if all(isinstance(ref.get(key), str) and ref[key] for key in ("source", "id", "label", "url")):
                    normalized_refs.append(
                        {
                            "source": ref["source"],
                            "id": ref["id"],
                            "label": ref["label"],
                            "url": ref["url"],
                        }
                    )
            refs = sorted(normalized_refs, key=lambda ref: (ref["source"], ref["id"]))
        if refs:
            entry["evidence_refs"] = refs

        normalized.append(entry)
    return normalized


def _list_meta(
    *,
    tool_name: str,
    data_type: str,
    items: list[dict[str, Any]],
    quality_note: str,
    coverage: str,
    queried_sources: list[str] | None = None,
    warnings: list[dict[str, str]] | None = None,
    requested_filters: dict[str, Any] | None = None,
    evidence_sources: list[str] | None = None,
    evidence_trace: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    returned_sources = _unique_sources(items)
    queried_sources = _normalize_source_list(queried_sources)
    normalized_trace = _normalize_evidence_trace(evidence_trace)
    trace_sources = sorted(
        {
            source
            for step in normalized_trace
            for source in step.get("sources", [])
            if isinstance(source, str) and source
        }
    )
    trace_refs = sorted(
        {
            (ref["source"], ref["id"], ref["label"], ref["url"])
            for step in normalized_trace
            for ref in step.get("evidence_refs", [])
            if all(isinstance(ref.get(key), str) and ref[key] for key in ("source", "id", "label", "url"))
        }
    )
    item_refs = document_refs_from_nested_data(items)
    evidence_sources = _normalize_source_list(evidence_sources)
    evidence_basis = sorted(set(evidence_sources + returned_sources + queried_sources + trace_sources))
    source_basis = returned_sources or queried_sources
    tool_metadata = get_tool_metadata(tool_name)
    if not normalized_trace and evidence_basis:
        fallback_step: dict[str, Any] = {
            "step": "tool_result",
            "sources": evidence_basis,
            "note": "Result assembled from the relevant sources reported for this tool call.",
        }
        if tool_metadata and isinstance(tool_metadata.get("output_kind"), str):
            fallback_step["output_kind"] = tool_metadata["output_kind"]
        normalized_trace = [fallback_step]
    if len(source_basis) == 1:
        source_label = source_basis[0]
    elif len(source_basis) > 1:
        source_label = "multi-source"
    else:
        source_label = "unknown"

    meta = {
        "tool": tool_name,
        "source": source_label,
        "sources": returned_sources,
        "returned_sources": returned_sources,
        "queried_sources": queried_sources,
        "evidence_sources": evidence_basis,
        "evidence_refs": [
            {
                "source": source,
                "id": doc_id,
                "label": label,
                "url": url,
            }
            for source, doc_id, label, url in sorted(
                {
                    (ref["source"], ref["id"], ref["label"], ref["url"])
                    for ref in item_refs
                }.union(trace_refs)
            )
        ],
        "evidence_trace": normalized_trace,
        "data_type": data_type,
        "result_schema_version": "2.0",
        "quality_note": quality_note,
        "coverage": coverage,
        "requested_filters": _compact_filters(requested_filters),
        "partial_failures": warnings or [],
    }
    if tool_metadata:
        output_kind = tool_metadata.get("output_kind")
        meta["tool_category"] = tool_metadata.get("category")
        meta["tool_family"] = tool_metadata.get("family")
        meta["output_kind"] = output_kind
        meta["workflow_position"] = tool_metadata.get("workflow_position")
        meta["stability"] = tool_metadata.get("stability")
        meta["interpretation_note"] = OUTPUT_KIND_NOTES.get(output_kind, "")
        meta["routing_hints"] = {
            "canonical_parameters": tool_metadata.get("canonical_parameters", []),
            "parameter_aliases": tool_metadata.get("parameter_aliases", {}),
            "requires_identifiers": tool_metadata.get("requires_identifiers", []),
            "use_when": tool_metadata.get("use_when", []),
            "avoid_when": tool_metadata.get("avoid_when", []),
            "typical_next_tools": tool_metadata.get("typical_next_tools", []),
        }
        if tool_metadata.get("deprecated"):
            meta["deprecation"] = {
                "deprecated": True,
                "replacement_tool": tool_metadata.get("replacement_tool"),
            }
    return meta


def list_response(
    *,
    tool_name: str,
    data_type: str,
    items: list[dict[str, Any]],
    quality_note: str,
    coverage: str,
    queried_sources: list[str] | None = None,
    warnings: list[dict[str, str]] | None = None,
    requested_filters: dict[str, Any] | None = None,
    evidence_sources: list[str] | None = None,
    evidence_trace: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    _write_audit_log(
        tool_name=tool_name,
        requested_filters=requested_filters,
        queried_sources=queried_sources,
        result_count=len(items),
        warnings=warnings,
    )
    return {
        "_meta": _list_meta(
            tool_name=tool_name,
            data_type=data_type,
            items=items,
            quality_note=quality_note,
            coverage=coverage,
            queried_sources=queried_sources,
            warnings=warnings,
            requested_filters=requested_filters,
            evidence_sources=evidence_sources,
            evidence_trace=evidence_trace,
        ),
        "count": len(items),
        "results": items,
    }


def detail_response(
    *,
    tool_name: str,
    data_type: str,
    item: dict[str, Any] | None,
    quality_note: str,
    coverage: str,
    missing_message: str | None = None,
    queried_sources: list[str] | None = None,
    warnings: list[dict[str, str]] | None = None,
    requested_filters: dict[str, Any] | None = None,
    evidence_sources: list[str] | None = None,
    evidence_trace: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    _write_audit_log(
        tool_name=tool_name,
        requested_filters=requested_filters,
        queried_sources=queried_sources,
        result_count=1 if item is not None else 0,
        warnings=warnings,
    )
    items = [item] if item is not None else []
    payload: dict[str, Any] = {
        "_meta": _list_meta(
            tool_name=tool_name,
            data_type=data_type,
            items=items,
            quality_note=quality_note,
            coverage=coverage,
            queried_sources=queried_sources,
            warnings=warnings,
            requested_filters=requested_filters,
            evidence_sources=evidence_sources,
            evidence_trace=evidence_trace,
        ),
        "result": item,
    }

    if item is None and missing_message is not None:
        payload["message"] = missing_message

    return payload
