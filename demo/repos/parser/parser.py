"""User record parser — reads raw API payloads and returns clean records."""


def parse_user(raw: dict) -> dict:
    """Parse a raw user payload from the API into a clean internal record."""
    return {
        "id": raw["id"],
        "username": raw["name"],  # BUG: API uses "username" key, not "name"
        "email": raw["email"],
        "active": raw.get("active", True),
    }


def parse_users(raw_list: list[dict]) -> list[dict]:
    """Parse a list of raw user payloads."""
    return [parse_user(r) for r in raw_list]


def find_user_by_username(raw_list: list[dict], username: str) -> dict | None:
    """Find a user by username from a list of raw payloads."""
    parsed = parse_users(raw_list)
    for user in parsed:
        if user["username"] == username:
            return user
    return None
