from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_EXPORT_DIR = Path(__file__).resolve().parents[2] / "exports"


class Settings(BaseSettings):
    session_idle_minutes: int = Field(default=30, gt=0)
    session_absolute_hours: int = Field(default=12, gt=0)
    session_secret: str
    initial_username: str
    initial_password: str
    database_url: str = "postgresql://postgres:postgres@localhost:5432/gmc_feed"
    plugins_dir: str = str(Path(__file__).resolve().parents[2] / "plugins")
    export_dir: str = str(DEFAULT_EXPORT_DIR)
    public_base_url: str = "http://localhost:8000"

    @property
    def async_database_url(self) -> str:
        if self.database_url.startswith("postgresql+asyncpg://"):
            return self.database_url
        if self.database_url.startswith("postgresql://"):
            return "postgresql+asyncpg://" + self.database_url.removeprefix(
                "postgresql://"
            )
        if self.database_url.startswith("postgres://"):
            return "postgresql+asyncpg://" + self.database_url.removeprefix(
                "postgres://"
            )
        return self.database_url

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
