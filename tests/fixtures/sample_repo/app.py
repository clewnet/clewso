"""Application entry point — wires routes and configuration."""

from config import Settings
from routes import register_routes


def create_app(settings: Settings) -> dict:
    """Create and configure the application."""
    app = {"name": settings.app_name, "debug": settings.debug}
    register_routes(app)
    return app


def main():
    """Boot the application."""
    settings = Settings()
    app = create_app(settings)
    print(f"Starting {app['name']}...")


if __name__ == "__main__":
    main()
