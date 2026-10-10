"""candidate_pair_ids_in_window bounds both sides of the self-join."""

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from app.constants import TALLINN_TZ
from app.dedup.rules import candidate_pair_ids_in_window


@pytest.mark.asyncio
async def test_pair_query_has_upper_date_bound(mock_db):
    result = MagicMock()
    result.all.return_value = []
    mock_db.execute.return_value = result

    await candidate_pair_ids_in_window(mock_db, datetime.now(TALLINN_TZ))

    compiled = str(mock_db.execute.call_args.args[0])
    assert compiled.count("starts_at <=") >= 3  # window upper bound + a/b lookahead
