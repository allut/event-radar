import pytest

from app.rate_limit import limiter


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """The slowapi Limiter is a module-level singleton shared by every router
    test in this directory. Since L2 (routers/admin.py) moved every /admin/*
    route onto ONE shared_limit(..., scope="admin") bucket per client instead
    of one bucket per route, the whole admin test suite would otherwise share
    a single 10/minute allowance and start seeing spurious 429s partway
    through a run. Reset before (and after, for tests that don't clean up
    themselves) every test so each one starts with a fresh bucket."""
    limiter.reset()
    yield
    limiter.reset()
