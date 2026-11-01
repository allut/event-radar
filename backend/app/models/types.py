from typing import Any

from sqlalchemy.types import UserDefinedType


class CIText(UserDefinedType):
    """PostgreSQL citext extension type — case-insensitive text."""

    cache_ok = True

    def get_col_spec(self, **kw: Any) -> str:
        return "CITEXT"
