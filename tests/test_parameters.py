import pytest
import redis.asyncio
from redis import Redis

import flowix
from flowix import create_limiter, run_limiter

LEAKY = {"capacity": 2, "leak_rate": 1}
TOKEN = {"capacity": 2, "refill_rate": 1, "refill_interval": 1}
WINDOW = {"limit": 2, "window": 1}
WINDOW_ALGOS = ["fixed_window", "sliding_log", "sliding_counter"]


def test_everything_in_all_is_exported():
    for name in flowix.__all__:
        assert hasattr(flowix, name)


def test_creates_the_right_limiter():
    assert isinstance(create_limiter("leaky", **LEAKY), flowix.LeakyBucketLimiter)
    assert isinstance(create_limiter("token", **TOKEN), flowix.TokenBucketLimiter)
    assert isinstance(create_limiter("fixed_window", **WINDOW), flowix.FixedWindowLimiter)
    assert isinstance(create_limiter("sliding_log", **WINDOW), flowix.SlidingLogLimiter)
    assert isinstance(create_limiter("sliding_counter", **WINDOW), flowix.SlidingCounterLimiter)


def test_unsupported_algorithm():
    with pytest.raises(flowix.UnsupportedAlgorithm):
        create_limiter("nope")


@pytest.mark.parametrize("algo, params", [
    ("leaky", {"capacity": 2}),
    ("leaky", {**LEAKY, "refill_rate": 1}),
    ("token", {"capacity": 2, "leak_rate": 1}),
    *[(algo, {"limit": 2}) for algo in WINDOW_ALGOS],
    *[(algo, {**WINDOW, "capacity": 2}) for algo in WINDOW_ALGOS],
])
def test_missing_or_extra_parameters(algo, params):
    with pytest.raises(flowix.IncorrectParameters):
        create_limiter(algo, **params)


@pytest.mark.parametrize("algo, params", [
    ("leaky", LEAKY),
    ("token", TOKEN),
    *[(algo, WINDOW) for algo in WINDOW_ALGOS],
])
def test_wrong_types_and_non_positive_values(algo, params):
    for name in params:
        with pytest.raises(flowix.InvalidParameterType):
            create_limiter(algo, **{**params, name: "1"})
        for value in (0, -1):
            with pytest.raises(flowix.InvalidParameterValue):
                create_limiter(algo, **{**params, name: value})


@pytest.mark.parametrize("capacity", [True, 1.5])
def test_capacity_must_be_an_integer(capacity):
    with pytest.raises(flowix.InvalidParameterType):
        create_limiter("leaky", capacity=capacity, leak_rate=1)


@pytest.mark.parametrize("algo", WINDOW_ALGOS)
@pytest.mark.parametrize("limit", [True, 1.5])
def test_limit_must_be_an_integer(algo, limit):
    with pytest.raises(flowix.InvalidParameterType):
        create_limiter(algo, limit=limit, window=1)


@pytest.mark.parametrize("error, builtin", [
    (flowix.InvalidParameterType, TypeError),
    (flowix.InvalidParameterValue, ValueError),
    (flowix.IncorrectParameters, ValueError),
    (flowix.UnsupportedAlgorithm, ValueError),
])
def test_exceptions_are_also_builtin_ones(error, builtin):
    assert issubclass(error, flowix.FlowixError)
    assert issubclass(error, builtin)


def test_run_limiter_rejects_wrong_types():
    limiter = create_limiter("leaky", **LEAKY)
    with pytest.raises(flowix.InvalidParameterType):
        run_limiter("a", object(), Redis())
    with pytest.raises(flowix.InvalidParameterType):
        run_limiter(1, limiter, Redis())
    for client in (None, redis.asyncio.Redis()):
        with pytest.raises(flowix.InvalidParameterType):
            run_limiter("a", limiter, client)


def test_redis_down_raises_backend_failed():
    limiter = create_limiter("leaky", **LEAKY)
    with pytest.raises(flowix.BackendFailed) as error:
        run_limiter("a", limiter, Redis(port=1))
    assert isinstance(error.value.__cause__, redis.exceptions.RedisError)
