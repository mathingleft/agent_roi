from solution import rolling_max

def test_basic():
    assert rolling_max([1, 2, 3, 2, 3, 4, 2]) == [1, 2, 3, 3, 3, 4, 4]

def test_decreasing():
    assert rolling_max([5, 4, 3, 2, 1]) == [5, 5, 5, 5, 5]

def test_single():
    assert rolling_max([3]) == [3]

def test_all_same():
    assert rolling_max([2, 2, 2]) == [2, 2, 2]
