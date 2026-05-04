from struct import unpack_from
from ._core import murmur2_fast, murmur2_nocopy

__all__ = ['murmur2_fast', 'murmur2_nocopy', 'murmur2_python']


def murmur2_python(data, length):
    """32-bit MurmurHash2 implementation in pure Python."""
    if isinstance(data, str):
        data = data.encode('utf-8')
    # mixing constants
    m = 0x5bd1e995
    r = 24

    MASK = 0xFFFFFFFF
    # Initialize the hash with forced seed of 1
    h = (1 ^ length) & MASK
    # Mix 4 bytes at a time into the hash
    i = 0
    ignore = {9, 10, 13, 32}
    while length >= 4:
        # Unpack 4 bytes as an unsigned 32-bit little-endian integer
        k, = unpack_from("<I", data, i)

        if k in ignore:
            i += 4
            length -= 4
            continue

        k = (k * m) & MASK
        k ^= (k >> r)
        k = (k * m) & MASK
        h = (h * m) & MASK
        h ^= k
        i += 4
        length -= 4
    # Handle the last few bytes of the input array
    if length == 3:
        h ^= data[i + 2] << 16
    if length >= 2:
        h ^= data[i + 1] << 8
    if length >= 1:
        h ^= data[i]
        h = (h * m) & MASK
    # Do a few final mixes of the hash to ensure the last few bytes are well-mixed
    h ^= h >> 13
    h = (h * m) & MASK
    h ^= h >> 15
    return h & MASK


__all__ = ['murmur2']

