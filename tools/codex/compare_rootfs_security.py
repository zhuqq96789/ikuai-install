#!/usr/bin/env python3
"""Compare filesystem contents without executing any firmware code."""
import difflib
import hashlib
import json
import lzma
import struct
from pathlib import Path, PurePosixPath

from ext4_extract_ro import Ext4Image, S_IFMT, S_IFREG, S_IFLNK


BASE = Path(__file__).resolve().parent / "security-3.7.25"


def collect(version):
    folder = BASE / version
    image = folder / "rootfs.img"
    image.write_bytes(lzma.decompress((folder / "rootfs.xz").read_bytes()))
    fs = Ext4Image(image)
    records, contents = {}, {}
    for rel, meta in fs.walk():
        if PurePosixPath(rel).is_absolute() or ".." in PurePosixPath(rel).parts:
            raise ValueError(f"unsafe path: {rel!r}")
        raw = meta["raw"]
        entry = {"mode": oct(meta["mode"]), "size": meta["size"],
                 "uid": struct.unpack_from("<H", raw, 2)[0] | (struct.unpack_from("<H", raw, 120)[0] << 16),
                 "gid": struct.unpack_from("<H", raw, 24)[0] | (struct.unpack_from("<H", raw, 122)[0] << 16)}
        kind = meta["mode"] & S_IFMT
        if kind in (S_IFREG, S_IFLNK):
            data = fs.read_file(meta["ino"])
            assert len(data) == meta["size"], rel
            entry["sha256"] = hashlib.sha256(data).hexdigest()
            contents[rel] = data
            if kind == S_IFLNK:
                entry["link"] = data.decode("utf-8", "surrogateescape")
            else:
                target = folder / "files" / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
        records[rel] = entry
    (folder / "manifest.json").write_text(json.dumps(records, indent=2, sort_keys=True) + "\n")
    print(f"{version}: {len(records)} entries, {len(contents)} file/link payloads", flush=True)
    return records, contents


def main():
    old, old_data = collect("3.7.24")
    new, new_data = collect("3.7.25")
    changes, patches = [], []
    for rel in sorted(old.keys() | new.keys()):
        before, after = old.get(rel), new.get(rel)
        if before == after:
            continue
        kind = "added" if before is None else "removed" if after is None else "modified"
        change = {"path": rel, "change": kind, "before": before, "after": after}
        changes.append(change)
        a, b = old_data.get(rel, b""), new_data.get(rel, b"")
        for version, data, record in (("3.7.24", a, before), ("3.7.25", b, after)):
            if record and int(record["mode"], 8) & S_IFMT == S_IFREG:
                target = BASE / "changed-files" / version / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
        if a != b:
            try:
                ta, tb = a.decode("utf-8"), b.decode("utf-8")
                if "\x00" not in ta + tb:
                    patches.extend(difflib.unified_diff(ta.splitlines(True), tb.splitlines(True),
                                                       f"3.7.24/{rel}", f"3.7.25/{rel}"))
                    change["text_diff"] = True
            except UnicodeDecodeError:
                pass
        print(f"{kind:8} {rel}  {before['size'] if before else '-'} -> {after['size'] if after else '-'}", flush=True)
    (BASE / "changes.json").write_text(json.dumps(changes, indent=2) + "\n")
    (BASE / "text-changes.patch").write_text("".join(patches))
    print(f"Total changes: {len(changes)}", flush=True)


if __name__ == "__main__":
    main()
