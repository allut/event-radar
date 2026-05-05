"""Admin endpoints — protected by HTTP Basic auth."""
import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.config import settings
from app.ingestion.jobs import ingest_all_enabled, ingest_source
from app.ingestion.registry import ADAPTER_REGISTRY

log = logging.getLogger(__name__)
router = APIRouter(prefix="/admin")
_security = HTTPBasic()


def _require_admin(credentials: HTTPBasicCredentials = Depends(_security)) -> None:
    password = settings.ADMIN_PASSWORD
    if not password:
        if settings.APP_ENV != "development":
            # Production with no password set — refuse all access until explicitly configured.
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Admin endpoints disabled: ADMIN_PASSWORD not configured",
            )
        # Development with no password — allow any credentials but log a warning so devs know.
        log.warning("ADMIN_PASSWORD not set; admin endpoints are unprotected (development mode)")
        return
    username_ok = secrets.compare_digest(
        credentials.username.encode(),
        settings.ADMIN_USERNAME.encode(),
    )
    password_ok = secrets.compare_digest(
        credentials.password.encode(),
        password.encode(),
    )
    if not (username_ok and password_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect credentials",
            headers={"WWW-Authenticate": "Basic"},
        )


@router.get("/ingest", dependencies=[Depends(_require_admin)])
async def admin_ingest_all():
    """Trigger ingestion for all enabled sources."""
    results = await ingest_all_enabled()
    return {"results": results}


@router.post("/ingest/{slug}", dependencies=[Depends(_require_admin)])
async def admin_ingest_source(slug: str):
    """Trigger ingestion for a single source by slug."""
    if slug not in ADAPTER_REGISTRY:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown source: {slug!r}")
    try:
        result = await ingest_source(slug)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception:
        log.exception("admin ingest failed for slug=%s", slug)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Ingestion failed; see server logs")
    return result
