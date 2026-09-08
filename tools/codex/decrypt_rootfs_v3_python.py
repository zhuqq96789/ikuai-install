#!/usr/bin/env python3
import argparse
import struct
from typing import Tuple
from pathlib import Path


HASH_TABLE = bytes(
    [
        0x00, 0x00, 0x00, 0x00, 0x64, 0x10, 0xB7, 0x1D,
        0xC8, 0x20, 0x6E, 0x3B, 0xAC, 0x30, 0xD6, 0x26,
        0x90, 0x41, 0xDE, 0x76, 0xF4, 0x51, 0x6B, 0x6B,
        0x56, 0x61, 0xB2, 0x4D, 0x3C, 0x71, 0x05, 0x50,
        0x20, 0x63, 0xB8, 0xED, 0x43, 0x93, 0x0F, 0xF0,
        0xE8, 0xA3, 0xD6, 0xD6, 0x8C, 0xB3, 0x61, 0xCB,
        0xB0, 0xC2, 0x64, 0x9B, 0xD4, 0xD2, 0xD4, 0x86,
        0x78, 0xE2, 0x0A, 0xA0, 0x1C, 0xF2, 0xDD, 0xBD,
    ]
)
HASH_WORDS = struct.unpack("<16I", HASH_TABLE)
TRAILER_SIZE = 16 + 4 + 256


def rotl8(v: int, s: int) -> int:
    return ((v << s) | (v >> (8 - s))) & 0xFF


def rotr8(v: int, s: int) -> int:
    return ((v >> s) | (v << (8 - s))) & 0xFF


def swap_bytes(val: int) -> int:
    return (
        ((val << 24) & 0xFF000000)
        | ((val << 8) & 0x00FF0000)
        | ((val >> 8) & 0x0000FF00)
        | ((val >> 24) & 0x000000FF)
    )


def hash_raw(data, words) -> int:
    result = 0xFFFFFFFF
    for cur in data:
        tmp = words[(cur ^ (result & 0xFF)) & 0xF] ^ (result >> 4)
        result = words[((tmp & 0xFF) ^ (cur >> 4)) & 0xF] ^ (tmp >> 4)
        result &= 0xFFFFFFFF
    return result


def ikuai_hash(data) -> int:
    h = hash_raw(data, HASH_WORDS)
    h = swap_bytes((~h) & 0xFFFFFFFF)
    hb = struct.pack("<I", h)
    h = hash_raw(hb, HASH_WORDS)
    return swap_bytes((~h) & 0xFFFFFFFF)


def generate_v3_context(seed: bytes) -> Tuple[list, list, list]:
    ext_key = []
    for i in range(2048):
        val = seed[i & 0xF] + (19916032 * (i + 1)) // 131
        ext_key.append(val & 0xFF)
    for i in range(2048):
        ext_key[i] ^= (i + ext_key[(7 * i + 13) % 2048]) & 0xFF
    for i in range(2048):
        prev = ext_key[(2048 + i - 1) % 2048]
        cur = ext_key[i]
        nxt = ext_key[(i + 1) % 2048]
        ext_key[i] = ((prev + cur + nxt) ^ rotl8(cur, 1)) & 0xFF

    perm = list(range(256))
    j = 0
    for i in range(256):
        j = (j + perm[i] + seed[i & 0xF]) & 0xFF
        perm[i], perm[j] = perm[j], perm[i]
    inv_perm = [0] * 256
    for i, v in enumerate(perm):
        inv_perm[v] = i

    for i in range(2048):
        mask = 0x10 >> ((i & 3) * 8)
        ext_key[i] = (mask ^ perm[ext_key[i]]) & 0xFF
    return ext_key, perm, inv_perm


def generate_extended_key(base_key: bytes) -> list:
    ext_key = []
    for i in range(1024):
        val = base_key[i & 0xF] + (19916032 * (i + 1)) // 131
        ext_key.append(val & 0xFF)
    return ext_key


def decrypt_v2_region(data: bytes, actual_size: int) -> Tuple[bytes, bytes, int, int]:
    if len(data) < actual_size + 20:
        raise ValueError("file too small for V2 rootfs region")
    seed = data[actual_size : actual_size + 16]
    authentic_hash = struct.unpack_from("<I", data, actual_size + 16)[0]
    out = bytearray(data[:actual_size])
    ext_key = generate_extended_key(seed)
    size_low = actual_size & 0xFF
    if size_low >= 128:
        size_low -= 256
    for idx in range(actual_size):
        lb = (size_low + ext_key[idx % 1024]) & 0xFF
        diff = (out[idx] - lb) & 0xFF
        shift = (lb % 7) + 1
        out[idx] = rotl8(diff, shift)
    calculated_hash = ikuai_hash(out)
    return bytes(out), seed, authentic_hash, calculated_hash


def decrypt_v3_region(data: bytes, actual_size: int) -> Tuple[bytes, bytes, int, int]:
    if len(data) < actual_size + 20:
        raise ValueError("file too small for V3 rootfs region")
    seed = data[actual_size : actual_size + 16]
    authentic_hash = struct.unpack_from("<I", data, actual_size + 16)[0]
    out = bytearray(data[:actual_size])
    ext_key, _perm, inv_perm = generate_v3_context(seed)

    for round_no in range(2, -1, -1):
        for idx in range(actual_size):
            ev = ext_key[(17 * round_no + idx) % 2048]
            mix = ev + actual_size + round_no
            carry = (mix >> 8) & 0xFF
            shift = (mix & 7) + 1
            val = out[idx]
            val = (val - round_no - carry) & 0xFF
            val ^= carry
            val = rotr8(val, shift)
            val = (val - ((mix + round_no) & 0xFF)) & 0xFF
            out[idx] = inv_perm[val]

    calculated_hash = ikuai_hash(out)
    return bytes(out), seed, authentic_hash, calculated_hash


def decrypt_v3(data: bytes) -> Tuple[bytes, bytes, int, int]:
    if len(data) < TRAILER_SIZE:
        raise ValueError("file too small for V3 rootfs")
    return decrypt_v3_region(data, len(data) - TRAILER_SIZE)


def ikmf_rootfs_len(data: bytes) -> int:
    ikmf = data.rfind(b"IKMF")
    if ikmf < 0:
        raise ValueError("IKMF metadata block not found")
    if ikmf < 20:
        raise ValueError("IKMF metadata has no preceding seed/hash")
    version, header_size, _flags = struct.unpack_from("<III", data, ikmf + 4)
    if version != 3 or header_size < 32:
        raise ValueError(f"unsupported IKMF metadata: version={version} header_size={header_size}")
    rootfs_len = struct.unpack_from("<Q", data, ikmf + 16)[0]
    if rootfs_len + 20 != ikmf:
        raise ValueError(f"unexpected IKMF layout: rootfs_len={rootfs_len} ikmf={ikmf}")
    return int(rootfs_len)


def decrypt_ikmf_v3(data: bytes) -> Tuple[bytes, bytes, int, int]:
    return decrypt_v3_region(data, ikmf_rootfs_len(data))


def decrypt_ikmf_v2(data: bytes) -> Tuple[bytes, bytes, int, int]:
    return decrypt_v2_region(data, ikmf_rootfs_len(data))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--ikmf", action="store_true")
    parser.add_argument("--v2", action="store_true")
    args = parser.parse_args()

    raw = args.input.read_bytes()
    if args.v2:
        plain, seed, authentic_hash, calculated_hash = decrypt_ikmf_v2(raw) if args.ikmf else decrypt_v2_region(raw, len(raw) - 20)
    else:
        plain, seed, authentic_hash, calculated_hash = decrypt_ikmf_v3(raw) if args.ikmf else decrypt_v3(raw)
    if calculated_hash != authentic_hash:
        raise SystemExit(
            f"hash verification failed: calculated=0x{calculated_hash:08x} "
            f"authentic=0x{authentic_hash:08x}"
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(plain)
    print(f"seed={seed.hex()}")
    print(f"hash=0x{calculated_hash:08x}")
    print(f"output={args.output}")
    print(f"size={len(plain)}")


if __name__ == "__main__":
    main()
