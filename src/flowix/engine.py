from typing import Any, Literal, overload
from redis import Redis
from redis.exceptions import RedisError
from .algorithm_lua_scripts.leaky_bucket import leaky_bucket_script
from .algorithm_lua_scripts.token_bucket import token_bucket_script
from .exceptions import (
    BackendFailed,
    IncorrectParameters,
    InvalidParameterType,
    UnsupportedAlgorithm,
)
from .interfaces import AlgoType, LimitResult
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

def run_limiter(key: str, limiter: AlgoType, client: Redis) -> LimitResult:
    if not isinstance(limiter, AlgoType):
        raise InvalidParameterType("limiter must be an algotype")
    if not isinstance(key,str):
        raise InvalidParameterType("key must be a string")
    if not isinstance(client,Redis):
        raise InvalidParameterType("client must be a redis.Redis instance")
    try:
        if isinstance(limiter, TokenBucketLimiter):
            # order must match ARGV[1..3] in the lua script
            args = [
                limiter.capacity,
                limiter.refill_rate,
                limiter.refill_interval,
            ]
            token_bucket = client.register_script(token_bucket_script)
            allowed, retry_after = token_bucket(keys=[f"flowix:token:{key}"],args=args)
        else:
            # order must match ARGV[1..2] in the lua script
            args = [limiter.capacity, limiter.leak_rate]
            leaky_bucket = client.register_script(leaky_bucket_script)
            allowed, retry_after = leaky_bucket(keys=[f"flowix:leaky:{key}"],args=args)
    except RedisError as exc:
        raise BackendFailed(f"Redis call failed: {exc}") from exc

    return {"allowed": bool(allowed), "retry_after": retry_after}
