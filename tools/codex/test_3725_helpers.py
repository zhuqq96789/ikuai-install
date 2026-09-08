#!/usr/bin/env python3
"""Offline helper checks; no router, network, or firmware binaries are used."""
import json
import os
import sqlite3
import subprocess
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parent / "security-3.7.25"
FILES = Path(os.environ.get("FILES_ROOT", BASE / "3.7.25/files"))
BASH_BIN = Path(os.environ.get("BASH_BIN", BASE / "bash-5.2.37/bash"))
REPORT_OUT = Path(os.environ.get("REPORT_OUT", BASE / "helper-tests.json"))
checks = []


def bash(source, code, *args, env=None):
    return subprocess.run([str(BASH_BIN), "--noprofile", "--norc", "-c",
                           'source "$1"; shift\n' + code, "test", str(FILES / source), *args],
                          capture_output=True, text=True, timeout=10,
                          env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", **(env or {})})


def check(name, condition, detail=""):
    checks.append({"name": name, "status": "PASS" if condition else "FAIL", "detail": detail})
    assert condition, (name, detail)


def main():
    version = subprocess.run([str(BASH_BIN), "--version"], capture_output=True, text=True, timeout=5)
    check("Selected Bash exists", version.returncode == 0, version.stderr)

    for value, expected in [("abc%20def", "abc def"), ("a+b", "a+b"),
                            ("%E4%B8%AD%E6%96%87", "中文"), ("%27quoted%27", "'quoted'"),
                            ("$(printf UNEXPECTED)", "$(printf UNEXPECTED)"),
                            ("%ZZ", "%ZZ"), ("%41%42", "AB")]:
        p = bash("usr/ikuai/include/urlcode.sh", 'url_decode_noeval_raw "$1"', value)
        check("URL literal roundtrip " + repr(value), p.returncode == 0 and p.stdout == expected + "\n", p.stderr)
    p = bash("usr/ikuai/include/urlcode.sh", 'url_decode "$1"', "%27abc%22")
    check("URL legacy quote stripping", p.returncode == 0 and p.stdout == "abc\n", p.stderr)

    sql_source = "usr/ikuai/include/sqlite.sh"
    capture = '__sql_config_exec() { printf "%s" "$3"; }; __sql_errmsg() { :; }; '
    value = "O'Reilly; literal $(printf UNEXPECTED) and ]]"
    p = bash(sql_source, capture + 'name="$1"; num=7; sql_config_insert unused demo id:null name:str num:int', value)
    db = sqlite3.connect(":memory:")
    db.execute("create table demo(id integer primary key, name text, num integer)")
    db.executescript(p.stdout)
    check("SQL string escaping roundtrip", p.returncode == 0 and db.execute("select name,num from demo").fetchone() == (value, 7), p.stderr)
    for value in ("1+1", "1; SELECT 1", "7x", "$(printf UNEXPECTED)"):
        p = bash(sql_source, capture + 'num="$1"; sql_config_insert unused demo num:int', value)
        check("SQL rejects invalid integer " + repr(value), p.returncode != 0 and not p.stdout, p.stderr)
    for field in ("name:srt", "name:text", "bad-name:str"):
        p = bash(sql_source, capture + 'name=ok; sql_config_insert unused demo "$1"', field)
        check("SQL rejects invalid field/type " + field, p.returncode != 0 and not p.stdout, p.stderr)

    with tempfile.TemporaryDirectory(prefix="helper-tests-", dir=BASE) as tmp:
        route = Path(tmp)
        (route / "route.d").mkdir()
        code = r'''
ROUTE_RULE_DIR="$1"
iproute_add_static_route() { printf 'static4:%s\n' "$*" >> "$ROUTE_RULE_DIR/calls"; }
ip6route_add_static_route() { printf 'static6:%s\n' "$*" >> "$ROUTE_RULE_DIR/calls"; }
ip() { printf 'ip:%s\n' "$*" >> "$ROUTE_RULE_DIR/calls"; }
route_rule_insert static_rt static4 1 wg1 10.0.0.1 192.0.2.0/24 1 || exit 2
route_rule_insert static_rt static6 2 wg1 fe80::1 2001:db8::/64 1 || exit 2
route_rule_insert stream_ipport stream_default 3 10.0.0.1 100 || exit 2
cat "$ROUTE_RULE_DIR"/route.d/* > "$ROUTE_RULE_DIR/root"
route_rule_update ALL
'''
        p = bash("usr/ikuai/include/route_rule.sh", code, tmp)
        calls = (route / "calls").read_text()
        check("Typed route dispatch preserves wg1 argument", p.returncode == 0 and "static4:wg1 " in calls and "static6:wg1 " in calls and "ip:route add default via 10.0.0.1 table 100" in calls, calls)
        p = bash("usr/ikuai/include/route_rule.sh", 'ROUTE_RULE_DIR="$1"; route_rule_insert static_rt static4 1 "wg1|extra" x y z', tmp)
        check("Route rejects embedded field separator", p.returncode != 0)

    changes = json.loads((BASE / "changes.json").read_text())
    syntax = []
    for change in changes:
        rel = change["path"]
        pth = FILES / rel
        if not pth.is_file():
            continue
        first = pth.read_bytes().split(b"\n", 1)[0]
        if rel.endswith(".sh") or first.startswith(b"#!/bin/bash"):
            p = subprocess.run([str(BASH_BIN), "-n", str(pth)], capture_output=True, text=True)
            syntax.append({"path": rel, "exit_code": p.returncode, "stderr": p.stderr})
    check("Changed shell scripts parse", all(p["exit_code"] == 0 for p in syntax), f"{len(syntax)} scripts; host Bash syntax only")
    report = {"scope": "Offline Bash helper tests and SQLite in-memory validation; not router/VM validation",
              "files_root": str(FILES),
              "bash": {"path": str(BASH_BIN), "version": version.stdout.splitlines()[0] if version.stdout else ""},
              "checks": checks, "shell_syntax": syntax}
    REPORT_OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
