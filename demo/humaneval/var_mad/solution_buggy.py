from typing import List

def mean_absolute_deviation(numbers: List[float]) -> float:
    """Calculate Mean Absolute Deviation around the mean.
    >>> mean_absolute_deviation([1.0, 2.0, 3.0, 4.0])
    1.0
    """
    mean = sum(numbers) / len(numbers)
    return sum(abs(x - mean) for x in numbers) / mean
