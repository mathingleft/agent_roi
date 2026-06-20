import pytest
from parser import parse_user, parse_users, find_user_by_username


RAW_USER = {"id": 1, "username": "alice", "email": "alice@example.com", "active": True}
RAW_USER_2 = {"id": 2, "username": "bob", "email": "bob@example.com"}


def test_parse_user_username():
    result = parse_user(RAW_USER)
    assert result["username"] == "alice", f"Expected 'alice', got '{result['username']}'"


def test_parse_user_email():
    result = parse_user(RAW_USER)
    assert result["email"] == "alice@example.com"


def test_parse_user_id():
    result = parse_user(RAW_USER)
    assert result["id"] == 1


def test_parse_user_defaults_active():
    result = parse_user(RAW_USER_2)
    assert result["active"] is True


def test_parse_users_list():
    results = parse_users([RAW_USER, RAW_USER_2])
    assert len(results) == 2
    assert results[0]["username"] == "alice"
    assert results[1]["username"] == "bob"


def test_find_user_by_username():
    result = find_user_by_username([RAW_USER, RAW_USER_2], "bob")
    assert result is not None
    assert result["email"] == "bob@example.com"


def test_find_user_missing():
    result = find_user_by_username([RAW_USER], "charlie")
    assert result is None
