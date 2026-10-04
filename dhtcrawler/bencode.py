"""
High-performance Bencode encoder and decoder for BitTorrent protocols.
Supports decoding streams with offset tracking for BEP 09 ut_metadata.
"""

from typing import Any, Tuple, Union


class BencodeError(Exception):
    pass


def bdecode_with_index(data: bytes, index: int = 0) -> Tuple[Any, int]:
    """
    Decodes bencoded data starting at `index`.
    Returns a tuple of (decoded_object, next_index).
    """
    if index >= len(data):
        raise BencodeError("Unexpected end of data")

    char = data[index:index + 1]

    # Integer: i<digits>e
    if char == b'i':
        end = data.find(b'e', index + 1)
        if end == -1:
            raise BencodeError("Unterminated integer")
        num_bytes = data[index + 1:end]
        try:
            num = int(num_bytes)
        except ValueError:
            raise BencodeError(f"Invalid integer: {num_bytes!r}")
        return num, end + 1

    # String / Byte string: <length>:<bytes>
    if b'0' <= char <= b'9':
        colon = data.find(b':', index)
        if colon == -1:
            raise BencodeError("Unterminated string length")
        try:
            length = int(data[index:colon])
        except ValueError:
            raise BencodeError(f"Invalid string length at {index}")
        if length < 0:
            raise BencodeError("Negative string length")
        start = colon + 1
        end = start + length
        if end > len(data):
            raise BencodeError(f"String length {length} exceeds available data")
        return data[start:end], end

    # List: l<items>e
    if char == b'l':
        idx = index + 1
        items = []
        while idx < len(data) and data[idx:idx + 1] != b'e':
            item, idx = bdecode_with_index(data, idx)
            items.append(item)
        if idx >= len(data) or data[idx:idx + 1] != b'e':
            raise BencodeError("Unterminated list")
        return items, idx + 1

    # Dictionary: d<key><value>...e
    if char == b'd':
        idx = index + 1
        items = {}
        while idx < len(data) and data[idx:idx + 1] != b'e':
            key, idx = bdecode_with_index(data, idx)
            if not isinstance(key, bytes):
                raise BencodeError("Dictionary key must be bytes")
            val, idx = bdecode_with_index(data, idx)
            items[key] = val
        if idx >= len(data) or data[idx:idx + 1] != b'e':
            raise BencodeError("Unterminated dictionary")
        return items, idx + 1

    raise BencodeError(f"Unexpected token {char!r} at index {index}")


def bdecode(data: bytes) -> Any:
    """Decodes complete bencoded bytes object."""
    obj, _ = bdecode_with_index(data, 0)
    return obj


def bencode(obj: Any) -> bytes:
    """Encodes a Python object into bencoded bytes."""
    if isinstance(obj, int):
        return f"i{obj}e".encode('ascii')
    elif isinstance(obj, bytes):
        return f"{len(obj)}:".encode('ascii') + obj
    elif isinstance(obj, str):
        b = obj.encode('utf-8')
        return f"{len(b)}:".encode('ascii') + b
    elif isinstance(obj, list) or isinstance(obj, tuple):
        encoded_items = b"".join(bencode(item) for item in obj)
        return b'l' + encoded_items + b'e'
    elif isinstance(obj, dict):
        # Keys must be bytes or strings, sorted in lexicographical byte order
        items = []
        for k, v in obj.items():
            key_bytes = k if isinstance(k, bytes) else str(k).encode('utf-8')
            items.append((key_bytes, v))
        items.sort(key=lambda pair: pair[0])

        encoded_dict = b"".join(bencode(k) + bencode(v) for k, v in items)
        return b'd' + encoded_dict + b'e'
    else:
        raise BencodeError(f"Unsupported type for bencode: {type(obj)}")
