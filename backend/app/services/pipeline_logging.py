"""
Track 4B: Structured logging - per version_id: counts, validation failures, runtime per stage, S3 sizes.
"""
from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


def log_stage_start(version_id: str, stage: str, **extra: Any) -> None:
    logger.info(
        "pipeline_stage_start",
        extra={
            "version_id": version_id,
            "stage": stage,
            "event": "stage_start",
            **extra,
        },
    )


def log_stage_complete(
    version_id: str,
    stage: str,
    duration_ms: int,
    counts: dict[str, int] | None = None,
    validation_failures: list | None = None,
    **extra: Any,
) -> None:
    payload: dict[str, Any] = {
        "version_id": version_id,
        "stage": stage,
        "duration_ms": duration_ms,
        "event": "stage_complete",
        **extra,
    }
    if counts:
        payload["counts"] = counts
    if validation_failures:
        payload["validation_failures"] = validation_failures
    logger.info("pipeline_stage_complete", extra=payload)


def log_stage_error(version_id: str, stage: str, error: str, **extra: Any) -> None:
    logger.error(
        "pipeline_stage_error",
        extra={
            "version_id": version_id,
            "stage": stage,
            "error": error[:500],
            "event": "stage_error",
            **extra,
        },
    )
