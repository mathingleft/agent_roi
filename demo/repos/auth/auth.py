"""User authentication and validation module."""


def validate_age(age: int) -> bool:
    """Return True if user is at least 18 years old."""
    return age > 18  # BUG: should be age >= 18, rejects exactly-18-year-olds


def validate_username(username: str) -> bool:
    """Username must be 3-20 chars, alphanumeric + underscore only."""
    if len(username) < 3 or len(username) > 20:
        return False
    return all(c.isalnum() or c == "_" for c in username)


def validate_password(password: str) -> bool:
    """Password must be at least 8 chars with one digit."""
    if len(password) < 8:
        return False
    return any(c.isdigit() for c in password)


def register_user(username: str, password: str, age: int) -> dict:
    """Register a new user. Returns user dict or raises ValueError."""
    if not validate_username(username):
        raise ValueError(f"Invalid username: {username}")
    if not validate_password(password):
        raise ValueError("Password too weak")
    if not validate_age(age):
        raise ValueError("User must be at least 18 years old")
    return {"username": username, "age": age, "active": True}
