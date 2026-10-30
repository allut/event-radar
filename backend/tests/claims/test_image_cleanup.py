"""#641 cleanup: only claimant-pinned non-Cloudinary images are cleared."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.claims.image_cleanup import clear_foreign_pinned_images

OWN = "https://res.cloudinary.com/demo/image/upload/v1/x.png"


@pytest.mark.asyncio
async def test_clears_only_foreign_pinned_images(mock_db, make_event):
    foreign = make_event(event_id=1)
    foreign.image_url = "https://evil.example.com/p.png"
    foreign.pinned_fields = ["image_url", "title:et"]
    own = make_event(event_id=2)
    own.image_url = OWN
    own.pinned_fields = ["image_url"]
    deliberately_cleared = make_event(event_id=3)
    deliberately_cleared.image_url = None
    deliberately_cleared.pinned_fields = ["image_url"]
    result = MagicMock()
    result.scalars.return_value.all.return_value = [foreign, own, deliberately_cleared]
    mock_db.execute = AsyncMock(return_value=result)

    with patch("app.ingestion.http_client.settings") as s:
        s.CLOUDINARY_CLOUD_NAME = "demo"
        count = await clear_foreign_pinned_images(mock_db)

    assert count == 1
    assert foreign.image_url is None
    assert foreign.pinned_fields == ["title:et"]
    assert own.image_url == OWN
    assert own.pinned_fields == ["image_url"]
    assert deliberately_cleared.pinned_fields == ["image_url"]
