from solution import fizz_buzz

def test_small():
    assert fizz_buzz(50) == 0

def test_78():
    assert fizz_buzz(78) == 2

def test_79():
    assert fizz_buzz(79) == 3

def test_100():
    assert fizz_buzz(100) == 3
