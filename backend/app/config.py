import logging
from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app._generated.shared_constants import (
    MAGIC_LINK_TTL_MINUTES as _MAGIC_LINK_TTL_DEFAULT,
    SESSION_TTL_DAYS as _SESSION_TTL_DEFAULT,
)
from app.constants import ADMIN_USERNAME_DEFAULT, APP_ENV_DEVELOPMENT, LOG_LEVEL_DEFAULT


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "postgresql+asyncpg://localhost/eventradar"
    SECRET_KEY: str  # required — no default; app fails at startup if unset
    APP_ENV: str = APP_ENV_DEVELOPMENT
    # Second, explicit opt-in required (alongside APP_ENV == development) before
    # require_configured_secret() fails open on an unset secret. A dev-shaped
    # APP_ENV alone must never be sufficient to unprotect /admin/*, the inbound
    # webhook, or /internal/tick — see routers/utils.py::require_configured_secret.
    ALLOW_INSECURE_DEV: bool = False

    # Development-only kill switch for the embedded APScheduler
    # (app/main.py::_start_scheduler). The schedule drives live HTTP scrapes of
    # third-party sites, real LLM spend, and real digest email on a timer — the
    # dev container sets this false (.devcontainer/docker-compose.yml) so
    # `uvicorn --reload` left running overnight can't arm all of it. Ignored
    # unless APP_ENV == development, so a stray env var can never stop the
    # pipeline in production. Manual POST /admin/* triggers are unaffected.
    ENABLE_SCHEDULER: bool = True

    FIENTA_BASE_URL: str = "https://fienta.com/api/v1/public/events"
    KULTUURIKATEL_URL: str = "https://kultuurikatel.ee/en/events/"
    FOTOGRAFISKA_URL: str = "https://tallinn.fotografiska.com/en/events"
    KUMU_URL: str = "https://kumu.ekm.ee/en/calendar/"
    ESTONIA_CONCERT_HALL_URL: str = "https://concert.ee/en/"
    PILETILEVI_BASE_URL: str = "https://www.piletilevi.ee"
    FIENTA_ORGANIZER_IDS: list[int] = [
        3349,
        1946,
        15,
        2111,
        17595,
        1088,
        2704,
        8403,
        8412,
        12106,
    ]
    FIENTA_ORGANIZER_NAMES: dict[str, str] = {
        "3349": "Kanuti Gildi SAAL",
        "1946": "Fotografiska Tallinn",
        "15": "Von Krahli Teater",
        "2111": "Kai kunstikeskus",
        "17595": "Paavli Kultuurivabrik",
        "1088": "Tallinn Fringe Festival",
        "2704": "Kellerteater",
        "8403": "MTÜ Uus Teater",
        "8412": "EKSPEDITSIOON",
        "12106": "Must Kast",
    }

    # Persona affinity vectors — keys must match VALID_CATEGORIES / VALID_VIBES / VALID_TIMES.
    # Override in .env to retune without code changes.
    # Retuned: lower music affinity so the concert-goer owns the daytime/evening
    # gig slot and the clubber stays clearly rave/techno/nightlife-only.
    PERSONA_UNDERGROUND_CLUBBER_AFFINITY: dict[str, Any] = {
        "categories": {"nightlife": 1.0, "music": 0.5, "alternative": 0.6},
        "vibes": {"underground": 1.0, "high_energy": 0.8, "indie": 0.6},
        "times": {"late_night": 1.0, "weekend": 0.8},
    }
    PERSONA_NETWORKING_PRO_AFFINITY: dict[str, Any] = {
        "categories": {"networking": 1.0, "workshops": 0.5},
        "vibes": {"trendy": 0.8, "accessible": 0.6, "educational": 0.5},
        "times": {"weekday": 0.8, "evening": 0.6},
    }
    PERSONA_WEEKEND_HOBBYIST_AFFINITY: dict[str, Any] = {
        "categories": {"sports": 0.8, "workshops": 0.7, "food_drink": 0.7},
        "vibes": {"casual": 1.0, "accessible": 0.8},
        "times": {"weekend": 1.0, "daytime": 0.8},
    }
    PERSONA_CULTURE_BUFF_AFFINITY: dict[str, Any] = {
        "categories": {
            "theater": 1.0,
            "exhibitions": 1.0,
            "cinema": 0.8,
            "literature": 0.7,
        },
        "vibes": {"niche": 0.7, "indie": 0.6, "trendy": 0.5},
        # No times preference — culture buff attends any time.
    }
    PERSONA_FAMILY_EXPLORER_AFFINITY: dict[str, Any] = {
        "categories": {"family": 1.0, "workshops": 0.6, "sports": 0.4},
        "vibes": {"accessible": 1.0, "casual": 0.7, "educational": 0.5},
        "times": {"daytime": 0.9, "weekend": 0.8},
    }
    PERSONA_CONCERT_GOER_AFFINITY: dict[str, Any] = {
        "categories": {"music": 1.0, "theater": 0.3},
        "vibes": {"mainstream": 0.8, "casual": 0.7, "accessible": 0.6},
        "times": {"evening": 0.9, "weekend": 0.7, "daytime": 0.6},
    }
    PERSONA_CINEPHILE_AFFINITY: dict[str, Any] = {
        "categories": {"cinema": 1.0, "exhibitions": 0.3, "literature": 0.3},
        "vibes": {"indie": 0.8, "niche": 0.7, "educational": 0.5},
        "times": {"evening": 0.8, "weekend": 0.6},
    }
    PERSONA_COMEDY_FAN_AFFINITY: dict[str, Any] = {
        "categories": {"comedy": 1.0, "theater": 0.5, "alternative": 0.3},
        "vibes": {"casual": 0.8, "high_energy": 0.7, "mainstream": 0.6},
        "times": {"evening": 0.9, "weekend": 0.7, "late_night": 0.4},
    }
    PERSONA_ROMANCE_SEEKER_AFFINITY: dict[str, Any] = {
        "categories": {"romantic": 1.0, "food_drink": 0.7, "music": 0.5, "cinema": 0.5, "theater": 0.4},
        "vibes": {"intimate": 1.0, "trendy": 0.5, "casual": 0.4},
        "times": {"evening": 0.9, "weekend": 0.7},
    }

    # Admin / internal security
    ADMIN_USERNAME: str = ADMIN_USERNAME_DEFAULT  # Basic-auth username for /admin/* endpoints
    ADMIN_PASSWORD: str = (
        ""  # Basic-auth password for /admin/* endpoints; empty = disabled (dev only)
    )
    INTERNAL_TOKEN: str = (
        ""  # X-Internal-Token header for /internal/tick; empty = disabled (dev only)
    )

    # Auth / email
    RESEND_API_KEY: str = (
        ""  # Resend API key for transactional email; empty = log-only (dev)
    )
    RESEND_FROM_ADDRESS: str = "What's on Radar <onboarding@resend.dev>"
    CONTACT_TO_ADDRESS: str = "contact@whatsonradar.com"  # owner inbox for contact-form mail
    FRONTEND_URL: str = "http://localhost:5173"  # Base URL for magic-link verification
    BACKEND_URL: str = "http://localhost:8000"  # Absolute API host — needed by the
    # RFC 8058 List-Unsubscribe email header, which mail providers call server-side
    # (can't go through the SPA's relative /api proxy).
    MAGIC_LINK_TTL_MINUTES: int = _MAGIC_LINK_TTL_DEFAULT
    SESSION_TTL_DAYS: int = _SESSION_TTL_DEFAULT

    # Cloudinary — organizer event-image upload (POST /organizer/events/image). Signed
    # server-side upload only; the API secret must never reach the SPA. Empty
    # CLOUD_NAME = feature disabled (log-only/501, dev without keys still runs).
    CLOUDINARY_CLOUD_NAME: str = ""
    CLOUDINARY_API_KEY: str = ""
    CLOUDINARY_API_SECRET: str = ""

    # Webhooks — Svix signing secret ("whsec_...") shown on the webhook's page in the
    # Resend dashboard. Verifies the svix-id/svix-timestamp/svix-signature headers
    # over the raw request body; do NOT pass it as a URL query param.
    RESEND_WEBHOOK_SECRET: str = ""  # empty = no verification (dev only)

    # LLM providers — empty key means that provider is skipped in the fallback chain
    GROQ_API_KEY: str = ""
    CEREBRAS_API_KEY: str = ""
    MISTRAL_API_KEY: str = ""

    # CORS — pydantic-settings parses a JSON array from the env var (e.g. '["https://eventradar.ee"]')
    # In Render: set CORS_ORIGINS to your Vercel/CF Pages URL before deploying.
    # Dual role: this set also seeds CsrfOriginCheckMiddleware's trusted-origin
    # allowlist (app/main.py, CORS_ORIGINS ∪ {FRONTEND_URL}) — widening it for CORS
    # also widens which Origins are trusted for the CSRF check.
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:4173"]

    # Logging
    LOG_LEVEL: str = LOG_LEVEL_DEFAULT
    LOG_SHIP_URL: str = (
        ""  # e.g. https://api.axiom.co/v1/datasets/event-radar/ingest ; empty = no shipping
    )
    LOG_SHIP_TOKEN: str = ""  # Bearer token for the log drain (Axiom ingest token)

    @field_validator("LOG_LEVEL")
    @classmethod
    def _validate_log_level(cls, v: str) -> str:
        normalized = v.upper()
        if normalized not in logging.getLevelNamesMapping():
            raise ValueError(f"Invalid LOG_LEVEL: {v!r}")
        return normalized


settings = Settings()  # type: ignore[call-arg]
