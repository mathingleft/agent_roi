from solution import triangle_area

def test_basic():
    assert triangle_area(5, 3) == 7.5

def test_square():
    assert triangle_area(2, 2) == 2.0

def test_large():
    assert triangle_area(10, 8) == 40.0
