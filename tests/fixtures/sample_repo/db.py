"""Database connection and persistence layer."""

import sqlite3

from config import Settings


class Database:
    """Simple database wrapper with connection pooling."""

    def __init__(self, settings: Settings):
        self.url = settings.database_url
        self._connection = None

    def connect(self):
        """Establish database connection."""
        self._connection = sqlite3.connect(self.url)
        return self._connection

    def save(self, table: str, data: dict) -> int:
        """Insert a record and return its ID."""
        conn = self.connect()
        columns = ", ".join(data.keys())
        placeholders = ", ".join("?" for _ in data)
        cursor = conn.execute(
            f"INSERT INTO {table} ({columns}) VALUES ({placeholders})",
            list(data.values()),
        )
        conn.commit()
        return cursor.lastrowid

    def find_by_id(self, table: str, record_id: int) -> dict | None:
        """Fetch a single record by ID."""
        conn = self.connect()
        cursor = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (record_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def close(self):
        """Close the database connection."""
        if self._connection:
            self._connection.close()


def get_db(settings: Settings) -> Database:
    """Factory for database instances."""
    return Database(settings)
