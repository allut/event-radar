from unittest.mock import AsyncMock, MagicMock


def mock_execute_returning(row):
    """An AsyncMock whose awaited result has `.fetchone()` returning `row` —
    stands in for `db.execute(...)` on an INSERT/UPDATE ... RETURNING
    statement. Shared by the consumer and organizer magic-link auth tests."""
    execute_result = MagicMock()
    execute_result.fetchone.return_value = row
    return AsyncMock(return_value=execute_result)
