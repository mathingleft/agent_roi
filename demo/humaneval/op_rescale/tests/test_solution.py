from solution import rescale_to_unit

def test_basic():
    assert rescale_to_unit([2.0, 49.9]) == [0.0, 1.0]

def test_reversed():
    assert rescale_to_unit([100.0, 49.9]) == [1.0, 0.0]

def test_five():
    assert rescale_to_unit([1.0, 2.0, 3.0, 4.0, 5.0]) == [0.0, 0.25, 0.5, 0.75, 1.0]
