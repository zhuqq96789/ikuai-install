#!/usr/bin/env python3
import gzip
import hashlib
import json
import struct
from pathlib import Path

from ext_read import ExtImage
from ext4_extract_ro import Ext4Image, S_IFMT, S_IFREG

BASE = Path(__file__).resolve().parent / "security-3.7.25"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    result = {"independent_extraction": {}, "binary_changes": [], "unchanged_focus": {}}
    for version in ("3.7.24", "3.7.25"):
        image = BASE / version / "rootfs.img"
        reader, other = Ext4Image(image), ExtImage(image)
        count = 0
        for rel, meta in reader.walk():
            if meta["mode"] & S_IFMT == S_IFREG:
                assert reader.read_file(meta["ino"]) == other.read_inode_data(meta["ino"]), rel
                count += 1
        result["independent_extraction"][version] = {"regular_files_checked": count, "status": "PASS"}
    manifests = [json.loads((BASE / v / "manifest.json").read_text()) for v in ("3.7.24", "3.7.25")]
    changes = json.loads((BASE / "changes.json").read_text())
    for c in changes:
        if c["change"] != "modified" or c.get("text_diff") or not c["before"].get("sha256"):
            continue
        rel = c["path"]
        a, b = [(BASE / v / "files" / rel).read_bytes() for v in ("3.7.24", "3.7.25")]
        item = {"path": rel, "sizes": [len(a), len(b)]}
        if a.startswith(b"\x1f\x8b") and b.startswith(b"\x1f\x8b"):
            aa, bb = gzip.decompress(a), gzip.decompress(b)
            item.update({"decompressed_equal": aa == bb, "decompressed_sha256": [sha(aa), sha(bb)]})
        elif a.startswith(b"\x7fELF") and len(a) == len(b):
            offsets = [i for i, (x, y) in enumerate(zip(a, b)) if x != y]
            item["different_byte_count"] = len(offsets)
            spans = []
            for off in offsets:
                if spans and off - spans[-1][1] < 24:
                    spans[-1][1] = off
                else:
                    spans.append([off, off])
            item["spans"] = []
            item["span_count"] = len(spans)
            for start, end in spans[:8]:
                lo, hi = max(0, start - 35), min(len(a), start + 100, end + 36)
                item["spans"].append({"first_offset": start, "last_offset": end,
                                      "old_context": a[lo:hi].decode("ascii", "backslashreplace"),
                                      "new_context": b[lo:hi].decode("ascii", "backslashreplace")})
        result["binary_changes"].append(item)
    focus = ["usr/sbin/ikdnsd", "usr/ikuai/script/dns.sh", "usr/ikuai/script/dns_replace.sh",
             "usr/ikuai/script/remote_control.sh", "usr/ikuai/script/wireguard.sh",
             "usr/openresty/lua/webman/ikrest.lua", "usr/openresty/lua/lib/webman.lua",
             "usr/ikuai/script/upgrade.sh", "usr/ikuai/script/sec/download.lua"]
    for rel in focus:
        a, b = [m.get(rel) for m in manifests]
        result["unchanged_focus"][rel] = {"present_both": a is not None and b is not None,
                                           "identical": a is not None and a == b,
                                           "sha256": a.get("sha256") if a else None}
    (BASE / "artifact-validation.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"independent_extraction": result["independent_extraction"],
                      "binary_changes": [{k: v for k, v in item.items() if k != "spans"}
                                         for item in result["binary_changes"]],
                      "unchanged_focus": result["unchanged_focus"]}, indent=2))


if __name__ == "__main__":
    main()
