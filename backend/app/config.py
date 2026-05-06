from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "postgresql+asyncpg://localhost/eventradar"
    SECRET_KEY: str  # required — no default; app fails at startup if unset
    APP_ENV: str = "development"

    FIENTA_BASE_URL: str = "https://fienta.com/api/v1/public/events"
    TELLISKIVI_URL: str = "https://telliskivi.cc/en/events/"
    KULTUURIKATEL_URL: str = "https://kultuurikatel.ee/en/events/"
    FOTOGRAFISKA_URL: str = "https://tallinn.fotografiska.com/en/events"
    FIENTA_ORGANIZER_IDS: list[int] = [3349, 1946, 15, 2111, 17595, 1088, 2704, 8403, 8412, 12106]
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

    # Persona affinity vectors — override in .env to retune without code changes
    PERSONA_UNDERGROUND_CLUBBER_AFFINITY: dict = {
        "categories": {"music": 1.0, "nightlife": 1.0, "arts": 0.4},
        "vibes": {"edgy": 1.0, "alternative": 1.0, "local": 0.6},
        "times": {"late_night": 1.0, "weekend": 0.8},
    }
    PERSONA_NETWORKING_PRO_AFFINITY: dict = {
        "categories": {"business": 1.0, "tech": 1.0, "education": 0.6},
        "vibes": {"professional": 1.0, "informative": 0.8},
        "times": {"weekday": 0.8, "evening": 0.6},
    }
    PERSONA_WEEKEND_HOBBYIST_AFFINITY: dict = {
        "categories": {"sports": 0.8, "crafts": 0.8, "food": 0.7, "outdoors": 0.7},
        "vibes": {"casual": 1.0, "fun": 0.8, "social": 0.6},
        "times": {"weekend": 1.0, "daytime": 0.8},
    }
    PERSONA_CULTURE_BUFF_AFFINITY: dict = {
        "categories": {"arts": 1.0, "theatre": 1.0, "film": 0.8, "exhibition": 0.9},
        "vibes": {"intellectual": 1.0, "curated": 0.8, "inspiring": 0.7},
        "times": {"any": 1.0},
    }
    PERSONA_FAMILY_EXPLORER_AFFINITY: dict = {
        "categories": {"family": 1.0, "outdoors": 0.8, "education": 0.6, "food": 0.5},
        "vibes": {"family_friendly": 1.0, "fun": 0.8, "safe": 0.7},
        "times": {"daytime": 0.9, "weekend": 0.8},
    }

    # Admin / internal security
    ADMIN_USERNAME: str = "admin"  # Basic-auth username for /admin/* endpoints
    ADMIN_PASSWORD: str = ""       # Basic-auth password for /admin/* endpoints; empty = disabled (dev only)
    INTERNAL_TOKEN: str = ""       # X-Internal-Token header for /internal/tick; empty = disabled (dev only)

    # Auth / email
    RESEND_API_KEY: str = ""       # Resend API key for transactional email; empty = log-only (dev)
    FRONTEND_URL: str = "http://localhost:5173"  # Base URL for magic-link verification
    MAGIC_LINK_TTL_MINUTES: int = 15


settings = Settings()
