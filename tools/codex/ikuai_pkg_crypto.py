#!/usr/bin/env python3
import argparse
import base64
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path


def evp_bytes_to_key_md5(password: bytes, salt: bytes, key_len: int, iv_len: int) -> tuple[bytes, bytes]:
    out = b""
    prev = b""
    while len(out) < key_len + iv_len:
        prev = hashlib.md5(prev + password + salt).digest()
        out += prev
    return out[:key_len], out[key_len : key_len + iv_len]


def openssl_crypt(data: bytes, password: bytes, *, salted: bool, key_len: int, decrypt: bool) -> bytes:
    if salted:
        if decrypt:
            if not data.startswith(b"Salted__") or len(data) < 16:
                raise ValueError("missing OpenSSL salted header")
            salt = data[8:16]
            body = data[16:]
        else:
            salt = os.urandom(8)
            body = data
    else:
        salt = b""
        body = data

    key, iv = evp_bytes_to_key_md5(password, salt, key_len, 16)
    cipher = f"aes-{key_len * 8}-cbc"
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "in.bin"
        dst = Path(td) / "out.bin"
        src.write_bytes(body)
        cmd = [
            "openssl",
            cipher,
            "-d" if decrypt else "-e",
            "-K",
            key.hex(),
            "-iv",
            iv.hex(),
            "-in",
            str(src),
            "-out",
            str(dst),
        ]
        subprocess.run(cmd, check=True, stderr=subprocess.PIPE)
        result = dst.read_bytes()
    if salted and not decrypt:
        return b"Salted__" + salt + result
    return result


def decrypt_db(path: Path) -> list[dict]:
    raw_text = path.read_text().strip()
    data = base64.b64decode(raw_text)
    plain = openssl_crypt(data, b"ikupdat-d~#-", salted=False, key_len=32, decrypt=True)
    return json.loads(plain.decode())


def unpack_pkg(pkg_path: Path, secret_key: str, out_dir: Path) -> None:
    data = pkg_path.read_bytes()
    plain = openssl_crypt(data, secret_key.encode(), salted=True, key_len=16, decrypt=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_path = out_dir / f"{pkg_path.stem}.bin"
    raw_path.write_bytes(plain)
    marker = b"\x0a\x1f\x8b\x08\x00"
    idx = plain.find(marker)
    if idx >= 0:
        (out_dir / "install.sh").write_bytes(plain[:idx])
        gz = plain[idx + 1 :]
        gz_path = out_dir / "payload.gz"
        gz_path.write_bytes(gz)
        tar_path = out_dir / "payload.tar"
        subprocess.run(["gzip", "-dc", str(gz_path)], check=True, stdout=tar_path.open("wb"))
        extract_dir = out_dir / "files"
        extract_dir.mkdir(exist_ok=True)
        subprocess.run(["tar", "-xf", str(tar_path), "-C", str(extract_dir)], check=True)


def build_wrapper(package_name: str) -> str:
    template = """#!/bin/bash
HEAD_LEN={head_len}
PACKAGE_NAME={package_name}
INSTALL_ROOT_DIR=/tmp/ikpkg
export INSTALL_DIR=${{INSTALL_ROOT_DIR}}/${{PACKAGE_NAME}}
ACTION=${{1:-install}}

[ ! -f ${{INSTALL_DIR}}/uninstall.sh ] && HAS_OLD_UNINSTALL=no
if [ -f ${{INSTALL_DIR}}/uninstall.sh ] ;then
    if [ "$ACTION" = "uninstall" ]; then
        bash ${{INSTALL_DIR}}/uninstall.sh uninstall
    else
        bash ${{INSTALL_DIR}}/uninstall.sh
    fi
fi
ret="$?"
rm -rf ${{INSTALL_DIR}}
if [ "$ACTION" = "install" ]; then
    mkdir -p ${{INSTALL_DIR}}
    tail -n +$HEAD_LEN $0 | tar zx -C ${{INSTALL_DIR}}/
    [ "x${{HAS_OLD_UNINSTALL}}" == "xno" -a -f ${{INSTALL_DIR}}/uninstall.sh ] && bash ${{INSTALL_DIR}}/uninstall.sh "$@"
    [ ! -f ${{INSTALL_DIR}}/install.sh ] && exit 0
    bash ${{INSTALL_DIR}}/install.sh "$@"
    ret="$?"
    [ "$ret" == 100 ] && rm -rf ${{INSTALL_DIR}}
fi
exit $ret"""
    wrapper = template.format(head_len=0, package_name=package_name)
    head_len = wrapper.count("\n") + 2
    return template.format(head_len=head_len, package_name=package_name)


def make_payload_targz(files_dir: Path) -> bytes:
    with tempfile.TemporaryDirectory() as td:
        tar_path = Path(td) / "payload.tar"
        gz_path = Path(td) / "payload.gz"
        with tarfile.open(tar_path, "w") as tar:
            for path in sorted(files_dir.rglob("*")):
                rel = path.relative_to(files_dir)
                info = tar.gettarinfo(str(path), arcname=str(rel))
                info.uid = 0
                info.gid = 0
                info.uname = ""
                info.gname = ""
                if path.is_file():
                    with path.open("rb") as fh:
                        tar.addfile(info, fh)
                else:
                    tar.addfile(info)
        subprocess.run(["gzip", "-n", "-9", "-c", str(tar_path)], check=True, stdout=gz_path.open("wb"))
        return gz_path.read_bytes()


def pack_pkg(name: str, files_dir: Path, secret_key: str, output: Path) -> bytes:
    raw = build_wrapper(name).encode() + b"\n" + make_payload_targz(files_dir)
    encrypted = openssl_crypt(raw, secret_key.encode(), salted=True, key_len=16, decrypt=False)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(encrypted)
    return encrypted


def encrypt_db(packages: list[dict], output: Path) -> bytes:
    plain = json.dumps(packages, ensure_ascii=False, separators=(",", ":")).encode()
    encrypted = openssl_crypt(plain, b"ikupdat-d~#-", salted=False, key_len=32, decrypt=False)
    encoded = base64.b64encode(encrypted)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(encoded)
    return encoded


def cmd_unpack(args: argparse.Namespace) -> None:
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)
    db_path = input_dir / "db" / ".__DB.3.x86_64"
    if not db_path.exists() and (db_path.with_suffix(db_path.suffix + ".b64")).exists():
        db_path = db_path.with_suffix(db_path.suffix + ".b64")
    packages = decrypt_db(db_path)
    (output_dir / "db.json").write_text(json.dumps(packages, ensure_ascii=False, indent=2))
    print(json.dumps(packages, ensure_ascii=False, indent=2))
    for pkg in packages:
        name = pkg.get("name")
        secret = pkg.get("secret_key")
        if not name or not secret:
            continue
        path = input_dir / f"{name}.bin.pkg"
        if not path.exists():
            print(f"missing {path}")
            continue
        try:
            unpack_pkg(path, secret, output_dir / name)
            print(f"unpacked {name}")
        except Exception as exc:
            print(f"failed {name}: {exc}")


def cmd_pack(args: argparse.Namespace) -> None:
    data = pack_pkg(args.name, Path(args.files_dir), args.secret_key, Path(args.output))
    print(f"output: {args.output}")
    print(f"size: {len(data)}")
    print(f"md5: {hashlib.md5(data).hexdigest()}")


def cmd_encrypt_db(args: argparse.Namespace) -> None:
    packages = json.loads(Path(args.input_json).read_text())
    data = encrypt_db(packages, Path(args.output))
    print(f"output: {args.output}")
    print(f"size: {len(data)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(required=True)
    p = sub.add_parser("unpack")
    p.add_argument("input_dir")
    p.add_argument("output_dir")
    p.set_defaults(func=cmd_unpack)
    p = sub.add_parser("pack")
    p.add_argument("--name", required=True)
    p.add_argument("--files-dir", required=True)
    p.add_argument("--secret-key", required=True)
    p.add_argument("--output", required=True)
    p.set_defaults(func=cmd_pack)
    p = sub.add_parser("encrypt-db")
    p.add_argument("--input-json", required=True)
    p.add_argument("--output", required=True)
    p.set_defaults(func=cmd_encrypt_db)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
