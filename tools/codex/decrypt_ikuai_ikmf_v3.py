#!/usr/bin/env python3
import argparse
import hashlib
import lzma
import struct
import sys
from pathlib import Path


SECRET = bytes.fromhex("42712a9fd3556c1888e41d0b63af72c6195eb134cd078a90ef2c446da813f75b")

LABEL_MANIFEST_GATE = b"ikuai-rootfs-manifest-gate-v1"
LABEL_TEXT_GATE = b"ikuai-rootfs-text-gate-v1"
LABEL_CTX_KDF = b"ikuai-rootfs-ctx-kdf-v1"
LABEL_CTX_INIT = b"ikuai-rootfs-ctx-init-v1"
LABEL_STATE_MAC = b"ikuai-rootfs-state-mac-v1"
LABEL_ROOTFS_KEY = b"ikuai-rootfs-ctx-rootfs-key-v1"

CRC_NIBBLE_TABLE = [
    0x00000000, 0x1DB71064, 0x3B6E20C8, 0x26D930AC,
    0x76DC4190, 0x6B6B51F4, 0x4DB26158, 0x5005713C,
    0xEDB88320, 0xF00F9344, 0xD6D6A3E8, 0xCB61B38C,
    0x9B64C2B0, 0x86D3D2D4, 0xA00AE278, 0xBDBDF21C,
]


def u32(x: int) -> int:
    return x & 0xFFFFFFFF


def rol32(x: int, n: int) -> int:
    x &= 0xFFFFFFFF
    return ((x << n) | (x >> (32 - n))) & 0xFFFFFFFF


def ror8(x: int, n: int) -> int:
    x &= 0xFF
    n &= 7
    return ((x >> n) | (x << (8 - n))) & 0xFF


def sha256(*parts: bytes) -> bytes:
    h = hashlib.sha256()
    for part in parts:
        h.update(part)
    return h.digest()


def all_zero(buf: bytes) -> bool:
    return not any(buf)


def ik_crc32(buf: bytes) -> int:
    crc = 0xFFFFFFFF
    for b in buf:
        idx = (crc ^ b) & 0x0F
        crc = (crc >> 4) ^ CRC_NIBBLE_TABLE[idx]
        idx = (crc ^ (b >> 4)) & 0x0F
        crc = (crc >> 4) ^ CRC_NIBBLE_TABLE[idx]
    return (~crc) & 0xFFFFFFFF


def gate_gmkg(a: bytes, b: bytes, c: bytes, actual_len: int, total_len: int) -> int:
    if all_zero(a):
        return 0
    eax = u32(actual_len ^ total_len ^ 0x696B6D67)
    edi = 0
    ecx = 0
    edx = 0
    for i in range(32):
        ecx = a[i]
        eax = rol32(eax, 5)
        edx = b[i] ^ c[i]
        eax = u32(eax ^ edi)
        edi = u32(edi + 0x27D4EB2D)
        ecx = rol32(ecx ^ eax, 7)
        eax = u32(ecx ^ edx)
    return 0x696B6D67 if ecx == edx else eax


def gate_gtkg(a: bytes, b: bytes, c: bytes, actual_len: int, total_len: int) -> int:
    if all_zero(a):
        return 0
    eax = u32(actual_len ^ total_len ^ 0x696B7467)
    edi = 0
    ecx = 0
    edx = 0
    for i in range(32):
        ecx = a[i]
        eax = rol32(eax, 5)
        edx = b[i] ^ c[i]
        eax = u32(eax ^ edi)
        edi = u32(edi + 0x045D9F3B)
        ecx = rol32(ecx ^ eax, 7)
        eax = u32(ecx ^ edx)
    return 0x696B7467 if ecx == edx else eax


def ctx_check(ctx: bytearray) -> int:
    if not ctx:
        return 0
    edx = (
        struct.unpack_from("<I", ctx, 0x108)[0]
        ^ struct.unpack_from("<I", ctx, 0x118)[0]
        ^ struct.unpack_from("<I", ctx, 0x10C)[0]
        ^ struct.unpack_from("<I", ctx, 0x110)[0]
        ^ 0x696B6374
    )
    eax = 0
    for b in ctx[0x11C:0x13C]:
        edx = rol32(edx, 5)
        edx = u32(edx ^ eax)
        eax = u32(eax - 0x61C8864F)
        edx = u32(edx ^ b)
        if eax == 0xC6EF3620:
            break
    eax = 0
    for b in ctx[0x64:0x84]:
        edx = rol32(edx, 5)
        edx = u32(edx ^ eax)
        eax = u32(eax + 0x7F4A7C15)
        edx = u32(edx ^ b)
        if eax == 0xE94F82A0:
            break
    eax = struct.unpack_from("<I", ctx, 0x60)[0] ^ struct.unpack_from("<I", ctx, 0x84)[0] ^ edx
    edx = 0
    edi = 0
    for b in ctx[0x88:0xA8]:
        eax = rol32(eax, 3)
        eax = u32(eax ^ edx)
        edx = u32(edx + 0x1F123BB5)
        esi = eax
        edi = b
        eax = u32(edi ^ esi)
        if edx == 0xE24776A0:
            break
    return 0x696B7569 if edi == esi else eax


def kdf_digest(ctx0: bytes, ctx20: bytes, ctx40: bytes, gate60: int, ctx64: bytes,
               gate84: int, ctxa8: bytes, ctxc8: bytes, ctxe8: bytes,
               actual_len: int, total_len: int) -> bytes:
    return sha256(
        SECRET,
        LABEL_STATE_MAC,
        ctx0,
        ctx20,
        ctx40,
        struct.pack("<I", gate60),
        ctx64,
        struct.pack("<I", gate84),
        ctxa8,
        ctxc8,
        ctxe8,
        struct.pack("<I", actual_len),
        struct.pack("<I", total_len),
    )


def build_context(ikmf: bytes, actual_len: int, total_len: int, code_hash: bytes) -> bytearray:
    if ikmf[:4] != b"IKMF":
        raise ValueError("IKMF magic not found")
    version, hsize, flags = struct.unpack_from("<III", ikmf, 4)
    len1, len2 = struct.unpack_from("<QQ", ikmf, 0x10)
    if (version, hsize, flags) != (3, 0x80, 0):
        raise ValueError(f"unsupported IKMF header {(version, hsize, flags)}")
    if len1 != actual_len or len2 != actual_len:
        raise ValueError("IKMF embedded lengths do not match rootfs length")
    if ikmf[0x60:0x80] != code_hash:
        raise ValueError("kernel IKMF code hash does not match this rootfs")

    h_hdr = sha256(ikmf[:0x80])
    h_sig = sha256(ikmf[0x80:0x180])
    digest_manifest = sha256(
        SECRET,
        LABEL_MANIFEST_GATE,
        h_hdr,
        h_sig,
        struct.pack("<I", actual_len),
        struct.pack("<I", total_len),
    )
    manifest_gate = gate_gmkg(digest_manifest, h_hdr, h_sig, actual_len, total_len)
    if manifest_gate == 0:
        raise ValueError("manifest gate is zero")

    digest_text = sha256(
        SECRET,
        LABEL_TEXT_GATE,
        code_hash,
        code_hash,
        h_hdr,
        h_sig,
        struct.pack("<I", actual_len),
        struct.pack("<I", total_len),
    )
    text_gate = gate_gtkg(digest_text, h_hdr, h_sig, actual_len, total_len)
    if text_gate == 0:
        raise ValueError("text gate is zero")

    ctx = bytearray(0x13C)
    ctx[0x00:0x20] = h_hdr
    ctx[0x20:0x40] = h_sig
    ctx[0x40:0x60] = digest_manifest
    struct.pack_into("<I", ctx, 0x60, manifest_gate)
    ctx[0x64:0x84] = digest_text
    struct.pack_into("<I", ctx, 0x84, text_gate)
    ctx[0xA8:0xC8] = ikmf[0x20:0x40]
    ctx[0xC8:0xE8] = ikmf[0x40:0x60]
    ctx[0xE8:0x108] = ikmf[0x60:0x80]
    struct.pack_into("<I", ctx, 0x108, actual_len)
    struct.pack_into("<I", ctx, 0x10C, total_len)

    ctx[0x88:0xA8] = kdf_digest(
        ctx[0x00:0x20], ctx[0x20:0x40], ctx[0x40:0x60],
        manifest_gate, ctx[0x64:0x84], text_gate,
        ctx[0xA8:0xC8], ctx[0xC8:0xE8], ctx[0xE8:0x108],
        actual_len, total_len,
    )

    init_digest = sha256(
        SECRET,
        LABEL_CTX_INIT,
        ctx[0x00:0x20],
        ctx[0x20:0x40],
        ctx[0x40:0x60],
        ctx[0x60:0x64],
        ctx[0x64:0x84],
        ctx[0x84:0x88],
        ctx[0x88:0xA8],
        ctx[0xE8:0x108],
        ctx[0x108:0x10C],
        ctx[0x10C:0x110],
        ctx[0xC8:0xE8],
    )
    ctx[0x11C:0x13C] = init_digest
    struct.pack_into("<I", ctx, 0x118, 1)

    ctx[0x11C:0x13C] = sha256(
        SECRET,
        ctx[0x11C:0x13C],
        LABEL_CTX_KDF,
        ctx[0xA8:0xC8],
    )
    struct.pack_into("<I", ctx, 0x118, 2)
    return ctx


def derive_rootfs_key(ctx: bytearray, seed16: bytes) -> bytes:
    expected = kdf_digest(
        ctx[0x00:0x20], ctx[0x20:0x40], ctx[0x40:0x60],
        struct.unpack_from("<I", ctx, 0x60)[0], ctx[0x64:0x84],
        struct.unpack_from("<I", ctx, 0x84)[0],
        ctx[0xA8:0xC8], ctx[0xC8:0xE8], ctx[0xE8:0x108],
        struct.unpack_from("<I", ctx, 0x108)[0],
        struct.unpack_from("<I", ctx, 0x10C)[0],
    )
    if expected != ctx[0x88:0xA8]:
        raise ValueError("ctx KDF verification failed")
    d = sha256(
        SECRET,
        ctx[0x11C:0x13C],
        seed16,
        ctx[0x20:0x40],
        ctx[0x64:0x84],
        ctx[0x84:0x88],
        ctx[0x60:0x64],
        ctx[0x88:0xA8],
        LABEL_ROOTFS_KEY,
    )
    return d[:16]


def rc4_ksa(key: bytes) -> list[int]:
    s = list(range(256))
    j = 0
    for i in range(256):
        j = (j + s[i] + key[i % len(key)]) & 0xFF
        s[i], s[j] = s[j], s[i]
    return s


def init_stream_state(key: bytes) -> tuple[list[int], list[int], list[int]]:
    n = 0x800
    rounds = 3
    r8d = 16
    seed_step = r8d * len(key) * 0x12FE5
    seed_acc = seed_step
    const = 0x03E88CB3C9484E2B
    state = [0] * n
    for i in range(n):
        q = ((seed_acc * const) >> 64) >> 1
        state[i] = (key[i % len(key)] + q) & 0xFF
        seed_acc = (seed_acc + seed_step) & 0xFFFFFFFFFFFFFFFF

    for i in range(n):
        pos = (13 + 7 * i) % n
        state[i] ^= (state[pos] + i) & 0xFF

    for i in range(n):
        prev = (n + i - 1) % n
        nxt = (i + 1) % n
        v = ((state[prev] + state[i] + state[nxt]) & 0xFF) ^ rol8(state[i], 1)
        state[i] = v & 0xFF

    rc4s = rc4_ksa(key)
    inv = [0] * 256
    for i, v in enumerate(rc4s):
        inv[v] = i

    for i in range(n):
        shift = (i & 3) * 8
        state[i] = ((r8d >> shift) ^ rc4s[state[i]]) & 0xFF
    return state, rc4s, inv


def rol8(x: int, n: int) -> int:
    x &= 0xFF
    n &= 7
    return ((x << n) | (x >> (8 - n))) & 0xFF


def decrypt_payload(cipher: bytes, key: bytes) -> bytes:
    state, _rc4s, inv = init_stream_state(key)
    out = bytearray(cipher)
    n = 0x800
    actual_len = len(out)
    offset_base = 0
    scale = 1
    for round_idx in (2, 1, 0):
        ebx = actual_len + round_idx
        for j, b in enumerate(out):
            rem = (offset_base + 17 * round_idx + j) % n
            edx0 = state[rem] * scale + ebx
            ecx = edx0 >> 8
            x = (b - round_idx) & 0xFF
            x = (x - ecx) & 0xFF
            x ^= ecx & 0xFF
            x = ror8(x, (edx0 & 7) + 1)
            x = (x - (edx0 + round_idx)) & 0xFF
            out[j] = inv[x]
    return bytes(out)


def kernel_code_hash(vmlinux: Path) -> bytes:
    data = vmlinux.read_bytes()
    init_text_va = 0xFFFFFFFF82B8C000
    init_text_off = 0x1F8C000
    start_va = 0xFFFFFFFF82BDDFA8
    end_va = 0xFFFFFFFF82BE01BB
    start = start_va - init_text_va + init_text_off
    end = end_va - init_text_va + init_text_off
    return sha256(data[start:end])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("rootfs")
    parser.add_argument("vmlinux")
    parser.add_argument("output")
    args = parser.parse_args()

    raw = Path(args.rootfs).read_bytes()
    ikmf_off = raw.rfind(b"IKMF")
    if ikmf_off < 20:
        raise SystemExit("IKMF not found")
    actual_len = ikmf_off - 20
    total_len = len(raw) - 0x100
    pre20 = raw[actual_len:ikmf_off]
    cipher = raw[:actual_len]
    ikmf = raw[ikmf_off:ikmf_off + 0x280]
    code_hash = kernel_code_hash(Path(args.vmlinux))
    ctx = build_context(ikmf, actual_len, total_len, code_hash)
    key = derive_rootfs_key(ctx, pre20[:16])
    plain = decrypt_payload(cipher, key)

    plain_sha = sha256(plain)
    crc1 = ik_crc32(plain)
    crc2 = ik_crc32(struct.pack(">I", crc1))
    stored_hash = struct.unpack_from("<I", raw, actual_len + 0x10)[0]
    print(f"actual_len={actual_len}")
    print(f"total_len={total_len}")
    print(f"code_hash={code_hash.hex()}")
    print(f"rootfs_key={key.hex()}")
    print(f"plain_sha256={plain_sha.hex()}")
    print(f"expected_plain_sha256={ikmf[0x20:0x40].hex()}")
    print(f"crc1=0x{crc1:08x} crc2_be=0x{crc2:08x} stored_le=0x{stored_hash:08x}")
    print(f"ctx_state=0x{struct.unpack_from('<I', ctx, 0x118)[0]:08x} ctx_check=0x{ctx_check(ctx):08x}")
    print(f"first16={plain[:16].hex()}")
    if plain_sha != ikmf[0x20:0x40]:
        return 2
    # Validate the whole compressed stream, including its embedded checksum.
    decoder = lzma.LZMADecompressor()
    decoded = decoder.decompress(plain)
    if not decoder.eof or decoder.unused_data:
        raise ValueError("incomplete XZ stream or unexpected trailing bytes")
    print(f"xz_integrity=PASS decompressed_sha256={sha256(decoded).hex()}")
    if crc2 != stored_hash:
        print("warning: legacy four-byte field interpretation remains unverified; "
              "IKMF plaintext SHA256 and XZ checksum both passed")
    Path(args.output).write_bytes(plain)
    return 0


if __name__ == "__main__":
    sys.exit(main())
