import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from flowix import create_limiter, run_limiter


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
