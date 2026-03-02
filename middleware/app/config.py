from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str
    EVOLUTION_API_URL: str = "http://evolution-api:8080"
    EVOLUTION_API_KEY: str
    ODOO_WEBHOOK_URL: str
    ODOO_API_KEY: str
    MIDDLEWARE_API_KEY: str
    RETRY_MAX_ATTEMPTS: int = 5
    RETRY_BASE_DELAY: float = 1.0
    ODOO_FORWARD_WORKERS: int = 10
    ODOO_FORWARD_QUEUE_SIZE: int = 1000
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"

    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()
