from collections.abc import Iterable
from typing import Any, Literal, overload
from redis import Redis
from redis.exceptions import RedisError
from .algorithm_lua_scripts.limiter_script import limiter_script
from .exceptions import (
    BackendFailed,
    IncorrectParameters,
    InvalidParameterType,
    InvalidParameterValue,
    UnsupportedAlgorithm,
)
from .interfaces import AlgoType, BatchLimitResult, LimitResult
from .limiter import (
    FixedWindowLimiter,
    LeakyBucketLimiter,
    SlidingCounterLimiter,
    SlidingLogLimiter,
    TokenBucketLimiter,
)

# names match the functions in the lua script, parameters are in the order they take them
_ALGORITHMS: dict[str, tuple[type[AlgoType], tuple[str, ...]]] = {
    "leaky": (LeakyBucketLimiter, ("capacity", "leak_rate")),
    "token": (TokenBucketLimiter, ("capacity", "refill_rate", "refill_interval")),
    "fixed_window": (FixedWindowLimiter, ("limit", "window")),
    "sliding_log": (SlidingLogLimiter, ("limit", "window")),
    "sliding_counter": (SlidingCounterLimiter, ("limit", "window")),
}

# the lua script reads this many parameters for every limiter
_PARAMS_PER_LIMITER = 3


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

@overload
def create_limiter(
    algo_type: Literal["fixed_window"],
    *,
    limit: int,
    window: float
) -> FixedWindowLimiter: ...

@overload
def create_limiter(
    algo_type: Literal["sliding_log"],
    *,
    limit: int,
    window: float
) -> SlidingLogLimiter: ...

@overload
def create_limiter(
    algo_type: Literal["sliding_counter"],
    *,
    limit: int,
    window: float
) -> SlidingCounterLimiter: ...

def create_limiter(algo_type: str, **kwargs: Any) -> AlgoType:
    if algo_type not in _ALGORITHMS:
        raise UnsupportedAlgorithm(f"Unsupported algorithm: {algo_type}")

    limiter_class, params = _ALGORITHMS[algo_type]
    if kwargs.keys() != set(params):
        raise IncorrectParameters(f"{algo_type} takes exactly {sorted(params)}, got {sorted(kwargs)}")
    return limiter_class(**kwargs)

def run_limiter(key: str, limiter: AlgoType, client: Redis) -> LimitResult:
    return run_limiters([(key, limiter)], client)["results"][0]

def run_limiters(checks: Iterable[tuple[str, AlgoType]], client: Redis) -> BatchLimitResult:
    if not isinstance(checks,Iterable):
        raise InvalidParameterType("checks must be (key, limiter) pairs")

    keys: list[str] = []
    args: list[str | float] = []
    for check in checks:
        if not isinstance(check,(tuple,list)) or len(check) != 2:
            raise InvalidParameterType("checks must be (key, limiter) pairs")
        key, limiter = check
        if not isinstance(limiter, AlgoType):
            raise InvalidParameterType("limiter must be an algotype")
        if not isinstance(key,str):
            raise InvalidParameterType("key must be a string")

        algo_type, params = next(
            (name, params)
            for name, (limiter_class, params) in _ALGORITHMS.items()
            if isinstance(limiter, limiter_class)
        )
        redis_key = f"flowix:{algo_type}:{key}"
        if redis_key in keys:
            # both would see the same state, and only one would be charged
            raise InvalidParameterValue(f"{algo_type} limiter with key {key!r} is repeated")
        keys.append(redis_key)
        args.append(algo_type)
        args += [getattr(limiter, param) for param in params]
        args += [0] * (_PARAMS_PER_LIMITER - len(params))

    if not keys:
        raise InvalidParameterValue("checks must not be empty")
    if not isinstance(client,Redis):
        raise InvalidParameterType("client must be a redis.Redis instance")

    try:
        raw = client.register_script(limiter_script)(keys=keys, args=args)
    except RedisError as exc:
        raise BackendFailed(f"Redis call failed: {exc}") from exc

    results: list[LimitResult] = [
        {"allowed": bool(allowed), "retry_after": retry_after}
        for allowed, retry_after in raw
    ]
    return {
        "allowed": all(result["allowed"] for result in results),
        "retry_after": max(result["retry_after"] for result in results),
        "results": results,
    }
