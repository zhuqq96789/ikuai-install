#!/usr/bin/env python3
import argparse
import base64
import gzip
import hashlib
import json
from pathlib import Path

import requests


def jdump(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def login(session, base_url, password):
    response = session.post(
        base_url + "/Action/login",
        json={
            "username": "admin",
            "passwd": hashlib.md5(password.encode()).hexdigest(),
            "pass": base64.b64encode(password.encode()).decode(),
            "remember_password": "",
        },
        timeout=20,
        verify=session.verify,
    )
    response.raise_for_status()
    payload = response.json()
    print("login:", jdump(payload))
    if payload.get("Result") != 10000:
        raise SystemExit("login failed")


def call(session, base_url, func_name, action, param=None, ok=True, timeout=30):
    response = session.post(
        base_url + "/Action/call",
        json={"func_name": func_name, "action": action, "param": param or {}},
        timeout=timeout,
        verify=session.verify,
    )
    response.raise_for_status()
    payload = response.json()
    print(f"{func_name}.{action}:", jdump(payload)[:2400])
    if ok and payload.get("Result") != 30000:
        raise SystemExit(f"{func_name}.{action} failed")
    return payload


def ensure_wg_interfaces(payload, label):
    data = payload.get("Data", {})
    interfaces = data.get("interface") or []
    flat = [item[0] if isinstance(item, list) and item else item for item in interfaces]
    if "wg1" not in flat:
        raise SystemExit(f"wg1 missing from {label}: {jdump(data)}")


def validate_china_iplib(payload):
    data = payload.get("Data", {})
    china = data.get("china_iplib")
    if not isinstance(china, dict):
        raise SystemExit(f"china_iplib payload missing object: {jdump(data)}")
    required = {"enable", "group_name", "china_url", "last_update", "count"}
    missing = sorted(required - set(china))
    if missing:
        raise SystemExit(f"china_iplib missing keys: {missing}; payload={jdump(china)}")
    if not china.get("group_name"):
        raise SystemExit(f"china_iplib group_name empty: {jdump(china)}")
    if not china.get("china_url"):
        raise SystemExit(f"china_iplib china_url empty: {jdump(china)}")
    print("china_iplib feature ok:", jdump(china))


def read_asset(path):
    raw = Path(path).read_bytes()
    if path.endswith(".gz"):
        return gzip.decompress(raw).decode("utf-8", "ignore")
    return raw.decode("utf-8", "ignore")


def validate_static_assets(asset_paths):
    if not asset_paths:
        return
    combined = "\n".join(read_asset(path) for path in asset_paths)
    checks = {
        "wireguard route": "wireguard-client",
        "wireguard import action": "IMPORT_EXTEND",
        "wireguard export action": "EXPORT_EXTEND",
        "wireguard qr action": "qrcode",
        "china_iplib UI/API token": "china_iplib",
        "china_iplib update action": "china_iplib_update",
    }
    for label, needle in checks.items():
        if needle not in combined:
            raise SystemExit(f"static asset check failed: {label} missing {needle!r}")
    print("static asset feature tokens ok:", ",".join(checks))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--insecure", action="store_true")
    parser.add_argument("--asset", action="append", default=[])
    args = parser.parse_args()

    validate_static_assets(args.asset)

    base_url = args.base_url.rstrip("/")
    session = requests.Session()
    session.verify = not args.insecure
    login(session, base_url, args.password)

    ensure_wg_interfaces(
        call(session, base_url, "wireguard", "show", {"TYPE": "interface"}),
        "wireguard.show interface",
    )
    wg_iface = call(session, base_url, "wireguard", "show", {"TYPE": "wg_iface"})
    if "wg1" not in (wg_iface.get("Data", {}).get("wg_iface") or []):
        raise SystemExit(f"wg1 missing from wireguard.show wg_iface: {jdump(wg_iface)}")
    call(session, base_url, "wireguard", "show", {"TYPE": "defaults"})
    call(session, base_url, "wireguard", "show", {"TYPE": "gen_privatekey"})
    ensure_wg_interfaces(
        call(session, base_url, "stream_ipport", "show", {"TYPE": "interface"}),
        "stream_ipport.show interface",
    )
    validate_china_iplib(call(session, base_url, "ipgroup", "show", {"TYPE": "china_iplib"}))
    print("WG_IPGROUP_FEATURE_VALIDATION_OK")


if __name__ == "__main__":
    main()
