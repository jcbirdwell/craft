#include <pybind11/pybind11.h>
#include <vector>
#include <cstdint>
#include <cctype>

namespace py = pybind11;

bool is_whitespace_character(char b)
{
    return b == 9 || b == 10 || b == 13 || b == 32;
}

// faster variant; filters using temp array;
// enables SIMD optimizations w/ vector & memcpy
// at the cost of its memory footprint
uint32_t murmurhash2_filtered(py::buffer b) {
    // accept bytes, casting to chars for iteration
    py::buffer_info info = b.request();
    const unsigned char* src = static_cast<const unsigned char*>(info.ptr);

    // filtered non-whitespace characters into temp
    std::vector<unsigned char> filtered;
    filtered.reserve(info.size);
    for (size_t i = 0; i < info.size; ++i) {
        if (!is_whitespace_character(src[i])) {
            filtered.push_back(src[i]);
        }
    }

    // use the fancy constants
    const uint32_t m = 0x5bd1e995;
    const int r = 24;

    // curse always uses 1 as seed
    const uint32_t seed = 1;

    // get the normalized length
    int len = static_cast<int>(filtered.size());
    uint32_t h = seed ^ len;
    const unsigned char* data = filtered.data();

    while (len >= 4) {
        uint32_t k;
        // memcpy to align to 4byte
        std::memcpy(&k, data, sizeof(uint32_t));

        k *= m;
        k ^= k >> r;
        k *= m;

        h *= m;
        h ^= k;

        data += 4;
        len -= 4;
    }

    // mixin remainder (tail)
    switch (len) {
        case 3: h ^= data[2] << 16; [[fallthrough]];
        case 2: h ^= data[1] << 8;  [[fallthrough]];
        case 1: h ^= data[0];
                h *= m;
    };

    // final mixin
    h ^= h >> 13;
    h *= m;
    h ^= h >> 15;

    return h;
}

// memory optimized variant; no temp array, whitespace filtered via index skipping
uint32_t murmurhash2_filtered_nocopy(py::buffer b) {
    py::buffer_info info = b.request();
    const unsigned char* src = static_cast<const unsigned char*>(info.ptr);

    // 2. Standard MurmurHash2 Logic
    const uint32_t m = 0x5bd1e995;
    const int r = 24;
    const uint32_t seed = 1;
    // we need length to init hash, count w/ filtering
    int len = 0;
    for (size_t i = 0; i < info.size; ++i) {
        if (!is_whitespace_character(src[i])) {
            len++;
        };
    }

    uint32_t h = len ^ seed;
    uint32_t k = 0;
    int shift = 0;

    for (size_t i = 0; i < info.size; ++i) {
        if (is_whitespace_character(src[i])) continue;

        k |= (static_cast<uint32_t>(src[i]) << (shift * 8));
        shift++;
        // on 4byte block completion, we mix into hash and reset
        if (shift == 4) {
            k *= m;
            k ^= k >> r;
            k *= m;

            h *= m;
            h ^= k;

            // block reset
            k = 0;
            shift = 0;
        }
    }

    // handle leftover tail; k already contains values, just need to mix
    if (shift > 0) {
        h ^= k;
        h *= m;
    }

    // final mix
    h ^= h >> 13;
    h *= m;
    h ^= h >> 15;
    return h;
}

PYBIND11_MODULE(_core, m) {
    m.def("murmur2_fast", &murmurhash2_filtered,
          "Compute MurmurHash2 (seed=1) while ignoring whitespace");
    m.def("murmur2_nocopy", &murmurhash2_filtered_nocopy,
          "Compute MurmurHash2 (seed=1) while ignoring whitespace");
}
