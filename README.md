# flowix

Distributed, atomic rate limiting for Python, powered by Redis.

- **Distributed:** every app server using the same Redis shares the same limits.
- **Atomic:** each check is a single Lua script, so simultaneous requests can't slip past a limit.
- **One clock:** timing comes from the Redis server, not from your app servers.

## Install

```bash
pip install flowix
```

Requires Python 3.10+ and Redis 5+.

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

## Choosing keys

A key identifies what is being limited, such as a user or an IP address. Limiters
using the same algorithm and the same key share one bucket, so give each limit its
own key:

```python
run_limiter("login:user:1", login_limiter, client)
run_limiter("search:user:1", search_limiter, client)
```

flowix stores its data in Redis under `flowix:`.

## Errors

Every exception inherits from `FlowixError`.

| Exception | Raised when |
|---|---|
| `InvalidParameterType` | A parameter has the wrong type |
| `InvalidParameterValue` | A number is zero or negative |
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
