"""Week-1 checkpoint integration tests.

Run against a live server:
    cd backend
    uvicorn app.main:app --reload &
    pytest tests/integration/ -v -s
"""
import http
import pytest
import pytest_asyncio

from app.constants import DEFAULT_USER_LOCALE, DEFAULT_USER_CITY

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == http.HTTPStatus.OK
    assert r.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_ingest_all_sources(client, admin_auth):
    r = await client.get("/admin/ingest", auth=admin_auth, timeout=180)
    assert r.status_code == http.HTTPStatus.OK
    results = r.json()["results"]
    assert any(s.get("raw_count", 0) > 0 for s in results), "No source returned events"


@pytest.mark.asyncio
async def test_canonical_event_count(client, admin_auth):
    r = await client.get("/admin/stats", auth=admin_auth)
    assert r.status_code == http.HTTPStatus.OK
    stats = r.json()
    canonical = stats["events"]["canonical"]
    assert canonical >= 200, (
        f"Only {canonical} canonical events — ingestion may need more runs or sources are down"
    )


@pytest.mark.asyncio
async def test_dedup_no_large_groups(client, admin_auth):
    r = await client.post("/admin/dedup", auth=admin_auth, timeout=60)
    assert r.status_code == http.HTTPStatus.OK

    r2 = await client.get("/admin/dedup/groups", auth=admin_auth)
    groups_data = r2.json()
    for g in groups_data["groups"]:
        assert len(g["events"]) <= 5, (
            f"Dedup group {g['dedup_group_id']} has {len(g['events'])} events — "
            f"titles: {[e['title'] for e in g['events']]}"
        )

    stats = (await client.get("/admin/stats", auth=admin_auth)).json()
    total = stats["events"]["total"]
    canonical = stats["events"]["canonical"]
    if total:
        dup_rate = 1 - (canonical / total)
        assert dup_rate < 0.20, f"Duplicate rate {dup_rate:.1%} exceeds 20%"


@pytest.mark.asyncio
async def test_auth_login_flow(client, int_db):
    """Bypass email delivery by inserting a magic-link record directly into the DB."""
    from sqlalchemy import delete, select

    from app.auth.tokens import generate_magic_token
    from app.models.models import AuthMagicLink, User

    TEST_EMAIL = "checkpoint-test@example.com"

    await int_db.execute(delete(User).where(User.email == TEST_EMAIL))
    await int_db.commit()

    user = User(email=TEST_EMAIL, locale=DEFAULT_USER_LOCALE, home_city=DEFAULT_USER_CITY)
    int_db.add(user)
    await int_db.flush()

    token, token_hash, expires_at = generate_magic_token(user.id)
    int_db.add(AuthMagicLink(user_id=user.id, token_hash=token_hash, expires_at=expires_at))
    await int_db.commit()

    r = await client.get("/auth/verify", params={"token": token})
    assert r.status_code == http.HTTPStatus.OK, f"verify failed: {r.text}"
    session_token = r.json()["session_token"]

    r = await client.get("/auth/me", headers={"Authorization": f"Bearer {session_token}"})
    assert r.status_code == http.HTTPStatus.OK
    me = r.json()
    assert me["email"].lower() == TEST_EMAIL.lower()

    r2 = await client.get("/auth/verify", params={"token": token})
    assert r2.status_code == http.HTTPStatus.BAD_REQUEST, "Re-use of magic link should be rejected"

    await int_db.execute(delete(User).where(User.email == TEST_EMAIL))
    await int_db.commit()
