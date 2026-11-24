from typing import Any, Literal, overload
from .exceptions import (
    IncorrectParameters,
    UnsupportedAlgorithm,
)
from .interfaces import AlgoType
from .limiter import LeakyBucketLimiter, TokenBucketLimiter


@overload
def create_limiter(
    algo_type: Literal["leaky"],
    *,
    capacity: int,
    leak_rate: float
) -> LeakyBucketLimiter: ...

@overload
def create_limiter(
    algo_type: Literal["token"],
    *,
    capacity: int,
    refill_rate: float,
    refill_interval: float
) -> TokenBucketLimiter: ...

def create_limiter(algo_type: str, **kwargs: Any) -> AlgoType:
    if algo_type == "leaky":
        leaky_params = {"capacity","leak_rate"}
        if not kwargs.keys() == leaky_params:
            raise IncorrectParameters(f"leaky takes exactly {sorted(leaky_params)}, got {sorted(kwargs)}")
        return LeakyBucketLimiter(**kwargs)

    elif algo_type == "token":
        token_params = {"capacity","refill_rate","refill_interval"}
        if not kwargs.keys() == token_params:
            raise IncorrectParameters(f"token takes exactly {sorted(token_params)}, got {sorted(kwargs)}")
        return TokenBucketLimiter(**kwargs)

    raise UnsupportedAlgorithm(f"Unsupported algorithm: {algo_type}")
