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


settings = Settings()
