from solution import greatest_common_divisor

def test_coprime():
    assert greatest_common_divisor(3, 7) == 1

def test_basic():
    assert greatest_common_divisor(10, 15) == 5

def test_larger():
    assert greatest_common_divisor(49, 14) == 7

def test_big():
    assert greatest_common_divisor(144, 60) == 12
