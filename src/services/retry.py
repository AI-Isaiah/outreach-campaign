"""Retry decorator for external API calls with exponential backoff."""

from __future__ import annotations

import functools
import logging
import time
from typing import Callable, TypeVar

F = TypeVar("F", bound=Callable)

logger = logging.getLogger(__name__)


def retry_on_failure(
    max_retries: int = 3,
    backoff_base: float = 1.0,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
) -> Callable[[F], F]:
    """Retry a function on transient failures with exponential backoff.

    Args:
        max_retries: total attempts (including the first)
        backoff_base: seconds to wait after first failure (doubles each retry)
        exceptions: exception types to catch and retry
    """

    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(max_retries):
                try:
                    return fn(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if attempt < max_retries - 1:
                        wait = backoff_base * (2 ** attempt)
                        logger.warning(
                            "%s failed (attempt %d/%d), retrying in %.1fs: %s",
                            fn.__name__, attempt + 1, max_retries, wait, exc,
                        )
                        time.sleep(wait)
            raise last_exc  # type: ignore[misc]

        return wrapper  # type: ignore[return-value]

    return decorator
