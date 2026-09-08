#!/usr/bin/env python3
import argparse
import base64
import hashlib
import json
import subprocess
import tempfile
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


def call(session, base_url, func_name, action, param=None, timeout=30):
    response = session.post(
        base_url + "/Action/call",
        json={"func_name": func_name, "action": action, "param": param or {}},
        timeout=timeout,
        verify=session.verify,
    )
    response.raise_for_status()
    payload = response.json()
    print(f"{func_name}.{action}:", jdump(payload)[:1800])
    return payload


def make_test_ca():
    tmpdir = tempfile.TemporaryDirectory(prefix="ikuai-openvpn-ca-")
    cert = Path(tmpdir.name) / "ca.crt"
    key = Path(tmpdir.name) / "ca.key"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-days",
            "1",
            "-subj",
            "/CN=codex-ovpn-ca-test",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    pem = cert.read_text()
    escaped = "@".join(line.replace(" ", "#") for line in pem.splitlines()) + "@"
    return tmpdir, escaped


def cleanup(session, base_url, prefix):
    payload = call(
        session,
        base_url,
        "openvpn-client",
        "show",
        {"TYPE": "data", "ORDER_BY": "id", "ORDER": "desc", "limit": "0,50"},
    )
    ids = []
    for row in (payload.get("Data") or {}).get("data") or []:
        if str(row.get("name", "")).startswith(prefix):
            ids.append(str(row.get("id")))
    ids = sorted(set(item for item in ids if item and item != "None"))
    if ids:
        result = call(session, base_url, "openvpn-client", "del", {"id": ",".join(ids)})
        if result.get("Result") != 30000:
            raise SystemExit("cleanup failed")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--insecure", action="store_true")
    args = parser.parse_args()

    if args.insecure:
        requests.packages.urllib3.disable_warnings()

    session = requests.Session()
    session.verify = not args.insecure
    login(session, args.base_url.rstrip("/"), args.password)

    prefix = "codex_ovpn_ca_test"
    cleanup(session, args.base_url.rstrip("/"), prefix)
    tmpdir, ca = make_test_ca()
    try:
        param = {
            "name": prefix + "_final",
            "remote_addr": "198.51.100.1",
            "remote_port": "1194",
            "interface": "auto",
            "proto": "udp",
            "dev_type": "tun",
            "enabled": "no",
            "comment": "codex_temp",
            "method": "0",
            "username": "u",
            "password": "p",
            "cipher": "",
            "comp_lzo": "",
            "tun_mtu": "1500",
            "redirect_gateway": "0",
            "accept_push_route": "1",
            "route": "",
            "extra_config": "",
            "timing_rst_switch": "0",
            "timing_rst_week": "",
            "timing_rst_time": "",
            "check_link_mode": "0",
            "check_link_host": "",
            "ca": ca,
            "cert": "",
            "key": "",
            "tls_auth": "",
        }
        result = call(session, args.base_url.rstrip("/"), "openvpn-client", "add", param)
        if result.get("Result") != 30000:
            raise SystemExit("openvpn-client.add failed")

        payload = call(
            session,
            args.base_url.rstrip("/"),
            "openvpn-client",
            "show",
            {"TYPE": "data", "ORDER_BY": "id", "ORDER": "desc", "limit": "0,50"},
        )
        found = False
        for row in (payload.get("Data") or {}).get("data") or []:
            if row.get("name") == prefix + "_final":
                found = True
                if not row.get("ca"):
                    raise SystemExit("created row has empty ca")
        if not found:
            raise SystemExit("created openvpn test row not found")
    finally:
        cleanup(session, args.base_url.rstrip("/"), prefix)
        tmpdir.cleanup()

    print("OPENVPN_CA_WRITE_VALIDATION_OK")


if __name__ == "__main__":
    main()
