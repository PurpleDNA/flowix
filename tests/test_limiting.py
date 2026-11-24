import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from flowix import create_limiter, run_limiter
from flowix.algorithm_lua_scripts.leaky_bucket import leaky_bucket_script
from flowix.algorithm_lua_scripts.token_bucket import token_bucket_script


def allowed(key, limiter, client, times):
    return [run_limiter(key, limiter, client)["allowed"] for _ in range(times)]


@pytest.mark.parametrize("algo, params", [
    ("token", {"capacity": 3, "refill_rate": 1, "refill_interval": 1}),
    ("token", {"capacity": 1, "refill_rate": 0.5, "refill_interval": 1}),
    ("leaky", {"capacity": 3, "leak_rate": 1}),
    ("leaky", {"capacity": 1, "leak_rate": 0.5}),
])
def test_blocks_at_capacity_then_allows_after_retry_after(client, key, algo, params):
    limiter = create_limiter(algo, **params)
    assert allowed(key, limiter, client, params["capacity"]) == [True] * params["capacity"]

    blocked = run_limiter(key, limiter, client)
    assert blocked["allowed"] is False
    assert blocked["retry_after"] >= 1

    time.sleep(blocked["retry_after"])
    assert run_limiter(key, limiter, client) == {"allowed": True, "retry_after": 0}


@pytest.mark.parametrize("algo, params", [
    ("token", {"capacity": 50, "refill_rate": 1, "refill_interval": 3600}),
    ("leaky", {"capacity": 50, "leak_rate": 0.0001}),
])
def test_concurrent_requests_never_exceed_capacity(client, key, algo, params):
    limiter = create_limiter(algo, **params)
    with ThreadPoolExecutor(20) as pool:
        results = list(pool.map(lambda _: run_limiter(key, limiter, client)["allowed"], range(200)))
    assert sum(results) == 50


@pytest.mark.parametrize("algo, params, drain_time", [
    ("token", {"capacity": 10, "refill_rate": 2, "refill_interval": 6}, 30),
    ("leaky", {"capacity": 10, "leak_rate": 0.5}, 20),
])
def test_bucket_outlives_its_full_recovery(client, key, algo, params, drain_time):
    # expiring any sooner would hand out a full bucket early
    run_limiter(key, create_limiter(algo, **params), client)
    assert client.ttl(f"flowix:{algo}:{key}") >= drain_time


def test_idle_bucket_expires(client, key):
    run_limiter(key, create_limiter("leaky", capacity=1, leak_rate=1), client)
    time.sleep(2.5)
    assert not client.exists(f"flowix:leaky:{key}")


def test_algorithms_do_not_share_a_bucket(client, key):
    token = create_limiter("token", capacity=2, refill_rate=1, refill_interval=60)
    leaky = create_limiter("leaky", capacity=2, leak_rate=5)
    allowed(key, token, client, 2)
    assert run_limiter(key, leaky, client)["allowed"]
    time.sleep(2.5)  # longer than the leaky bucket's ttl
    assert not run_limiter(key, token, client)["allowed"]


@pytest.mark.parametrize("prefix", ["token", "leaky"])
def test_does_not_touch_the_apps_own_keys(client, key, prefix):
    client.hset(f"{prefix}:{key}", mapping={"user": "42"})
    run_limiter(key, create_limiter("token", capacity=2, refill_rate=1, refill_interval=1), client)
    run_limiter(key, create_limiter("leaky", capacity=2, leak_rate=1), client)
    assert client.hlen(f"{prefix}:{key}") == 1
    assert client.ttl(f"{prefix}:{key}") == -1


# The scripts read Redis' clock, so these run a copy that takes the time as its
# last argument instead.

NOW = "local now = tonumber(t[1]) + tonumber(t[2]) / 1e6"
T = 1_700_000_000.25


def with_fake_clock(client, script, key, *args):
    assert script.count(NOW) == 1
    fake = client.register_script(script.replace(NOW, f"local now = tonumber(ARGV[{len(args) + 1}])"))
    return lambda now: fake(keys=[f"flowix:{key}"], args=[*args, now])


def test_token_clock_moving_backwards(client, key):
    run = with_fake_clock(client, token_bucket_script, key, 3, 1, 60)
    for _ in range(3):
        run(T)
    assert run(T - 10) == [0, 60]
    assert run(T + 49) == [0, 1]
    assert run(T + 50) == [1, 0]


def test_leaky_clock_moving_backwards(client, key):
    run = with_fake_clock(client, leaky_bucket_script, key, 3, 1)
    for _ in range(3):
        run(T)
    assert run(T - 10) == [0, 1]
    assert run(T - 9) == [1, 0]
