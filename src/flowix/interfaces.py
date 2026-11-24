from typing import TypedDict
from .limiter import LeakyBucketLimiter, TokenBucketLimiter

AlgoType = LeakyBucketLimiter | TokenBucketLimiter


class LimitResult(TypedDict):
    allowed: bool
    retry_after: int  # seconds, 0 when allowed
