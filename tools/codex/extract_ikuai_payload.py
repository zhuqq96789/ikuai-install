#!/usr/bin/env python3
import struct
import sys
from pathlib import Path


src = Path(sys.argv[1])
dst = Path(sys.argv[2])
data = src.read_bytes()
head_len = struct.unpack(">I", data[:4])[0]
dst.write_bytes(data[4 + head_len :])
print(dst)
