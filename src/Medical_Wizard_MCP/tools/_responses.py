from __future__ import annotations

from typing import Any

from ._tool_catalog import OUTPUT_KIND_NOTES, get_tool_metadata


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
) -> dict[str, Any]:
    returned_sources = _unique_sources(items)
    queried_sources = sorted(set(queried_sources or []))
    source_basis = returned_sources or queried_sources
    tool_metadata = get_tool_metadata(tool_name)
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
) -> dict[str, Any]:
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
) -> dict[str, Any]:
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
        ),
        "result": item,
    }

    if item is None and missing_message is not None:
        payload["message"] = missing_message

    return payload
