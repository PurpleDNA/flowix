from concurrent.futures import ThreadPoolExecutor

import pytest
import redis.asyncio
from redis import Redis

import flowix
from flowix import create_limiter, run_limiter, run_limiters
from helpers import T, batch_with_fake_clock, with_fake_clock

# every algorithm, with parameters it takes to allow `size` requests and then no more
ALGOS = {
    "token": lambda size: {"capacity": size, "refill_rate": 1, "refill_interval": 86400},
    "leaky": lambda size: {"capacity": size, "leak_rate": 0.00001},
    "fixed_window": lambda size: {"limit": size, "window": 86400},
    "sliding_log": lambda size: {"limit": size, "window": 86400},
    "sliding_counter": lambda size: {"limit": size, "window": 86400 * 365},
}


def limiter(algo, size):
    return create_limiter(algo, **ALGOS[algo](size))


def stored(client, algo, key):
    """Everything kept for a key, to see whether anything changed."""
    name = f"flowix:{algo}:{key}"
    if client.type(name) in ("list", b"list"):
        return client.lrange(name, 0, -1)
    return client.hgetall(name)


def test_allowed_batch_charges_every_limiter(client, key):
    checks = [(f"{key}:{algo}", limiter(algo, 3)) for algo in ALGOS]
    for _ in range(3):
        assert run_limiters(checks, client) == {
            "allowed": True,
            "retry_after": 0,
            "results": [{"allowed": True, "retry_after": 0}] * len(ALGOS),
        }
    for check_key, check_limiter in checks:
        assert not run_limiter(check_key, check_limiter, client)["allowed"]


@pytest.mark.parametrize("used", [0, 2])
@pytest.mark.parametrize("denier", ALGOS)
def test_denied_batch_changes_nothing(client, key, denier, used):
    full = (f"{key}:full", limiter(denier, 1))
    run_limiter(*full, client)
    others = [(f"{key}:{algo}", limiter(algo, 3)) for algo in ALGOS]
    for _ in range(used):
        run_limiters(others, client)

    names = [(algo, f"{key}:{algo}") for algo in ALGOS] + [(denier, f"{key}:full")]
    before = [stored(client, *name) for name in names]
    for checks in ([full, *others], [*others, full], [*others[:2], full, *others[2:]]):
        for _ in range(5):
            assert run_limiters(checks, client)["allowed"] is False
    assert [stored(client, *name) for name in names] == before

    # and what was left before is still there
    allowed = [run_limiters(others, client)["allowed"] for _ in range(4 - used)]
    assert allowed == [True] * (3 - used) + [False]


def test_results_are_in_order_and_retry_after_is_the_longest(client, key):
    slow = create_limiter("fixed_window", limit=1, window=5000)
    slower = create_limiter("sliding_log", limit=1, window=9000)
    checks = [
        (f"{key}:room", limiter("leaky", 5)),
        (f"{key}:slow", slow),
        (f"{key}:slower", slower),
        (f"{key}:more-room", limiter("token", 5)),
    ]
    assert run_limiters(checks, client)["allowed"]

    batch = run_limiters(checks, client)
    assert [result["allowed"] for result in batch["results"]] == [True, False, False, True]
    waits = [result["retry_after"] for result in batch["results"]]
    assert waits[0] == waits[3] == 0
    assert 4990 <= waits[1] <= 5000
    assert 8990 <= waits[2] <= 9000
    assert batch["retry_after"] == waits[2]


def test_batch_is_allowed_after_retry_after(client, key):
    run = batch_with_fake_clock(
        client,
        ("token", key, 4, 2, 5),
        ("leaky", key, 3, 0.7),
        ("fixed_window", key, 6, 11),
        ("sliding_log", key, 5, 7.3),
        ("sliding_counter", key, 7, 13),
    )
    now, deniers = T, set()
    for step in range(150):
        results = run(now)
        if all(ok for ok, _ in results):
            now += (step % 3) * 0.2
            continue
        deniers |= {i for i, (ok, _) in enumerate(results) if not ok}
        now += max(retry_after for _, retry_after in results)
        assert run(now) == [[1, 0]] * 5
    assert len(deniers) >= 4


def test_batch_and_single_limiters_share_their_state(client, key):
    for algo in ALGOS:
        check = (f"{key}:{algo}", limiter(algo, 2))
        assert run_limiter(*check, client)["allowed"]
        assert run_limiters([check], client)["allowed"]
        assert not run_limiter(*check, client)["allowed"]
        assert not run_limiters([check], client)["allowed"]


def test_concurrent_batches_never_exceed_any_limit(client, key):
    sizes = dict(zip(ALGOS, (70, 50, 90, 60, 80)))
    checks = [(f"{key}:{algo}", limiter(algo, size)) for algo, size in sizes.items()]
    with ThreadPoolExecutor(20) as pool:
        results = list(pool.map(lambda _: run_limiters(checks, client)["allowed"], range(200)))
    assert sum(results) == 50

    # the 150 denied requests used up nothing
    for (check_key, check_limiter), size in zip(checks, sizes.values()):
        left = sum(run_limiter(check_key, check_limiter, client)["allowed"] for _ in range(100))
        assert left == size - 50


def test_denied_batch_does_not_open_a_fixed_window(client, key):
    full = ("token", f"{key}:full", 1, 1, 3600)
    with_fake_clock(client, *full)(T)
    batch = batch_with_fake_clock(client, full, ("fixed_window", key, 2, 60))
    assert batch(T) == [[0, 3600], [1, 0]]

    run = with_fake_clock(client, "fixed_window", key, 2, 60)
    assert [run(T + 59), run(T + 59)] == [[1, 0], [1, 0]]
    assert run(T + 60) == [0, 59]


def test_same_key_with_different_algorithms(client, key):
    checks = [(key, limiter(algo, 1)) for algo in ALGOS]
    assert run_limiters(checks, client)["allowed"]
    assert not run_limiters(checks, client)["allowed"]


def test_checks_can_be_any_iterable(client, key):
    for checks in ([[key, limiter("leaky", 9)]], ((key, limiter("leaky", 9)) for _ in range(1))):
        assert run_limiters(checks, client)["allowed"]


def test_repeated_limiter_is_rejected_before_charging(client, key):
    with pytest.raises(flowix.InvalidParameterValue):
        run_limiters([(key, limiter("leaky", 5)), (key, limiter("leaky", 9))], client)
    assert not client.exists(f"flowix:leaky:{key}")


def test_empty_batch_is_rejected():
    for checks in ([], iter(())):
        with pytest.raises(flowix.InvalidParameterValue):
            run_limiters(checks, Redis())


@pytest.mark.parametrize("checks", [
    None,
    "ab",
    {"a": 1},
    ["ab"],
    [("a",)],
    [("a", create_limiter("leaky", capacity=1, leak_rate=1), 1)],
    [("a", object())],
    [(1, create_limiter("leaky", capacity=1, leak_rate=1))],
])
def test_wrong_types_are_rejected(checks):
    with pytest.raises(flowix.InvalidParameterType):
        run_limiters(checks, Redis())


@pytest.mark.parametrize("client", [None, redis.asyncio.Redis()])
def test_wrong_clients_are_rejected(client):
    with pytest.raises(flowix.InvalidParameterType):
        run_limiters([("a", limiter("leaky", 1))], client)


def test_redis_down_raises_backend_failed():
    with pytest.raises(flowix.BackendFailed):
        run_limiters([("a", limiter("leaky", 1))], Redis(port=1))
