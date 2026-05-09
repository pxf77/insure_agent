import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./hermes.db")
    service_name: str = "hermes-trading-assistant"


def get_settings() -> Settings:
    return Settings()
