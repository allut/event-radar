"""Shared per-IP rate limiter instance.

Lives in its own module (mirroring db.py's role for the engine/session) so that
both app.main (middleware/exception-handler wiring) and routers (per-endpoint
@limiter.limit decorators) can import it without a circular dependency.
"""

from typing import cast

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from starlette.types import ExceptionHandler

limiter = Limiter(key_func=get_remote_address)
rate_limit_exceeded_handler = cast(ExceptionHandler, _rate_limit_exceeded_handler)
