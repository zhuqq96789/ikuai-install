#!/usr/bin/env python3
"""Extract verified vendor boot files for offline security comparison."""
import gzip
import hashlib
import json
import lzma
import struct
from pathlib import Path

from ext_read import ExtImage


BASE = Path(__file__).resolve().parent / "security-3.7.25"
HEADER = bytes.fromhex("1f8b08006f9b4b590203")


def main():
    for version, build in (("3.7.24", "202608141210"), ("3.7.25", "202609021525")):
        out = BASE / version
        out.mkdir(parents=True, exist_ok=True)
        src = Path.home() / "Downloads" / f"iKuai8_x64_{version}_Build{build}.bin"
        data = src.read_bytes()
        length = struct.unpack_from(">I", data)[0]
        header = json.loads(gzip.decompress(HEADER + data[4:4 + length]))
        payload = data[4 + length:]
        assert hashlib.md5(payload).hexdigest() == header["md5"]
        assert hashlib.sha256(payload).hexdigest().startswith(header["sha256"])
        image = out / "boot-partition.img"
        image.write_bytes(gzip.decompress(payload))
        fs = ExtImage(image)
        hashes = {}
        for name in ("boot/rootfs", "boot/vmlinuz", "boot/grub/grub.cfg"):
            content = fs.read_inode_data(fs.resolve(name))
            target = out / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            hashes[name] = hashlib.sha256(content).hexdigest()
        kernel = (out / "boot/vmlinuz").read_bytes()
        offset = kernel.find(b"\xfd7zXZ\x00")
        assert offset >= 0
        elf = lzma.LZMADecompressor().decompress(kernel[offset:])
        assert elf.startswith(b"\x7fELF")
        (out / "vmlinux").write_bytes(elf)
        info = {"source": str(src), "source_sha256": hashlib.sha256(data).hexdigest(),
                "header": header, "boot_sha256": hashes}
        (out / "source.json").write_text(json.dumps(info, indent=2) + "\n")
        print(json.dumps({"version": version, "boot_sha256": hashes}), flush=True)


if __name__ == "__main__":
    main()
