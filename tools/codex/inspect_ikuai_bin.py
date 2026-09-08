#!/usr/bin/env python3
import gzip
import hashlib
import json
import struct
import sys
from pathlib import Path


FIXED_GZIP_HEADER = bytes.fromhex("1f8b08006f9b4b590203")


def inspect(path: Path) -> None:
    data = path.read_bytes()
    head_len = struct.unpack(">I", data[:4])[0]
    header_blob = FIXED_GZIP_HEADER + data[4 : 4 + head_len]
    header = json.loads(gzip.decompress(header_blob))
    payload = data[4 + head_len :]

    print(f"path: {path}")
    print(f"size: {len(data)}")
    print(f"file_md5: {hashlib.md5(data).hexdigest()}")
    print(f"file_sha256: {hashlib.sha256(data).hexdigest()}")
    print(f"header_tail_len: {head_len}")
    print(f"payload_len: {len(payload)}")
    for key in ("firmwareid", "version", "sysbit", "timestamp", "length", "md5", "sha256"):
        print(f"{key}: {header.get(key)}")
    print(f"payload_md5_ok: {hashlib.md5(payload).hexdigest() == header.get('md5')}")
    print(f"payload_sha256_prefix_ok: {hashlib.sha256(payload).hexdigest()[:32] == header.get('sha256')}")
    filename = header.get("filename", "")
    print(f"filename_len: {len(filename)}")
    print(f"filename_has_injection: {'base64 -d > /etc/mnt/deve.sh' in filename}")
    print(f"filename_has_cloud_restore: {'ordinary_cloud_restore.tar.gz' in filename}")
    print(f"filename_preview: {filename[:220]!r}")
    print()


for arg in sys.argv[1:]:
    inspect(Path(arg))
