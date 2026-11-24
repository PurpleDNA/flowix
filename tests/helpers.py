from flowix.algorithm_lua_scripts.limiter_script import limiter_script

NOW = "local now = tonumber(t[1]) + tonumber(t[2]) / 1e6"
T = 1_700_000_000.25


def batch_with_fake_clock(client, *checks):
    """Run (algo, key, *params) checks on a copy of the script that is told the time."""
    assert limiter_script.count(NOW) == 1
    fake = client.register_script(limiter_script.replace(NOW, "local now = tonumber(ARGV[#ARGV])"))
    keys = [f"flowix:{algo}:{key}" for algo, key, *_ in checks]
    args = []
    for algo, _, *params in checks:
        args += [algo, *params, *[0] * (3 - len(params))]
    return lambda now: fake(keys=keys, args=[*args, now])


def with_fake_clock(client, algo, key, *params):
    run = batch_with_fake_clock(client, (algo, key, *params))
    return lambda now: run(now)[0]
