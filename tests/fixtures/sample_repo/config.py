"""Application configuration loaded from environment variables."""

import os


class Settings:
    """Central configuration object."""

    def __init__(self):
        self.app_name = os.getenv("APP_NAME", "sample-app")
        self.debug = os.getenv("DEBUG", "false").lower() == "true"
        self.database_url = os.getenv("DATABASE_URL", "sqlite:///data.db")
        self.secret_key = os.getenv("SECRET_KEY", "change-me")


def get_settings() -> Settings:
    """Factory for settings singleton."""
    return Settings()
