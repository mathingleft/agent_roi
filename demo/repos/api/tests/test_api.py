import pytest
import asyncio
from api import get_user, get_all_users, get_user_email


def run(coro):
    return asyncio.run(coro)


def test_get_user_returns_dict():
    user = run(get_user(1))
    assert isinstance(user, dict), f"Expected dict, got {type(user)}"
    assert user["name"] == "Alice"


def test_get_user_missing():
    user = run(get_user(999))
    assert user is None


def test_get_all_users():
    users = run(get_all_users())
    assert len(users) == 3


def test_get_user_email():
    email = run(get_user_email(2))
    assert email == "bob@example.com"


def test_get_user_email_missing():
    email = run(get_user_email(999))
    assert email is None
