from solution import sum_to_n

def test_one():
    assert sum_to_n(1) == 1

def test_six():
    assert sum_to_n(6) == 21

def test_hundred():
    assert sum_to_n(100) == 5050
