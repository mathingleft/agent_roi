def greatest_common_divisor(a: int, b: int) -> int:
    """Return greatest common divisor of two integers.
    >>> greatest_common_divisor(3, 5)
    1
    >>> greatest_common_divisor(25, 15)
    5
    """
    while b:
        a, b = b, a % b
    return b
