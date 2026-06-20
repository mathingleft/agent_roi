import pytest
from auth import validate_age, validate_username, validate_password, register_user


def test_validate_age_over_18():
    assert validate_age(25) is True


def test_validate_age_exactly_18():
    assert validate_age(18) is True, "18-year-olds should be allowed to register"


def test_validate_age_under_18():
    assert validate_age(17) is False


def test_validate_username_valid():
    assert validate_username("john_doe") is True


def test_validate_username_too_short():
    assert validate_username("ab") is False


def test_validate_password_valid():
    assert validate_password("secret42") is True


def test_validate_password_too_short():
    assert validate_password("abc1") is False


def test_register_user_success():
    user = register_user("alice99", "password1", 25)
    assert user["username"] == "alice99"
    assert user["active"] is True


def test_register_user_exactly_18():
    user = register_user("bob_18", "password1", 18)
    assert user["username"] == "bob_18"
