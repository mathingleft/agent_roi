def encode_shift(s: str):
    """Returns encoded string by shifting every character by 5 in the alphabet."""
    return "".join([chr(((ord(ch) + 5 - ord("a")) % 26) + ord("a")) for ch in s])

def decode_shift(s: str):
    """Takes a string encoded with encode_shift and returns the original."""
    return "".join([chr(((ord(ch) - 5 - ord("a")) % 26) + ord(ch)) for ch in s])
