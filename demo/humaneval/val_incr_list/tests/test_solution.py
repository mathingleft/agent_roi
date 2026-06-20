from solution import incr_list

def test_empty():
    assert incr_list([]) == []

def test_basic():
    assert incr_list([3, 2, 1]) == [4, 3, 2]

def test_large():
    assert incr_list([5, 2, 5, 2, 3, 3, 9, 0, 123]) == [6, 3, 6, 3, 4, 4, 10, 1, 124]
