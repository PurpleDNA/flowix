import logging
import subprocess
import sys
import threading

import pytest
import redis.asyncio
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from redis import Redis

import flowix
from flowix import create_limiter, run_limiter
from flowix.fastapi import rate_limit

DOWN = Redis(port=1)


def limiter(size):
    return create_limiter("fixed_window", limit=size, window=3600)


def app_with(dependency):
    app = FastAPI()

    @app.get("/async", dependencies=[Depends(dependency)])
    async def async_endpoint():
        return "async"

    @app.get("/sync", dependencies=[Depends(dependency)])
    def sync_endpoint():
        return "sync"

    return TestClient(app)


@pytest.mark.parametrize("path", ["/async", "/sync"])
def test_allows_then_responds_429(client, key, path):
    api = app_with(rate_limit(client, lambda: [(key, limiter(2))]))
    for _ in range(2):
        assert api.get(path).json() == path[1:]

    denied = api.get(path)
    assert denied.status_code == 429
    assert denied.json() == {"detail": "Too many requests"}
    assert 3590 <= int(denied.headers["Retry-After"]) <= 3600


def test_denied_request_does_not_reach_the_endpoint(client, key):
    app, reached = FastAPI(), []

    @app.get("/", dependencies=[Depends(rate_limit(client, lambda: [(key, limiter(1))]))])
    async def endpoint():
        reached.append(1)

    api = TestClient(app)
    assert [api.get("/").status_code for _ in range(3)] == [200, 429, 429]
    assert len(reached) == 1


def test_denied_request_charges_no_limit(client, key):
    roomy = (f"{key}:roomy", limiter(3))
    api = app_with(rate_limit(client, lambda: [roomy, (f"{key}:tight", limiter(1))]))
    assert [api.get("/async").status_code for _ in range(5)] == [200] + [429] * 4
    assert [run_limiter(*roomy, client)["allowed"] for _ in range(3)] == [True, True, False]


def test_checks_can_use_other_dependencies(client, key):
    def current_user(x_user: str = Header(default="")):
        if not x_user:
            raise HTTPException(401)
        return x_user

    def checks(user: str = Depends(current_user)):
        return [(f"{key}:{user}", limiter(1))]

    api = app_with(rate_limit(client, checks))
    assert api.get("/async").status_code == 401
    for user in ("ada", "bob"):
        statuses = [api.get("/async", headers={"X-User": user}).status_code for _ in range(2)]
        assert statuses == [200, 429]


def test_checks_can_be_async(client, key):
    async def checks():
        return [(key, limiter(1))]

    api = app_with(rate_limit(client, checks))
    assert [api.get("/async").status_code for _ in range(2)] == [200, 429]


def test_runs_outside_the_event_loop_thread(client, key, monkeypatch):
    threads = {}

    def spy(*args):
        threads["limiter"] = threading.get_ident()
        return flowix.run_limiters(*args)

    monkeypatch.setattr("flowix.fastapi.run_limiters", spy)
    app = FastAPI()

    @app.get("/", dependencies=[Depends(rate_limit(client, lambda: [(key, limiter(1))]))])
    async def endpoint():
        threads["event loop"] = threading.get_ident()

    assert TestClient(app).get("/").status_code == 200
    assert threads["limiter"] != threads["event loop"]


def test_can_limit_a_whole_router(client, key):
    dependency = rate_limit(client, lambda: [(key, limiter(2))])
    router = APIRouter(dependencies=[Depends(dependency)])
    router.add_api_route("/a", lambda: "a")
    router.add_api_route("/b", lambda: "b")
    app = FastAPI()
    app.include_router(router)
    api = TestClient(app)
    assert [api.get(path).status_code for path in ("/a", "/b", "/a")] == [200, 200, 429]


def test_redis_down_raises_backend_failed():
    api = app_with(rate_limit(DOWN, lambda: [("a", limiter(1))]))
    with pytest.raises(flowix.BackendFailed):
        api.get("/async")


def test_redis_down_with_fail_open_allows_and_warns(caplog):
    api = app_with(rate_limit(DOWN, lambda: [("a", limiter(1))], fail_open=True))
    with caplog.at_level(logging.WARNING, logger="flowix.fastapi"):
        assert api.get("/async").json() == "async"
    assert [record.name for record in caplog.records] == ["flowix.fastapi"]


def test_fail_open_still_denies(client, key):
    api = app_with(rate_limit(client, lambda: [(key, limiter(1))], fail_open=True))
    assert [api.get("/async").status_code for _ in range(2)] == [200, 429]


@pytest.mark.parametrize("fail_open", [True, False])
def test_fail_open_does_not_hide_mistakes(fail_open):
    api = app_with(rate_limit(Redis(), lambda: [], fail_open=fail_open))
    with pytest.raises(flowix.InvalidParameterValue):
        api.get("/async")


def test_wrong_arguments_are_rejected_at_startup():
    for client in (None, redis.asyncio.Redis()):
        with pytest.raises(flowix.InvalidParameterType):
            rate_limit(client, lambda: [])
    with pytest.raises(flowix.InvalidParameterType):
        rate_limit(Redis(), [("a", limiter(1))])


def test_flowix_does_not_need_fastapi():
    code = "import sys; sys.modules['fastapi'] = None; import flowix"
    subprocess.run([sys.executable, "-c", code], check=True)
