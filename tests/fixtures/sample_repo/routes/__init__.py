"""Route registration for the application."""

from routes.users import handle_create_user, handle_get_user


def register_routes(app: dict):
    """Attach all route handlers to the application."""
    app["routes"] = {
        "POST /users": handle_create_user,
        "GET /users/:id": handle_get_user,
    }
