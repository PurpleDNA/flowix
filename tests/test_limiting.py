import math
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from flowix import create_limiter, run_limiter
from helpers import T, with_fake_clock


def allowed(key, limiter, client, times):
    return [run_limiter(key, limiter, client)["allowed"] for _ in range(times)]


@pytest.mark.parametrize("algo, params", [
    ("token", {"capacity": 3, "refill_rate": 1, "refill_interval": 1}),
    ("token", {"capacity": 1, "refill_rate": 0.5, "refill_interval": 1}),
    ("leaky", {"capacity": 3, "leak_rate": 1}),
    ("leaky", {"capacity": 1, "leak_rate": 0.5}),
    ("fixed_window", {"limit": 3, "window": 1}),
    ("fixed_window", {"limit": 1, "window": 1.5}),
    ("sliding_log", {"limit": 3, "window": 1}),
    ("sliding_log", {"limit": 1, "window": 1.5}),
    # sliding_counter is tested with a fake clock: its windows can end mid-test
])
def test_blocks_at_capacity_then_allows_after_retry_after(client, key, algo, params):
    limiter = create_limiter(algo, **params)
    size = params.get("capacity") or params["limit"]
    assert allowed(key, limiter, client, size) == [True] * size

    blocked = run_limiter(key, limiter, client)
    assert blocked["allowed"] is False
    assert blocked["retry_after"] >= 1

    time.sleep(blocked["retry_after"])
    assert run_limiter(key, limiter, client) == {"allowed": True, "retry_after": 0}


@pytest.mark.parametrize("algo, params", [
    ("token", {"capacity": 50, "refill_rate": 1, "refill_interval": 3600}),
    ("leaky", {"capacity": 50, "leak_rate": 0.0001}),
    ("fixed_window", {"limit": 50, "window": 86400}),
    ("sliding_log", {"limit": 50, "window": 86400}),
    ("sliding_counter", {"limit": 50, "window": 86400}),
])
def test_concurrent_requests_never_exceed_capacity(client, key, algo, params):
    limiter = create_limiter(algo, **params)
    with ThreadPoolExecutor(20) as pool:
        results = list(pool.map(lambda _: run_limiter(key, limiter, client)["allowed"], range(200)))
    assert sum(results) == 50


@pytest.mark.parametrize("algo, params, drain_time", [
    ("token", {"capacity": 10, "refill_rate": 2, "refill_interval": 6}, 30),
    ("token", {"capacity": 1, "refill_rate": 0.6, "refill_interval": 100}, 200),
    ("leaky", {"capacity": 10, "leak_rate": 0.5}, 20),
    ("fixed_window", {"limit": 10, "window": 20}, 20),
    ("sliding_log", {"limit": 10, "window": 20}, 20),
    ("sliding_counter", {"limit": 10, "window": 20}, 40),
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


def test_every_algorithm_can_use_the_same_key(client, key):
    for limiter in (
        create_limiter("token", capacity=1, refill_rate=1, refill_interval=3600),
        create_limiter("leaky", capacity=1, leak_rate=0.001),
        create_limiter("fixed_window", limit=1, window=3600),
        create_limiter("sliding_log", limit=1, window=3600),
        create_limiter("sliding_counter", limit=1, window=3600),
    ):
        assert run_limiter(key, limiter, client)["allowed"]


@pytest.mark.parametrize("prefix", ["token", "leaky"])
def test_does_not_touch_the_apps_own_keys(client, key, prefix):
    client.hset(f"{prefix}:{key}", mapping={"user": "42"})
    run_limiter(key, create_limiter("token", capacity=2, refill_rate=1, refill_interval=1), client)
    run_limiter(key, create_limiter("leaky", capacity=2, leak_rate=1), client)
    assert client.hlen(f"{prefix}:{key}") == 1
    assert client.ttl(f"{prefix}:{key}") == -1


# These run on a fake clock, so nothing has to sleep.


def test_token_clock_moving_backwards(client, key):
    run = with_fake_clock(client, "token", key, 3, 1, 60)
    for _ in range(3):
        run(T)
    assert run(T - 10) == [0, 60]
    assert run(T + 49) == [0, 1]
    assert run(T + 50) == [1, 0]


def test_leaky_clock_moving_backwards(client, key):
    run = with_fake_clock(client, "leaky", key, 3, 1)
    for _ in range(3):
        run(T)
    assert run(T - 10) == [0, 1]
    assert run(T - 9) == [1, 0]


def test_token_retry_after_counts_time_already_passed(client, key):
    run = with_fake_clock(client, "token", key, 3, 1, 60)
    for _ in range(3):
        run(T)
    assert run(T + 20) == [0, 40]
    assert run(T + 59.5) == [0, 1]


def test_leaky_allows_a_steady_stream_at_the_leak_rate(client, key):
    run = with_fake_clock(client, "leaky", key, 3, 1)
    for _ in range(3):
        run(T)
    assert all(run(T + second) == [1, 0] for second in range(1, 51))


def test_leaky_retry_after_rounds_up(client, key):
    run = with_fake_clock(client, "leaky", key, 1, 0.3)
    run(T)
    assert run(T) == [0, math.ceil(1 / 0.3)]


WINDOW_ALGOS = ["fixed_window", "sliding_log", "sliding_counter"]


@pytest.mark.parametrize("algo", WINDOW_ALGOS)
def test_window_denied_requests_do_not_count(client, key, algo):
    run = with_fake_clock(client, algo, key, 2, 60)
    assert [run(T)[0] for _ in range(20)] == [1, 1] + [0] * 18
    raised = with_fake_clock(client, algo, key, 4, 60)
    assert [raised(T)[0] for _ in range(3)] == [1, 1, 0]
    assert [run(T + 120)[0] for _ in range(3)] == [1, 1, 0]


@pytest.mark.parametrize("algo", WINDOW_ALGOS)
def test_window_retry_after_is_long_enough(client, key, algo):
    # 7.3 does not divide T, so the windows start at awkward times
    run = with_fake_clock(client, algo, key, 5, 7.3)
    now, denied = T, 0
    for step in range(60):
        ok, retry_after = run(now)
        if ok:
            now += (step % 4) * 0.37
            continue
        denied += 1
        assert retry_after >= 1
        now += retry_after
        assert run(now) == [1, 0]
    assert denied > 5


@pytest.mark.parametrize("algo", WINDOW_ALGOS)
def test_window_clock_moving_backwards(client, key, algo):
    run = with_fake_clock(client, algo, key, 3, 60)
    for _ in range(3):
        run(T)
    back = T - 3600
    ok, retry_after = run(back)
    assert not ok                   # moving the clock does not reset the limit
    assert retry_after <= 120       # nor block for the hour it moved
    assert run(back + retry_after) == [1, 0]


def test_fixed_window_starts_at_the_first_request(client, key):
    run = with_fake_clock(client, "fixed_window", key, 2, 60)
    assert run(T) == [1, 0]
    assert run(T + 59) == [1, 0]
    assert run(T + 59) == [0, 1]
    assert run(T + 60) == [1, 0]


def test_sliding_log_never_exceeds_the_limit_in_any_window(client, key):
    run = with_fake_clock(client, "sliding_log", key, 5, 10)
    times = [T + step * 0.25 for step in range(400) if run(T + step * 0.25)[0]]
    assert len(times) == 50
    assert all(later - first >= 10 for first, later in zip(times, times[5:]))


def test_sliding_log_retry_after_a_lowered_limit(client, key):
    run = with_fake_clock(client, "sliding_log", key, 3, 60)
    for second in range(3):
        run(T + second)
    lowered = with_fake_clock(client, "sliding_log", key, 1, 60)
    assert lowered(T + 2) == [0, 60]  # all three must leave, not just the oldest
    assert lowered(T + 62) == [1, 0]


def test_sliding_counter_fades_out_the_previous_window(client, key):
    start = 1_700_000_040  # a multiple of 60
    run = with_fake_clock(client, "sliding_counter", key, 10, 60)
    assert [run(start + 30)[0] for _ in range(11)] == [1] * 10 + [0]
    assert run(start + 30) == [0, 31]
    assert [run(start + 90)[0] for _ in range(6)] == [1] * 5 + [0]
    assert run(start + 90) == [0, 1]
    assert run(start + 91) == [1, 0]


def test_sliding_counter_retry_after_a_lowered_limit(client, key):
    start = 1_700_000_040
    run = with_fake_clock(client, "sliding_counter", key, 10, 60)
    for _ in range(10):
        run(start + 30)
    lowered = with_fake_clock(client, "sliding_counter", key, 5, 60)
    assert lowered(start + 30) == [0, 61]
    assert lowered(start + 91) == [1, 0]


def test_sliding_counter_retry_after_survives_float_error(client, key):
    run = with_fake_clock(client, "sliding_counter", key, 1, 10)
    run(1_700_000_003)
    retry_after = run(1_700_000_003)[1]
    assert run(1_700_000_003 + retry_after) == [1, 0]
