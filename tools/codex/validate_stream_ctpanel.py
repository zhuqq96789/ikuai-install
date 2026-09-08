#!/usr/bin/env python3
import argparse
import base64
import hashlib
import json
import time

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
    try:
        payload = response.json()
    except Exception:
        print(f"{func_name}.{action} raw:", response.text[:2600])
        raise
    print(f"{func_name}.{action}:", jdump(payload)[:2200])
    if ok and payload.get("Result") != 30000:
        raise SystemExit(f"{func_name}.{action} failed")
    return payload


def expect_wg_stream_interface(payload):
    interfaces = payload.get("Data", {}).get("interface") or []
    flat = [item[0] if isinstance(item, list) and item else item for item in interfaces]
    if "wg1" not in flat:
        raise SystemExit(f"wg1 missing from stream_ipport interface list: {jdump(flat)}")


def validate_temp_stream_rule(session, base_url):
    marker = f"codex-wg1-disabled-probe-{int(time.time())}"
    rule_id = None
    try:
        add = call(
            session,
            base_url,
            "stream_ipport",
            "add",
            {
                "enabled": "no",
                "comment": marker,
                "type": 0,
                "nexthop": "",
                "interface": "wg1",
                "mode": 0,
                "iface_band": 0,
                "src_addr": "",
                "dst_addr": "",
                "protocol": "any",
                "src_port": "",
                "dst_port": "",
                "week": "1234567",
                "time": "00:00-23:59",
            },
        )
        rule_id = str(add.get("RowId") or add.get("Data") or add.get("ErrMsg") or "").strip()
        if not rule_id.isdigit():
            raise SystemExit(f"cannot parse stream_ipport add id: {jdump(add)}")
        data = call(
            session,
            base_url,
            "stream_ipport",
            "show",
            {"TYPE": "data", "ORDER_BY": "id", "ORDER": "desc", "limit": "0,20"},
        )
        text = jdump(data)
        if marker not in text or '"interface":"wg1"' not in text:
            raise SystemExit("temporary wg1 stream rule was not visible after add")
        print(f"stream_ipport temporary wg1 rule ok: id={rule_id}")
    finally:
        if rule_id and rule_id.isdigit():
            call(session, base_url, "stream_ipport", "del", {"id": rule_id}, ok=False)
            data = call(session, base_url, "stream_ipport", "show", {"TYPE": "data"})
            if marker in jdump(data):
                raise SystemExit("temporary stream_ipport rule cleanup failed")
            print(f"stream_ipport temporary rule cleaned: id={rule_id}")


def cleanup_old_stream_probes(session, base_url):
    data = call(session, base_url, "stream_ipport", "show", {"TYPE": "data"})
    rows = data.get("Data", {}).get("data") or []
    old_ids = [
        str(row.get("id"))
        for row in rows
        if str(row.get("comment", "")).startswith("codex-wg1-disabled-probe-")
    ]
    if old_ids:
        call(session, base_url, "stream_ipport", "del", {"id": ",".join(old_ids)}, ok=False)
        print("stream_ipport old probe rules cleaned:", ",".join(old_ids))


def validate_ctpanel(session, base_url):
    data = call(session, base_url, "plugin_ctpanel", "show", {"TYPE": "data"})
    panel = data.get("Data", {})
    rcstatus = panel.get("rcstatus")
    if rcstatus not in ("on", "off"):
        raise SystemExit(f"unexpected ctpanel rcstatus: {jdump(panel)}")
    original_disable = rcstatus == "off"
    try:
        call(session, base_url, "plugin_ctpanel", "set_rc_trunoff", {"status": True})
        disabled = call(session, base_url, "plugin_ctpanel", "show", {"TYPE": "data"})
        disabled_status = disabled.get("Data", {}).get("rcstatus")
        if disabled_status != "off":
            raise SystemExit(f"ctpanel disable switch did not set rcstatus=off: {disabled_status}")
    finally:
        call(session, base_url, "plugin_ctpanel", "set_rc_trunoff", {"status": original_disable})
    restored = call(session, base_url, "plugin_ctpanel", "show", {"TYPE": "data"})
    restored_status = restored.get("Data", {}).get("rcstatus")
    expected = "off" if original_disable else "on"
    if restored_status != expected:
        raise SystemExit(f"ctpanel restore failed: expected={expected} actual={restored_status}")
    print(f"ctpanel cloud remote switch ok: restored rcstatus={restored_status}")
    return rcstatus


def max_route_collect_log_timestamp(payload):
    rows = payload.get("Data", {}).get("data") or []
    timestamps = [
        int(row.get("timestamp") or 0)
        for row in rows
        if "route_collect" in str(row.get("content", ""))
        or "云平台远控服务重新启动" in str(row.get("content", ""))
    ]
    return max(timestamps) if timestamps else 0


def validate_route_collect_log_suppressed(session, base_url, wait_s):
    before = call(
        session,
        base_url,
        "syslog-sysevent",
        "show",
        {"TYPE": "data", "ORDER_BY": "timestamp", "ORDER": "desc", "limit": "0,50"},
    )
    before_ts = max_route_collect_log_timestamp(before)
    print(f"route_collect log max timestamp before wait: {before_ts}")
    time.sleep(wait_s)
    after = call(
        session,
        base_url,
        "syslog-sysevent",
        "show",
        {"TYPE": "data", "ORDER_BY": "timestamp", "ORDER": "desc", "limit": "0,50"},
    )
    after_ts = max_route_collect_log_timestamp(after)
    if after_ts > before_ts:
        raise SystemExit(
            f"route_collect cloud remote restart log still increases: before={before_ts} after={after_ts}"
        )
    print(f"route_collect log suppression ok after {wait_s}s: before={before_ts} after={after_ts}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--insecure", action="store_true")
    parser.add_argument("--log-wait", type=int, default=0)
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    session = requests.Session()
    session.verify = not args.insecure
    login(session, base_url, args.password)
    expect_wg_stream_interface(call(session, base_url, "stream_ipport", "show", {"TYPE": "interface"}))
    cleanup_old_stream_probes(session, base_url)
    validate_temp_stream_rule(session, base_url)
    validate_ctpanel(session, base_url)
    if args.log_wait > 0:
        validate_route_collect_log_suppressed(session, base_url, args.log_wait)
    print("STREAM_CTPANEL_VALIDATION_OK")


if __name__ == "__main__":
    main()
