"""User route handlers — registration and lookup."""

from config import get_settings
from db import get_db
from models.user import User


def handle_create_user(request: dict) -> dict:
    """Register a new user account."""
    settings = get_settings()
    db = get_db(settings)

    user = User(
        username=request["username"],
        email=request["email"],
    )
    user.set_password(request["password"])
    user_id = user.save(db)

    db.close()
    return {"id": user_id, "username": user.username}


def handle_get_user(request: dict) -> dict | None:
    """Look up a user by ID."""
    settings = get_settings()
    db = get_db(settings)

    row = db.find_by_id("users", int(request["id"]))
    db.close()

    if row is None:
        return None
    return User.from_dict(row).__dict__
