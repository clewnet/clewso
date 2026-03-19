"""User model — represents an application user."""

from db import Database
from utils.auth import hash_password, verify_password


class User:
    """Domain object for users."""

    def __init__(self, username: str, email: str, password_hash: str = ""):
        self.username = username
        self.email = email
        self.password_hash = password_hash

    def set_password(self, raw_password: str):
        """Hash and store the password."""
        self.password_hash = hash_password(raw_password)

    def check_password(self, raw_password: str) -> bool:
        """Verify a password against the stored hash."""
        return verify_password(raw_password, self.password_hash)

    def save(self, db: Database) -> int:
        """Persist this user to the database."""
        return db.save(
            "users",
            {
                "username": self.username,
                "email": self.email,
                "password_hash": self.password_hash,
            },
        )

    @classmethod
    def from_dict(cls, data: dict) -> "User":
        """Reconstruct a User from a database row."""
        return cls(
            username=data["username"],
            email=data["email"],
            password_hash=data.get("password_hash", ""),
        )
