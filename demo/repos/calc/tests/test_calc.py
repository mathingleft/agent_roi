import pytest
from calc import add, subtract, divide, multiply


def test_add():
    assert add(2, 3) == 5


def test_subtract():
    assert subtract(5, 3) == 2


def test_divide_exact():
    assert divide(10, 2) == 5


def test_divide_float():
    result = divide(7, 2)
    assert result == 3.5, f"Expected 3.5, got {result}"


def test_multiply():
    assert multiply(3, 4) == 12
