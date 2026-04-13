from __future__ import annotations

import math
import os

import httpx


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value >= 0 else default


HTTP_CONNECT_TIMEOUT_SECONDS = _env_float("MEDICAL_WIZARD_HTTP_CONNECT_TIMEOUT_SECONDS", 5.0)
HTTP_READ_TIMEOUT_SECONDS = _env_float("MEDICAL_WIZARD_HTTP_READ_TIMEOUT_SECONDS", 8.0)
HTTP_WRITE_TIMEOUT_SECONDS = _env_float("MEDICAL_WIZARD_HTTP_WRITE_TIMEOUT_SECONDS", 8.0)
HTTP_POOL_TIMEOUT_SECONDS = _env_float("MEDICAL_WIZARD_HTTP_POOL_TIMEOUT_SECONDS", 5.0)
SOURCE_CALL_TIMEOUT_SECONDS = _env_float("MEDICAL_WIZARD_SOURCE_CALL_TIMEOUT_SECONDS", 12.0)
CURL_MAX_TIME_SECONDS = _env_float("MEDICAL_WIZARD_CURL_MAX_TIME_SECONDS", 12.0)
CURL_PROCESS_TIMEOUT_SECONDS = _env_float("MEDICAL_WIZARD_CURL_PROCESS_TIMEOUT_SECONDS", 15.0)
SOURCE_TIMEOUT_RETRIES = _env_int("MEDICAL_WIZARD_SOURCE_TIMEOUT_RETRIES", 1)
SOURCE_TIMEOUT_BACKOFF_BASE_SECONDS = _env_float(
    "MEDICAL_WIZARD_SOURCE_TIMEOUT_BACKOFF_BASE_SECONDS",
    0.75,
)
SOURCE_TIMEOUT_BACKOFF_MAX_SECONDS = _env_float(
    "MEDICAL_WIZARD_SOURCE_TIMEOUT_BACKOFF_MAX_SECONDS",
    4.0,
)


class SourceTimeoutError(RuntimeError):
    """Raised when a source-specific timeout occurs and the call may be retried."""


def build_http_timeout(
    *,
    connect_seconds: float | None = None,
    read_seconds: float | None = None,
    write_seconds: float | None = None,
    pool_seconds: float | None = None,
) -> httpx.Timeout:
    return httpx.Timeout(
        connect=connect_seconds if connect_seconds is not None else HTTP_CONNECT_TIMEOUT_SECONDS,
        read=read_seconds if read_seconds is not None else HTTP_READ_TIMEOUT_SECONDS,
        write=write_seconds if write_seconds is not None else HTTP_WRITE_TIMEOUT_SECONDS,
        pool=pool_seconds if pool_seconds is not None else HTTP_POOL_TIMEOUT_SECONDS,
    )


def format_source_timeout_message(source: str, stage: str, timeout_seconds: float) -> str:
    return f"{source} {stage} timed out after {timeout_seconds:.1f}s"


def timeout_backoff_seconds(attempt_number: int) -> float:
    if attempt_number <= 0:
        return 0.0
    delay = SOURCE_TIMEOUT_BACKOFF_BASE_SECONDS * math.pow(2, attempt_number - 1)
    return round(min(delay, SOURCE_TIMEOUT_BACKOFF_MAX_SECONDS), 2)
