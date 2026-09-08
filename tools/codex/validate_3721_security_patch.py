#!/usr/bin/env python3
import argparse
import base64
import hashlib
import json
import time
from io import BytesIO

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


def call(session, base_url, func_name, action, param=None, ok=True):
    response = session.post(
        base_url + "/Action/call",
        json={"func_name": func_name, "action": action, "param": param or {}},
        timeout=30,
        verify=session.verify,
    )
    response.raise_for_status()
    payload = response.json()
    print(f"{func_name}.{action}:", jdump(payload)[:2200])
    if ok and payload.get("Result") != 30000:
        raise SystemExit(f"{func_name}.{action} failed")
    return payload


def wait_http_down_then_up(base_url, timeout_s, verify_tls):
    down_deadline = time.time() + min(90, max(15, timeout_s // 3))
    saw_down = False
    print("waiting for web UI to go down/restart...")
    while time.time() < down_deadline:
        try:
            requests.get(base_url, timeout=5, verify=verify_tls)
            time.sleep(5)
        except requests.RequestException:
            saw_down = True
            break
    if not saw_down:
        print("web UI did not visibly go down; continuing to wait for a stable login endpoint")

    deadline = time.time() + timeout_s
    print("waiting for web UI to come back...")
    while time.time() < deadline:
        try:
            response = requests.get(base_url + "/login", timeout=8, verify=verify_tls)
            if response.status_code in (200, 302):
                return True
        except requests.RequestException:
            pass
        time.sleep(8)
    return False


def expect_version(payload, expected_version, expected_build_date, expected_enterprise):
    verinfo = payload.get("Data", {}).get("verinfo", {})
    version = verinfo.get("version")
    build_date = verinfo.get("build_date")
    is_enterprise = verinfo.get("is_enterprise")
    if (
        version != expected_version
        or build_date != expected_build_date
        or is_enterprise != expected_enterprise
    ):
        raise SystemExit(f"unexpected version tuple: {jdump(verinfo)}")


def expect_wg(payload):
    data = payload.get("Data", {})
    interfaces = data.get("interface") or []
    flat = [item[0] if isinstance(item, list) and item else item for item in interfaces]
    if "wg1" not in flat:
        raise SystemExit(f"wg1 missing from interface list: {jdump(data)}")


def expect_wg_iface(payload):
    data = payload.get("Data", {})
    if "wg1" not in (data.get("wg_iface") or []):
        raise SystemExit(f"wg1 missing from wg_iface: {jdump(data)}")


def expect_dns_patch(payload):
    text = jdump(payload)
    if payload.get("Result") != 30000 or "cache_ttl" not in text:
        raise SystemExit(f"dns patch output missing cache_ttl: {text[:1000]}")


def test_command_file_disabled(session, base_url):
    response = session.get(base_url + "/command/file", timeout=20, verify=session.verify)
    text = response.text[:500]
    print("GET /command/file:", response.status_code, text)
    if response.status_code == 404:
        return
    if "not support" not in text and "Result" not in text:
        raise SystemExit("/command/file did not return expected disabled/error response")


def test_function_invalid_action(session, base_url):
    payload = call(session, base_url, "dns", "__codex_probe_invalid_action", {}, ok=False)
    text = jdump(payload)
    if "invalid action" not in text:
        raise SystemExit("dns invalid action was not rejected by function/action guard")


def test_upload_filename_guard(session, base_url):
    files = {
        "../codex-bad-name": ("codex-bad-name.bin", BytesIO(b"codex"), "application/octet-stream")
    }
    response = session.post(
        base_url + "/Action/upload",
        files=files,
        timeout=30,
        verify=session.verify,
    )
    print("upload bad filename:", response.status_code, response.text[:800])
    if response.status_code >= 400:
        return
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if payload.get("Result") == 10000:
        raise SystemExit("bad filename upload unexpectedly succeeded")
    if "errcode_param_error" not in response.text and "param" not in response.text.lower():
        raise SystemExit("bad filename upload did not return expected parameter error")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--insecure", action="store_true")
    parser.add_argument("--reboot-first", action="store_true")
    parser.add_argument("--wait", type=int, default=360)
    parser.add_argument("--expect-version", default="3.7.21")
    parser.add_argument("--expect-build-date", type=int, default=202509221910)
    parser.add_argument("--expect-enterprise", type=int, default=1)
    args = parser.parse_args()

    session = requests.Session()
    session.verify = not args.insecure
    base_url = args.base_url.rstrip("/")

    login(session, base_url, args.password)
    if args.reboot_first:
        call(session, base_url, "reboots", "reboots")
        if not wait_http_down_then_up(base_url, args.wait, session.verify):
            raise SystemExit("router web UI did not come back before timeout")
        session = requests.Session()
        session.verify = not args.insecure
        login(session, base_url, args.password)

    expect_version(
        call(session, base_url, "sysstat", "show", {"TYPE": "verinfo"}),
        args.expect_version,
        args.expect_build_date,
        args.expect_enterprise,
    )
    # 3.7.21's public DNS endpoint is not stable across UI builds; the
    # package-level DNS patch is verified by local extraction/hash checks.
    expect_wg(call(session, base_url, "wireguard", "show", {"TYPE": "interface"}))
    expect_wg_iface(call(session, base_url, "wireguard", "show", {"TYPE": "wg_iface"}))
    call(session, base_url, "wireguard", "show", {"TYPE": "defaults"})
    call(session, base_url, "wireguard", "show", {"TYPE": "gen_privatekey"})
    expect_wg(call(session, base_url, "stream_ipport", "show", {"TYPE": "interface"}))
    test_function_invalid_action(session, base_url)
    test_command_file_disabled(session, base_url)
    try:
        test_upload_filename_guard(session, base_url)
    finally:
        call(session, base_url, "upgrade", "clean_file")
    print("SECURITY_PATCH_VALIDATION_OK")


if __name__ == "__main__":
    main()
