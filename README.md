# flowix

Distributed, atomic rate limiting for Python, powered by Redis.

- **Distributed:** every app server using the same Redis shares the same limits.
- **Atomic:** each check is a single Lua script, so simultaneous requests can't slip past a limit.
- **One clock:** timing comes from the Redis server, not from your app servers.

## Install

```bash
pip install flowix
```

Requires Python 3.10+ and Redis 6+.

## Quick start

```python
from redis import Redis
from flowix import create_limiter, run_limiter

client = Redis.from_url("redis://localhost:6379")
limiter = create_limiter("token", capacity=3, refill_rate=1, refill_interval=10)

result = run_limiter("user:1", limiter, client)

if result["allowed"]:
    print("go ahead")
else:
    print(f"try again in {result['retry_after']} seconds")
```

`run_limiter` returns a dict:

| Key | Type | Meaning |
|---|---|---|
| `allowed` | `bool` | Whether the request may proceed |
| `retry_after` | `int` | Whole seconds until a request can be allowed, `0` when allowed |

## Algorithms

### Token bucket

```python
create_limiter("token", capacity=10, refill_rate=5, refill_interval=60)
```

Allows bursts of up to `capacity` requests, then adds `refill_rate` tokens every
`refill_interval` seconds. Each request uses one token.

### Leaky bucket

```python
create_limiter("leaky", capacity=10, leak_rate=2)
```

Each request fills the bucket by one, and it drains continuously at `leak_rate`
requests per second. Requests are rejected while the bucket is full. Requests are
not queued or delayed.

### Fixed window

```python
create_limiter("fixed_window", limit=10, window=60)
```

Allows `limit` requests per `window` seconds. A window opens on the first
allowed request, and the next one opens on the first allowed request after it ends. Up to twice `limit` can
get through around the moment one window ends and the next begins.

### Sliding window log

```python
create_limiter("sliding_log", limit=10, window=60)
```

Never allows more than `limit` requests in any `window` seconds. It stores the time of
every allowed request, so each key holds up to `limit` entries.

### Sliding window counter

```python
create_limiter("sliding_counter", limit=1000, window=60)
```

Estimates the sliding window from two counters, so each key stays small however high
`limit` is. The estimate assumes the previous window's requests were evenly spread:
when they came in a burst, up to nearly twice `limit` can get through in `window`
seconds. Use `sliding_log` when the limit must be exact.

### Choosing an algorithm

| Algorithm | Stored per key | Most requests in one window | Good for |
|---|---|---|---|
| `token` | 2 numbers | `capacity` plus refills | APIs with bursty traffic |
| `leaky` | 2 numbers | `capacity` plus leaks | Smoothing to a steady rate |
| `fixed_window` | 2 numbers | Up to 2 × `limit` | Simple quotas |
| `sliding_log` | Up to `limit` times | Exactly `limit` | Low, strict limits such as logins |
| `sliding_counter` | 3 numbers | Usually about `limit`, at worst nearly 2 × | High limits on busy endpoints |

## Choosing keys

A key identifies what is being limited, such as a user or an IP address. Limiters
using the same algorithm and the same key share one bucket, so give each limit its
own key:

```python
run_limiter("login:user:1", login_limiter, client)
run_limiter("search:user:1", search_limiter, client)
```

flowix stores its data in Redis under `flowix:`.

## Several limits at once

When a request counts towards more than one limit, check them together:

```python
from flowix import run_limiters

result = run_limiters([
    ("user:1", user_limiter),
    ("ip:203.0.113.7", ip_limiter),
    ("tenant:9", tenant_limiter),
], client)

if not result["allowed"]:
    print(f"try again in {result['retry_after']} seconds")
```

If any limiter denies the request, the whole batch is denied and **none** of them are
charged. Everything happens in one Lua script and one round trip, and the limiters can
use different algorithms.

| Key | Type | Meaning |
|---|---|---|
| `allowed` | `bool` | Whether every limiter allowed the request |
| `retry_after` | `int` | Whole seconds until every limiter has room, `0` when allowed |
| `results` | `list` | One `run_limiter` result per limiter, in the order you gave them |

In a denied batch, `results` shows which limiters were the cause. The others say
`allowed: True` because they had room, not because they were charged.

A batch cannot be empty, or repeat the same key with the same algorithm.

## Errors

Every exception inherits from `FlowixError`.

| Exception | Raised when |
|---|---|
| `InvalidParameterType` | A parameter has the wrong type |
| `InvalidParameterValue` | A number is zero or negative, or a batch is empty or repeats a limiter |
| `IncorrectParameters` | Parameters are missing or not accepted by the algorithm |
| `UnsupportedAlgorithm` | The algorithm does not exist |
| `BackendFailed` | Redis could not be reached or returned an error |

If Redis goes down, you decide whether to let requests through:

```python
from flowix import BackendFailed

try:
    allowed = run_limiter("user:1", limiter, client)["allowed"]
except BackendFailed:
    allowed = True  # or False to reject
```

## Limitations

- Synchronous `redis.Redis` clients only; async clients are not supported yet.
- Redis Cluster clients (`RedisCluster`) are not supported yet.

## Running the tests

The tests need a running Redis. They use database 15 on `localhost:6379`, and delete
only the keys they create. Set `FLOWIX_TEST_REDIS_URL` to use a different one.

```bash
uv run pytest
```

## License

MIT
