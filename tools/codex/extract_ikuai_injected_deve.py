#!/usr/bin/env python3
import base64
import gzip
import json
import re
import struct
import sys
from pathlib import Path


FIXED_GZIP_HEADER = bytes.fromhex("1f8b08006f9b4b590203")


src = Path(sys.argv[1])
dst = Path(sys.argv[2])
data = src.read_bytes()
head_len = struct.unpack(">I", data[:4])[0]
header = json.loads(gzip.decompress(FIXED_GZIP_HEADER + data[4 : 4 + head_len]))
filename = header["filename"]
match = re.search(r"base64 -d > /etc/mnt/deve\.sh <<'([^']+)'\n(.*?)\n\1", filename, re.S)
if not match:
    raise SystemExit("no injected deve.sh base64 block found")
dst.write_bytes(base64.b64decode(match.group(2)))
print(dst)
