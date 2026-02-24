"""
Track 4C: Retries - only for transient failures (S3, DB, timeouts).
No retries on validation or mapping inconsistency.
"""
from __future__ import annotations

import time
from typing import Callable, TypeVar

T = TypeVar("T")

TRANSIENT_EXCEPTIONS = (
    ConnectionError,
    TimeoutError,
    OSError,
)
# botocore ClientError with 5xx or throttling
try:
    from botocore.exceptions import ClientError
    TRANSIENT_EXCEPTIONS = TRANSIENT_EXCEPTIONS + (ClientError,)
except ImportError:
    pass


def with_retries(
    fn: Callable[[], T],
    max_attempts: int = 3,
    delay_sec: float = 1.0,
    backoff: float = 2.0,
) -> T:
    """Execute fn with retries on transient failures only."""
    last: BaseException | None = None
    for attempt in range(max_attempts):
        try:
            return fn()
        except Exception as e:
            last = e
            if attempt == max_attempts - 1:
                raise
            if not isinstance(e, TRANSIENT_EXCEPTIONS):
                raise
            try:
                if hasattr(e, "response") and getattr(e, "response", {}).get("Error", {}).get("Code", "").startswith("5"):
                    pass  # 5xx - retry
                elif "throttl" in str(e).lower() or "timeout" in str(e).lower():
                    pass  # retry
                else:
                    raise  # Non-transient
            except Exception:
                raise
            time.sleep(delay_sec * (backoff ** attempt))
    raise last
