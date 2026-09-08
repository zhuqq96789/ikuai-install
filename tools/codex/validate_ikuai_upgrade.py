#!/usr/bin/env python3
import argparse
import base64
import hashlib
import json
import time
from pathlib import Path

import requests


def login(session: requests.Session, base_url: str, password: str, verify_tls: bool) -> None:
    response = session.post(
        base_url + "/Action/login",
        json={
            "username": "admin",
            "passwd": hashlib.md5(password.encode()).hexdigest(),
            "pass": base64.b64encode(password.encode()).decode(),
            "remember_password": "",
        },
        timeout=15,
        verify=verify_tls,
    )
    response.raise_for_status()
    print("login:", response.text[:300])


def call(session: requests.Session, base_url: str, func_name: str, action: str, param=None):
    response = session.post(
        base_url + "/Action/call",
        json={"func_name": func_name, "action": action, "param": param or {}},
        timeout=30,
        verify=session.verify,
    )
    response.raise_for_status()
    try:
        payload = response.json()
    except json.JSONDecodeError:
        payload = {"raw": response.text}
    print(f"{func_name}.{action}:", json.dumps(payload, ensure_ascii=False)[:2000])
    return payload


def call_until_success(
    session: requests.Session,
    base_url: str,
    func_name: str,
    action: str,
    param=None,
    timeout_s: int = 150,
):
    deadline = time.time() + timeout_s
    last_payload = None
    while time.time() < deadline:
        try:
            payload = call(session, base_url, func_name, action, param)
            last_payload = payload
            if payload.get("Result") == 30000:
                return payload
        except Exception as exc:
            print(f"{func_name}.{action} retryable failure: {exc}")
        time.sleep(5)
    raise SystemExit(
        f"{func_name}.{action} did not return Result=30000 within {timeout_s}s; "
        f"last={json.dumps(last_payload, ensure_ascii=False)[:1000]}"
    )


def wait_http(base_url: str, timeout_s: int, verify_tls: bool) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            requests.get(base_url, timeout=5, verify=verify_tls)
            return True
        except requests.RequestException:
            time.sleep(5)
    return False


def wait_http_down_then_up(base_url: str, timeout_s: int, verify_tls: bool) -> bool:
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate iKuai web upgrade package on a test router.")
    parser.add_argument("--base-url", required=True, help="Example: http://192.168.1.1")
    parser.add_argument("--password", required=True)
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--upgrade", action="store_true", help="Actually run upgrade.update_file")
    parser.add_argument(
        "--reboot-after-update",
        action="store_true",
        help="Call reboots.reboots after upgrade.update_file. The 3.7.21 UI does this manually for non-hd bootguide.",
    )
    parser.add_argument("--status-only", action="store_true", help="Only login and collect read-only status")
    parser.add_argument("--wait", type=int, default=240, help="Seconds to wait after upgrade")
    parser.add_argument("--upload-timeout", type=int, default=300, help="Seconds to allow for firmware upload")
    parser.add_argument("--insecure", action="store_true", help="Disable TLS certificate verification")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    package = args.package
    if not package.is_file():
        raise SystemExit(f"package not found: {package}")

    session = requests.Session()
    session.verify = not args.insecure
    login(session, base_url, args.password, session.verify)
    verinfo = call(session, base_url, "sysstat", "show", {"TYPE": "verinfo"})

    if args.status_only:
        for func_name, action, param in (
            ("sysstat", "show", {"TYPE": "data"}),
            ("upgrade", "show", {"TYPE": "fileinfo"}),
            ("wireguard", "show", {"TYPE": "data"}),
            ("stream_ipport", "show", {"TYPE": "data"}),
        ):
            try:
                call(session, base_url, func_name, action, param)
            except Exception as exc:
                print(f"{func_name}.{action} failed: {exc}")
        return

    call(session, base_url, "upgrade", "clean_file")

    upload_name = f"upgrade-{int(time.time())}.bin"
    with package.open("rb") as fh:
        response = session.post(
            base_url + "/Action/upload",
            files={upload_name: (upload_name, fh, "application/octet-stream")},
            timeout=args.upload_timeout,
            verify=session.verify,
        )
    response.raise_for_status()
    print("upload:", response.text[:1000])
    try:
        upload_payload = response.json()
    except json.JSONDecodeError as exc:
        raise SystemExit(f"upload did not return JSON: {response.text[:1000]}") from exc
    if upload_payload.get("Result") != 10000:
        raise SystemExit(f"upload failed: {json.dumps(upload_payload, ensure_ascii=False)[:1000]}")

    parse_payload = call(session, base_url, "upgrade", "parse_file", {"filename": upload_name})
    if parse_payload.get("Result") != 30000:
        raise SystemExit(f"parse_file failed: {json.dumps(parse_payload, ensure_ascii=False)[:1000]}")
    show_payload = call(session, base_url, "upgrade", "show", {"TYPE": "fileinfo"})
    if show_payload.get("Result") != 30000 or not show_payload.get("Data", {}).get("fileinfo"):
        raise SystemExit(f"upgrade.show did not return fileinfo: {json.dumps(show_payload, ensure_ascii=False)[:1000]}")

    if not args.upgrade:
        print("parse-only validation complete; pass --upgrade to perform runtime validation.")
        return

    update_payload = call(session, base_url, "upgrade", "update_file")
    if update_payload.get("Result") != 30000:
        raise SystemExit(f"update_file failed: {json.dumps(update_payload, ensure_ascii=False)[:1000]}")
    bootguide = (
        verinfo.get("Data", {})
        .get("verinfo", {})
        .get("bootguide", "")
    )
    if args.reboot_after_update or bootguide != "hd":
        print(f"triggering reboot after update_file; bootguide={bootguide!r}")
        call(session, base_url, "reboots", "reboots")
    print(f"waiting for router web UI for up to {args.wait}s...")
    if not wait_http_down_then_up(base_url, args.wait, session.verify):
        raise SystemExit("router web UI did not come back before timeout")

    session = requests.Session()
    session.verify = not args.insecure
    login(session, base_url, args.password, session.verify)
    call(session, base_url, "sysstat", "show", {"TYPE": "verinfo"})
    call_until_success(session, base_url, "wireguard", "show", {"TYPE": "data"})
    call_until_success(session, base_url, "wireguard", "show", {"TYPE": "defaults"})
    call_until_success(session, base_url, "wireguard", "show", {"TYPE": "interface"})
    call_until_success(session, base_url, "wireguard", "show", {"TYPE": "wg_iface"})
    call_until_success(session, base_url, "wireguard", "show", {"TYPE": "gen_privatekey"})
    call_until_success(session, base_url, "stream_ipport", "show", {"TYPE": "data"})
    call_until_success(session, base_url, "stream_ipport", "show", {"TYPE": "interface"})


if __name__ == "__main__":
    main()
