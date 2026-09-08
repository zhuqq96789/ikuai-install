#!/usr/bin/env python3
import argparse
import os
import stat
import struct
from pathlib import Path


S_IFMT = 0o170000
S_IFREG = 0o100000
S_IFDIR = 0o040000
S_IFLNK = 0o120000


class Ext4Image:
    def __init__(self, path: Path):
        self.path = path
        self.data = path.read_bytes()
        sb = self.data[1024:2048]
        if struct.unpack_from("<H", sb, 56)[0] != 0xEF53:
            raise ValueError("not an ext filesystem")
        self.inodes_count = struct.unpack_from("<I", sb, 0)[0]
        self.blocks_count = struct.unpack_from("<I", sb, 4)[0]
        self.block_size = 1024 << struct.unpack_from("<I", sb, 24)[0]
        self.blocks_per_group = struct.unpack_from("<I", sb, 32)[0]
        self.inodes_per_group = struct.unpack_from("<I", sb, 40)[0]
        self.first_inode = struct.unpack_from("<I", sb, 84)[0]
        self.inode_size = struct.unpack_from("<H", sb, 88)[0] or 128
        self.groups = (self.blocks_count + self.blocks_per_group - 1) // self.blocks_per_group
        self.gdt_off = 2 * self.block_size if self.block_size == 1024 else self.block_size
        self.group_desc_size = 32

    def group_desc(self, group: int) -> tuple[int, int, int]:
        off = self.gdt_off + group * self.group_desc_size
        return struct.unpack_from("<III", self.data, off)

    def inode_raw(self, ino: int) -> bytes:
        if ino <= 0:
            raise ValueError(f"bad inode {ino}")
        group = (ino - 1) // self.inodes_per_group
        index = (ino - 1) % self.inodes_per_group
        _bb, _ib, inode_table = self.group_desc(group)
        off = inode_table * self.block_size + index * self.inode_size
        return self.data[off:off + self.inode_size]

    def inode_meta(self, ino: int) -> dict:
        raw = self.inode_raw(ino)
        mode = struct.unpack_from("<H", raw, 0)[0]
        size_lo = struct.unpack_from("<I", raw, 4)[0]
        flags = struct.unpack_from("<I", raw, 32)[0]
        size_high = struct.unpack_from("<I", raw, 108)[0]
        size = size_lo | (size_high << 32) if (mode & S_IFMT) == S_IFREG else size_lo
        return {"ino": ino, "raw": raw, "mode": mode, "size": size, "flags": flags}

    def block(self, block_no: int) -> bytes:
        off = block_no * self.block_size
        return self.data[off:off + self.block_size]

    def extent_blocks_from_node(self, block_data: bytes, base: int = 0) -> list[tuple[int, int, int]]:
        magic, entries, _max_entries, depth, _gen = struct.unpack_from("<HHHHI", block_data, base)
        if magic != 0xF30A:
            raise ValueError(f"unsupported non-extent inode/block magic=0x{magic:04x}")
        out = []
        pos = base + 12
        if depth == 0:
            for _ in range(entries):
                logical, length, start_hi, start_lo = struct.unpack_from("<IHHI", block_data, pos)
                length &= 0x7FFF
                physical = (start_hi << 32) | start_lo
                out.append((logical, length, physical))
                pos += 12
        else:
            for _ in range(entries):
                logical, leaf_lo, leaf_hi, _unused = struct.unpack_from("<IIHH", block_data, pos)
                leaf = (leaf_hi << 32) | leaf_lo
                out.extend(self.extent_blocks_from_node(self.block(leaf), 0))
                pos += 12
        return out

    def extents(self, meta: dict) -> list[tuple[int, int, int]]:
        return self.extent_blocks_from_node(meta["raw"], 40)

    def read_file(self, ino: int) -> bytes:
        meta = self.inode_meta(ino)
        if meta["size"] == 0:
            return b""
        mode_type = meta["mode"] & S_IFMT
        if mode_type == S_IFLNK and meta["size"] <= 60:
            return meta["raw"][40:40 + meta["size"]]
        chunks = bytearray(meta["size"])
        for logical, length, physical in self.extents(meta):
            for i in range(length):
                dst = (logical + i) * self.block_size
                if dst >= meta["size"]:
                    break
                src = self.block(physical + i)
                chunks[dst:dst + min(self.block_size, meta["size"] - dst)] = src[:min(self.block_size, meta["size"] - dst)]
        return bytes(chunks)

    def iter_dir(self, ino: int):
        data = self.read_file(ino)
        pos = 0
        while pos + 8 <= len(data):
            child, rec_len, name_len, ftype = struct.unpack_from("<IHBB", data, pos)
            if rec_len < 8:
                break
            name = data[pos + 8:pos + 8 + name_len].decode("utf-8", "surrogateescape")
            if child and name not in (".", ".."):
                yield child, name, ftype
            pos += rec_len

    def walk(self, ino: int = 2, prefix: str = ""):
        for child, name, _ftype in self.iter_dir(ino):
            child_path = f"{prefix}/{name}" if prefix else name
            meta = self.inode_meta(child)
            yield child_path, meta
            if (meta["mode"] & S_IFMT) == S_IFDIR:
                yield from self.walk(child, child_path)

    def extract(self, out_dir: Path):
        out_dir.mkdir(parents=True, exist_ok=True)
        for rel, meta in self.walk():
            target = out_dir / rel
            mode_type = meta["mode"] & S_IFMT
            if mode_type == S_IFDIR:
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if mode_type == S_IFREG:
                target.write_bytes(self.read_file(meta["ino"]))
                try:
                    os.chmod(target, stat.S_IMODE(meta["mode"]))
                except PermissionError:
                    pass
            elif mode_type == S_IFLNK:
                link_target = self.read_file(meta["ino"]).decode("utf-8", "surrogateescape")
                try:
                    if target.exists() or target.is_symlink():
                        target.unlink()
                    os.symlink(link_target, target)
                except OSError:
                    target.write_text(link_target)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("image")
    parser.add_argument("out_dir", nargs="?")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()

    img = Ext4Image(Path(args.image))
    if args.list:
        for rel, meta in img.walk():
            print(f"{meta['ino']:6d} {meta['mode']:06o} {meta['size']:10d} {rel}")
        return 0
    if not args.out_dir:
        raise SystemExit("out_dir is required unless --list is used")
    img.extract(Path(args.out_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
