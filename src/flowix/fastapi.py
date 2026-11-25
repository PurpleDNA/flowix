import logging
from collections.abc import Callable
from typing import Any

from fastapi import Depends, HTTPException
from redis import Redis

from .engine import run_limiters
from .exceptions import BackendFailed, InvalidParameterType

logger = logging.getLogger(__name__)


def rate_limit(
    client: Redis, checks: Callable[..., Any], *, fail_open: bool = False
) -> Callable[..., None]:
    """Make a FastAPI dependency that responds 429 when any limit is reached.

    checks is itself a dependency. It returns the (key, limiter) pairs for a request.
    When Redis fails, fail_open lets the request through instead of raising.
    """
    # checked here so that mistakes show when the app starts, not on a request
    if not isinstance(client, Redis):
        raise InvalidParameterType("client must be a redis.Redis instance")
    if not callable(checks):
        raise InvalidParameterType("checks must be a function that returns (key, limiter) pairs")

    # a plain def: FastAPI runs it in a thread, so waiting on Redis never blocks the app
    def dependency(pairs: Any = Depends(checks)) -> None:
        try:
            result = run_limiters(pairs, client)
        except BackendFailed as exc:
            if not fail_open:
                raise
            logger.warning("Request allowed without rate limiting: %s", exc)
            return

        if not result["allowed"]:
            raise HTTPException(
                status_code=429,
                detail="Too many requests",
                headers={"Retry-After": str(result["retry_after"])},
            )

    return dependency
