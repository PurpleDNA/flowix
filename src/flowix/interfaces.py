from typing import TypedDict
from .limiter import (
    FixedWindowLimiter,
    LeakyBucketLimiter,
    SlidingCounterLimiter,
    SlidingLogLimiter,
    TokenBucketLimiter,
)

AlgoType = (
    LeakyBucketLimiter
    | TokenBucketLimiter
    | FixedWindowLimiter
    | SlidingLogLimiter
    | SlidingCounterLimiter
)


class LimitResult(TypedDict):
    allowed: bool
    retry_after: int  # seconds, 0 when allowed


class BatchLimitResult(TypedDict):
    allowed: bool  # True only if every limiter allowed the request
    retry_after: int  # seconds until every limiter has room, 0 when allowed
    results: list[LimitResult]  # one per limiter, in the order they were given
