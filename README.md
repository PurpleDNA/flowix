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
