#!/usr/bin/env python3
import hashlib
import json
import shutil
import subprocess
from pathlib import Path


BASE21 = Path("work/rootfs-3.7.21-security-patched-tree")
SEC = Path("work/security-3.7.25")
OLD = SEC / "changed-files/3.7.24"
NEW = SEC / "changed-files/3.7.25"
OUT = Path("work/rootfs-3.7.21-security-3725-patched-tree")
REPORT = SEC / "merge-into-3721.json"

# These are not security-script patches or are known to collide with the
# existing 3.7.21 custom feature set. Keep the current 3.7.21 versions unless
# a later manual pass explicitly extracts a smaller change.
SKIP_PATHS = {
    "bin/busybox",
    "etc/defaults/config_db.conf",
    "etc/defaults/libproto.gz",
    "etc/release",
    "usr/bin/ik_audit_client",
    "usr/lib/libdtalkd.so",
    "usr/lib/libreadline.so.7.0",
    "usr/lib/lua/lsqlite3.so",
    "usr/sbin/cre",
    "usr/sbin/ik_http_lua",
    "usr/sbin/ik_rc_client",
    "usr/sbin/miniupnpd",
    "usr/sbin/pmd",
    "usr/share/usb.ids.gz",
    # Changes the console authorization model; keep it separate for decision.
    "etc/setup/rc.console",
    "etc/ssl/default",
    "etc/ssl/default/console_ssh_allowlist.enc",
    "etc/ssl/default/console_ssh_allowlist.sig",
    "etc/ssl/default/device_auth.pem",
    # Submit3/host fallback is not required for the DNS/config hardening group.
    "etc/get_hosts/ik_hosts_v4_cn.json",
    "etc/get_hosts/ik_hosts_v4_en.json",
    "etc/get_hosts/ik_hosts_v4_sg.json",
    "usr/ikuai/submit",
    "usr/ikuai/submit/submit3",
    "usr/ikuai/script/utils/submit.lua",
    "usr/ikuai/script/utils/update_hosts.sh",
}

# Firmware-specific risk noted in the audit: defer pending live PPPoE testing.
SKIP_PATHS.add("usr/ikuai/script/pppoe_server.sh")


def sha256(path: Path):
    if not path.exists() or not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def is_text(path: Path) -> bool:
    if not path.exists() or not path.is_file():
        return False
    data = path.read_bytes()
    if b"\0" in data:
        return False
    try:
        data.decode("utf-8")
        return True
    except UnicodeDecodeError:
        try:
            data.decode("latin-1")
            return True
        except UnicodeDecodeError:
            return False


def copy_preserve(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def merge_text(rel: str, current: Path, old: Path, new: Path, dest: Path) -> dict:
    proc = subprocess.run(
        ["git", "merge-file", "-p", str(current), str(old), str(new)],
        capture_output=True,
        text=True,
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(proc.stdout)
    shutil.copymode(current, dest)
    return {
        "path": rel,
        "action": "merge-file",
        "status": "merged" if proc.returncode == 0 else "conflict",
        "exit_code": proc.returncode,
        "stderr": proc.stderr,
    }


def main() -> None:
    if OUT.exists():
        raise SystemExit(f"refusing to overwrite existing tree: {OUT}")
    shutil.copytree(BASE21, OUT, symlinks=True)

    changes = json.loads((SEC / "changes.json").read_text())
    report = []

    for change in changes:
        rel = change["path"]
        current = BASE21 / rel
        old = OLD / rel
        new = NEW / rel
        dest = OUT / rel

        if rel in SKIP_PATHS:
            report.append({"path": rel, "action": "skip", "reason": "deferred or feature-conflict"})
            continue

        if change["change"] == "added":
            if new.is_dir():
                dest.mkdir(parents=True, exist_ok=True)
                report.append({"path": rel, "action": "mkdir"})
            elif new.is_file():
                copy_preserve(new, dest)
                report.append({"path": rel, "action": "copy-added"})
            else:
                report.append({"path": rel, "action": "skip", "reason": "added path not regular file/dir"})
            continue

        if change["change"] != "modified":
            report.append({"path": rel, "action": "skip", "reason": f"unsupported change {change['change']}"})
            continue

        if not current.exists():
            report.append({"path": rel, "action": "skip", "reason": "missing in 3.7.21 custom tree"})
            continue

        if sha256(current) == sha256(old):
            copy_preserve(new, dest)
            report.append({"path": rel, "action": "copy-clean", "status": "same-as-3.7.24"})
            continue

        if is_text(current) and is_text(old) and is_text(new):
            report.append(merge_text(rel, current, old, new, dest))
        else:
            report.append({"path": rel, "action": "skip", "reason": "binary/custom"})

    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(OUT)
    print(REPORT)
    counts = {}
    for item in report:
        key = item.get("status") or item.get("action")
        counts[key] = counts.get(key, 0) + 1
    print(json.dumps(counts, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
