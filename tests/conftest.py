import os
import uuid

import pytest
from redis import Redis

URL = os.environ.get("FLOWIX_TEST_REDIS_URL", "redis://localhost:6379/15")


@pytest.fixture(params=[True, False], ids=["str-client", "bytes-client"])
def client(request):
    client = Redis.from_url(URL, decode_responses=request.param)
    yield client
    client.close()


@pytest.fixture
def key():
    """A key no other test uses; everything stored under it is deleted afterwards."""
    key = f"flowixtest-{uuid.uuid4().hex}"
    yield key
    client = Redis.from_url(URL)
    for name in client.scan_iter(f"*{key}*"):
        client.delete(name)
    client.close()
