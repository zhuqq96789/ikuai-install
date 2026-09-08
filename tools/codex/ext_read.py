#!/usr/bin/env python3
import argparse
import os
import struct
from pathlib import Path


EXTENT_MAGIC = 0xF30A


class ExtImage:
    def __init__(self, path: Path):
        self.path = path
        self.f = path.open("rb")
        sb = self._read_at(1024, 1024)
        self.block_size = 1024 << struct.unpack_from("<I", sb, 24)[0]
        self.blocks_per_group = struct.unpack_from("<I", sb, 32)[0]
        self.inodes_per_group = struct.unpack_from("<I", sb, 40)[0]
        self.inode_size = struct.unpack_from("<H", sb, 88)[0] or 128
        self.first_data_block = struct.unpack_from("<I", sb, 20)[0]
        self.group_desc_size = struct.unpack_from("<H", sb, 254)[0] or 32
        self.group_desc_offset = (self.first_data_block + 1) * self.block_size

    def _read_at(self, offset: int, size: int) -> bytes:
        self.f.seek(offset)
        return self.f.read(size)

    def _block(self, block_no: int) -> bytes:
        return self._read_at(block_no * self.block_size, self.block_size)

    def inode(self, ino: int) -> bytes:
        group = (ino - 1) // self.inodes_per_group
        index = (ino - 1) % self.inodes_per_group
        gd = self._read_at(self.group_desc_offset + group * self.group_desc_size, self.group_desc_size)
        inode_table = struct.unpack_from("<I", gd, 8)[0]
        return self._read_at(inode_table * self.block_size + index * self.inode_size, self.inode_size)

    def inode_size_bytes(self, inode: bytes) -> int:
        lo = struct.unpack_from("<I", inode, 4)[0]
        hi = struct.unpack_from("<I", inode, 108)[0] if len(inode) >= 112 else 0
        return lo | (hi << 32)

    def extents(self, inode: bytes):
        root = inode[40:100]
        magic, entries, _max_entries, depth, _gen = struct.unpack_from("<HHHHI", root, 0)
        if magic != EXTENT_MAGIC:
            raise ValueError("inode does not use extents")
        return list(self._extent_node(root, depth))

    def _extent_node(self, node: bytes, depth: int):
        _magic, entries, _max_entries, _depth, _gen = struct.unpack_from("<HHHHI", node, 0)
        pos = 12
        if depth == 0:
            for _ in range(entries):
                _ee_block, ee_len, ee_start_hi, ee_start_lo = struct.unpack_from("<IHHI", node, pos)
                pos += 12
                yield ee_start_lo | (ee_start_hi << 32), ee_len & 0x7FFF
        else:
            for _ in range(entries):
                _ei_block, ei_leaf_lo, ei_leaf_hi, _unused = struct.unpack_from("<IIHH", node, pos)
                pos += 12
                child = self._block(ei_leaf_lo | (ei_leaf_hi << 32))
                yield from self._extent_node(child, depth - 1)

    def read_inode_data(self, ino: int) -> bytes:
        inode = self.inode(ino)
        size = self.inode_size_bytes(inode)
        parts = []
        remaining = size
        try:
            block_runs = self.extents(inode)
        except ValueError:
            block_runs = [(block, 1) for block in self._traditional_blocks(inode, size) if block]
        for block, count in block_runs:
            chunk = self._read_at(block * self.block_size, count * self.block_size)
            parts.append(chunk[:remaining])
            remaining -= len(parts[-1])
            if remaining <= 0:
                break
        return b"".join(parts)[:size]

    def _traditional_blocks(self, inode: bytes, size: int):
        pointers = struct.unpack_from("<15I", inode, 40)
        blocks_needed = (size + self.block_size - 1) // self.block_size
        yielded = 0

        def emit(block: int):
            nonlocal yielded
            if yielded >= blocks_needed:
                return False
            yielded += 1
            return block

        for block in pointers[:12]:
            out = emit(block)
            if out is False:
                return
            yield out

        ptrs_per_block = self.block_size // 4

        def read_pointer_block(block: int):
            if not block:
                return []
            data = self._block(block)
            return struct.unpack_from(f"<{ptrs_per_block}I", data, 0)

        def walk_indirect(block: int, depth: int):
            if not block:
                return
            for child in read_pointer_block(block):
                if yielded >= blocks_needed:
                    return
                if depth == 1:
                    out = emit(child)
                    if out is False:
                        return
                    yield out
                else:
                    yield from walk_indirect(child, depth - 1)

        yield from walk_indirect(pointers[12], 1)
        yield from walk_indirect(pointers[13], 2)
        yield from walk_indirect(pointers[14], 3)

    def list_dir(self, ino: int):
        data = self.read_inode_data(ino)
        pos = 0
        out = []
        while pos + 8 <= len(data):
            child, rec_len, name_len, file_type = struct.unpack_from("<IHBB", data, pos)
            if rec_len < 8:
                break
            name = data[pos + 8 : pos + 8 + name_len].decode("utf-8", "replace")
            if child and name not in (".", ".."):
                out.append((name, child, file_type))
            pos += rec_len
        return out

    def resolve(self, path: str) -> int:
        ino = 2
        for part in path.strip("/").split("/"):
            if not part:
                continue
            for name, child, _file_type in self.list_dir(ino):
                if name == part:
                    ino = child
                    break
            else:
                raise FileNotFoundError(path)
        return ino


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("image", type=Path)
    parser.add_argument("paths", nargs="+")
    parser.add_argument("--extract-dir", type=Path)
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()
    img = ExtImage(args.image)
    for path in args.paths:
        try:
            ino = img.resolve(path)
            inode = img.inode(ino)
            mode = struct.unpack_from("<H", inode, 0)[0]
            size = img.inode_size_bytes(inode)
            print(f"{path}: inode={ino} mode={oct(mode)} size={size}")
            if args.list:
                for name, child, file_type in img.list_dir(ino):
                    print(f"  {name}\tinode={child}\ttype={file_type}")
            if args.extract_dir and (mode & 0o170000) == 0o100000:
                out = args.extract_dir / path.lstrip("/")
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(img.read_inode_data(ino))
                os.chmod(out, mode & 0o777)
        except FileNotFoundError:
            print(f"{path}: missing")


if __name__ == "__main__":
    main()
