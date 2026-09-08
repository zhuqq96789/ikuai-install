#!/usr/bin/env python3
import base64
import os
import re
import shlex
import textwrap
from pathlib import Path


ROOT = Path("work/rootfs-3.7.21-security-3725-patched-tree")
BASE_DEVE = Path("work/deve-from-3.7.21.sh")
OUT = Path("work/deve-3.7.21-wg-security-3725-runtime.sh")
WEBFIX_DEVE_CANDIDATES = [
    Path(os.environ["WEBFIX_DEVE"]) if os.environ.get("WEBFIX_DEVE") else None,
    Path("work/deve-202509-docstable-developergrub-upgrade.sh"),
    Path("work/deve-webfix-base.sh"),
]
WEBFIX_DEVE = next((path for path in WEBFIX_DEVE_CANDIDATES if path and path.exists()), None)
BUILD = "202609090052"
DISPLAY_VERSION = "3.7.25"
DISPLAY_VERSION_NUM = "300070025"
DISPLAY_BUILD_DATE = BUILD
DISPLAY_VERSTRING = f"{DISPLAY_VERSION} x64 Enterprise Patch Build{DISPLAY_BUILD_DATE}"

FILES = [
    ("etc/ikcommon", "644"),
    ("etc/inform/host_event.sh", "644"),
    ("usr/ikuai/ac/patch/include/load_config.sh", "755"),
    ("usr/ikuai/ac/patch/include/urlcode.sh", "644"),
    ("usr/ikuai/iklua/string/check.lua", "755"),
    ("usr/ikuai/include/ac/batch_edit.sh", "755"),
    ("usr/ikuai/include/check_varl.sh", "644"),
    ("usr/ikuai/include/iproute.sh", "644"),
    ("usr/ikuai/include/json.sh", "644"),
    ("usr/ikuai/include/openvpn.sh", "644"),
    ("usr/ikuai/include/route_rule.sh", "644"),
    ("usr/ikuai/include/sqlite.sh", "644"),
    ("usr/ikuai/include/urlcode.sh", "644"),
    ("usr/ikuai/include/wifi/apcli_gx2600.sh", "644"),
    ("usr/ikuai/include/wifi/apcli_mac80211.sh", "644"),
    ("usr/ikuai/include/wifi/apcli_mediatek.sh", "644"),
    ("usr/ikuai/include/wifi/apcli_qcawifi.sh", "644"),
    ("usr/ikuai/include/wifi/mesh.sh", "644"),
    ("usr/ikuai/include/wifi/qcaextend.sh", "644"),
    ("usr/ikuai/script/ac_group.sh", "755"),
    ("usr/ikuai/script/ac_net_optimize.sh", "644"),
    ("usr/ikuai/script/ac_server.sh", "644"),
    ("usr/ikuai/script/acl.sh", "755"),
    ("usr/ikuai/script/audit_url_log.sh", "644"),
    ("usr/ikuai/script/dprotos.sh", "644"),
    ("usr/ikuai/script/dprotos_l7.sh", "644"),
    ("usr/ikuai/script/ik_event_imlog.sh", "644"),
    ("usr/ikuai/script/ik_netoptimize.sh", "644"),
    ("usr/ikuai/script/ipv6.sh", "755"),
    ("usr/ikuai/script/mac_app.sh", "644"),
    ("usr/ikuai/script/monitor_lanip.sh", "644"),
    ("usr/ikuai/script/openvpn-client.sh", "755"),
    ("usr/ikuai/script/rc", "755"),
    ("usr/ikuai/script/send_log.sh", "644"),
    ("usr/ikuai/script/static_rt.sh", "755"),
    ("usr/ikuai/script/stream_ipport.sh", "755"),
    ("usr/ikuai/script/url_black.sh", "644"),
    ("usr/ikuai/script/utils/ap_load.sh", "755"),
    ("usr/ikuai/script/utils/async.lua", "644"),
    ("usr/ikuai/script/utils/cloud_switch.lua", "644"),
    ("usr/ikuai/script/utils/convert_config_old.sh", "644"),
    ("usr/ikuai/script/utils/convert_config_old_mips.sh", "644"),
    ("usr/ikuai/script/utils/devdiscovery.lua", "644"),
    ("usr/ikuai/script/utils/ldapinfo_load.lua", "644"),
    ("usr/ikuai/script/utils/monitor_process.sh", "755"),
    ("usr/ikuai/script/wan.sh", "755"),
    ("usr/ikuai/script/webauth.sh", "755"),
    ("usr/sbin/iktimerd", "755"),
    ("usr/ikuai/script/dns.sh", "755"),
    ("etc/setup/rc.console", "755"),
    ("sbin/sysinit", "755"),
    ("usr/ikuai/script/upgrade.sh", "755"),
    ("usr/ikuai/script/register.sh", "755"),
    ("usr/openresty/lua/lib/webman.lua", "644"),
    ("usr/openresty/lua/webman/ikrest.lua", "644"),
    ("usr/openresty/lua/webauth/release.lua", "644"),
    ("usr/ikuai/script/utils/submit.lua", "644"),
    ("usr/ikuai/include/submit.sh", "644"),
    ("usr/ikuai/script/sec/download.lua", "644"),
]

WEBFIX_FILES = [
    "/usr/ikuai/www/static/js/33.8a72b3b5c6af5253b36b.js.gz",
    "/usr/ikuai/www/static/js/109.75bd28d124ed74439509.js.gz",
    "/usr/ikuai/www/static/js/109.6cfe9e1d091a98eb1309.js.gz",
    "/usr/ikuai/www/static/js/136.8b4653f20b0396291faa.js.gz",
    "/usr/ikuai/www/static/js/136.229352b576fb36f36e62.js.gz",
    "/usr/ikuai/www/static/js/manifest.bbf944b389a3fcce7f6c.js.gz",
    "/usr/ikuai/www/static/js/manifest.214406a8f683cc509f28.js.gz",
    "/usr/ikuai/www/static/js/109.75bd28d124ed74439509.js",
    "/usr/ikuai/www/static/js/136.229352b576fb36f36e62.js",
    "/usr/ikuai/www/static/js/manifest.214406a8f683cc509f28.js",
    "/usr/ikuai/www/static/js/manifest.bbf944b389a3fcce7f6c.js",
    "/usr/ikuai/www/static/js/manifest.98c546fcac345deebb63.js",
    "/usr/ikuai/www/index.html",
]


def source_file_bytes(rel: str) -> bytes:
    data = (ROOT / rel).read_bytes()
    if rel == "usr/ikuai/script/openvpn-client.sh" and b"__ensure_openvpn_client_schema" not in data:
        text = data.decode("utf-8")
        text = text.replace(
            'CLIENT_INIT_DONE="/tmp/iktmp/ovpn_init_done"\n',
            '''CLIENT_INIT_DONE="/tmp/iktmp/ovpn_init_done"

__ensure_openvpn_client_schema()
{
\tsqlite3 $IK_DB_CONFIG "alter table openvpn_client add column check_link_mode integer default 0;" >/dev/null 2>&1 || true
\tsqlite3 $IK_DB_CONFIG "alter table openvpn_client add column check_link_host text default '';" >/dev/null 2>&1 || true
}

''',
            1,
        )
        for name in ("boot", "init", "edit", "add", "IMPORT", "show"):
            text = text.replace(f"{name}()\n{{\n", f"{name}()\n{{\n\t__ensure_openvpn_client_schema\n", 1)
        text = text.replace("show() {\n", "show() {\n\t__ensure_openvpn_client_schema\n", 1)
        return text.encode("utf-8")
    return data


def b64_file(rel: str) -> str:
    data = base64.b64encode(source_file_bytes(rel)).decode()
    return "\n".join(textwrap.wrap(data, 76))


def shell_write_block(rel: str, mode: str) -> str:
    tag = "IKUAI_SECURITY_PATCH_" + rel.replace("/", "_").replace(".", "_").replace("-", "_")
    dest = "/" + rel
    encoded = b64_file(rel)
    return f"""write_b64_file {shlex.quote(dest)} {shlex.quote(mode)} <<'{tag}'
{encoded}
{tag}
"""


def extract_webfix_blocks() -> str:
    if WEBFIX_DEVE is None:
        raise SystemExit(
            "missing Web fix deve script; set WEBFIX_DEVE or place it at "
            "work/deve-202509-docstable-developergrub-upgrade.sh"
        )
    src = WEBFIX_DEVE.read_text(errors="ignore")
    pattern = re.compile(r"/bin/base64 -d > (/usr/ikuai/www/[^ ]+) <<'([^']+)'\n(.*?)\n\2", re.S)
    blocks = {dest: body for dest, _tag, body in pattern.findall(src)}
    missing = [dest for dest in WEBFIX_FILES if dest not in blocks]
    if missing:
        raise SystemExit(f"missing webfix blocks in {WEBFIX_DEVE}: {missing}")

    out = []
    for dest in WEBFIX_FILES:
        tag = "IKUAI_WEBFIX_" + dest.strip("/").replace("/", "_").replace(".", "_").replace("-", "_")
        mode = "644"
        out.append(
            f"""write_b64_file {shlex.quote(dest)} {shlex.quote(mode)} <<'{tag}'
{blocks[dest]}
{tag}
"""
        )
    return "\n".join(out)


def symlink_commands() -> str:
    commands = []
    func_dir = ROOT / "usr/ikuai/function"
    for link in sorted(func_dir.iterdir(), key=lambda p: p.name):
        if not link.is_symlink():
            continue
        target = link.readlink().as_posix()
        commands.append(f"ln -sf {shlex.quote(target)} {shlex.quote('/usr/ikuai/function/' + link.name)}")
    return "\n".join(commands)


def main() -> None:
    base = BASE_DEVE.read_text()
    if not base.rstrip().endswith("exit 0"):
        raise SystemExit(f"{BASE_DEVE} does not end with exit 0")
    base = base.rstrip()[: -len("exit 0")].rstrip()

    blocks = "\n".join(shell_write_block(rel, mode) for rel, mode in FILES)
    webfix_blocks = extract_webfix_blocks()
    links = symlink_commands()

    security = f"""

install_security_patch_3721()
{{
    umask 022
    mkdir -p /tmp/iktmp /etc/mnt/ikuai/security_patch_backup

    backup_file_once()
    {{
        local dest="$1"
        local rel="${{dest#/}}"
        local backup="/etc/mnt/ikuai/security_patch_backup/$rel.orig"
        if [ -f "$dest" ] && [ ! -f "$backup" ]; then
            mkdir -p "$(dirname "$backup")"
            cp -a "$dest" "$backup" 2>/dev/null || true
        fi
    }}

    write_b64_file()
    {{
        local dest="$1"
        local mode="$2"
        mkdir -p "$(dirname "$dest")"
        backup_file_once "$dest"
        /bin/base64 -d > "$dest"
        chmod "$mode" "$dest" 2>/dev/null || true
    }}

{blocks.rstrip()}

    mkdir -p /usr/ikuai/www/static/js
{webfix_blocks.rstrip()}
    rm -f /tmp/iktmp/*.cache /tmp/ikweb_cache/* 2>/dev/null || true

    mkdir -p /usr/ikuai/function
{textwrap.indent(links, "    ")}

    if [ -f /etc/passwd ]; then
        backup_file_once /etc/passwd
        awk -F: 'BEGIN{{OFS=FS}} $1=="root"{{$7="/etc/setup/rc"}} $1!="ikuai"{{print}}' /etc/passwd > /tmp/iktmp/passwd.security_patch && cat /tmp/iktmp/passwd.security_patch > /etc/passwd
    fi

    if [ -f /etc/shadow ]; then
        backup_file_once /etc/shadow
        awk -F: 'BEGIN{{OFS=FS}} $1!="ikuai"{{print}}' /etc/shadow > /tmp/iktmp/shadow.security_patch && cat /tmp/iktmp/shadow.security_patch > /etc/shadow
    fi

    if [ -f /etc/hosts ]; then
        backup_file_once /etc/hosts
        sed '/alpha-cloud-log\\..*\\.aliyuncs\\.com/d' /etc/hosts > /tmp/iktmp/hosts.security_patch && cat /tmp/iktmp/hosts.security_patch > /etc/hosts
    fi

    if [ -f /etc/release ]; then
        backup_file_once /etc/release
        sed -i \\
            -e 's/^VERSION=.*/VERSION={DISPLAY_VERSION}/' \\
            -e 's/^VERSION_NUM=.*/VERSION_NUM={DISPLAY_VERSION_NUM}/' \\
            -e 's/^BUILD_DATE=.*/BUILD_DATE={DISPLAY_BUILD_DATE}/' \\
            -e 's/^VERSTRING=.*/VERSTRING="{DISPLAY_VERSTRING}"/' \\
            /etc/release
        grep -q '^PATCH_VERSION=' /etc/release || echo 'PATCH_VERSION=Patch3725' >> /etc/release
        grep -q '^PATCH_BASE_VERSION=' /etc/release || echo 'PATCH_BASE_VERSION=3.7.21' >> /etc/release
    fi

    openresty -s reload >/dev/null 2>&1 || true
    echo '{BUILD} {DISPLAY_VERSION} Patch3725 wg security runtime patch applied' > /etc/mnt/ikuai/security_patch_3721_version 2>/dev/null || true
    echo '{BUILD} {DISPLAY_VERSION} Patch3725 wg security runtime patch applied' > /tmp/iktmp/security_patch_3721_version 2>/dev/null || true
}}

install_security_patch_3721 >/tmp/iktmp/security_patch_3721_install.log 2>&1

exit 0
"""
    OUT.write_text(base + security)
    OUT.chmod(0o755)
    print(OUT)
    print(OUT.stat().st_size)


if __name__ == "__main__":
    main()
