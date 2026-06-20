"""Async API client for fetching user data."""
import asyncio


class FakeDatabase:
    """Simulates an async database."""
    def __init__(self):
        self._data = {
            1: {"id": 1, "name": "Alice", "email": "alice@example.com"},
            2: {"id": 2, "name": "Bob", "email": "bob@example.com"},
            3: {"id": 3, "name": "Carol", "email": "carol@example.com"},
        }

    async def fetch_user(self, user_id: int) -> dict | None:
        await asyncio.sleep(0)  # simulate async I/O
        return self._data.get(user_id)

    async def fetch_all_users(self) -> list[dict]:
        await asyncio.sleep(0)
        return list(self._data.values())


db = FakeDatabase()


async def get_user(user_id: int) -> dict | None:
    """Fetch a single user by ID."""
    return db.fetch_user(user_id)  # BUG: missing await — returns coroutine, not dict


async def get_all_users() -> list[dict]:
    """Fetch all users."""
    return await db.fetch_all_users()


async def get_user_email(user_id: int) -> str | None:
    """Return email for a user, or None if not found."""
    user = await get_user(user_id)
    if user is None:
        return None
    return user["email"]
