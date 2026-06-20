def solve(N):
    """Given a positive integer N, return sum of its digits in binary.
    >>> solve(1000)
    '1'
    >>> solve(150)
    '110'
    """
    return bin([int(i) for i in str(N)][-1])[2:]
