from solution import get_positive

def test_basic():
    assert get_positive([-1, 2, -4, 3, 5]) == [2, 3, 5]

def test_mixed():
    assert get_positive([5, 3, -5, 2, -3, 3, 9, 0, 123, 1, -10]) == [5, 3, 2, 3, 3, 9, 123, 1]

def test_all_negative():
    assert get_positive([-1, -2]) == []

def test_empty():
    assert get_positive([]) == []
