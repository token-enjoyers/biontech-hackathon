from __future__ import annotations

import os


def _normalize_version(raw_version: str | None) -> str | None:
    if raw_version is None:
        return None

    version = raw_version.strip()
    if not version:
        return None

    if version.startswith("refs/tags/"):
        version = version.removeprefix("refs/tags/")

    return version or None


def get_mcp_version() -> str:
    return (
        _normalize_version(os.getenv("MCP_VERSION"))
        or _normalize_version(os.getenv("TAG_NAME"))
        or "local"
    )


def get_mcp_version_source() -> str:
    if _normalize_version(os.getenv("MCP_VERSION")):
        return "MCP_VERSION"
    if _normalize_version(os.getenv("TAG_NAME")):
        return "TAG_NAME"
    return "fallback"
