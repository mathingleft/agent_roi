from solution import encode_shift, decode_shift
import string, random

def test_roundtrip():
    for _ in range(20):
        s = ''.join(random.choice(string.ascii_lowercase) for _ in range(15))
        assert decode_shift(encode_shift(s)) == s

def test_known():
    assert decode_shift(encode_shift("hello")) == "hello"
    assert decode_shift(encode_shift("abcde")) == "abcde"
