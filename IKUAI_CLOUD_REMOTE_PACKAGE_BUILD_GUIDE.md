# iKuai 云远控与插件控制面板修改包制作说明

这份说明给后续接手的 GPT 或维护者使用，目标是复现当前已验证的 Web 升级包：

```text
outputs/iKuai8_x64_3.7.21_Enterprise-ShellFull-WG-DNS-Test_Build202607030351_fw10001.bin
```

参考写法来自项目中的 `PACKAGE_BUILD_GUIDE.md`：

```text
https://github.com/baby666666/ikuai-install/blob/main/PACKAGE_BUILD_GUIDE.md
```

## 当前实现思路

本包基于原 Enterprise/ShellFull 升级包继续做 Web 升级包注入，目标是在保留“插件管理 / 控制面板 / 软件源管理”的同时，添加并修复“系统功能管理 / 禁用云端远控”开关。

最终稳定方案：

1. Web 升级包仍使用 iKuai 系统升级包格式，payload 写第 1 分区。
2. 头部 JSON 的 `filename` 字段注入一次性 shell 安装逻辑，写入并执行 `/etc/mnt/deve.sh`。
3. `/etc/log/script/install.sh` 会在后续启动时继续执行 `/etc/mnt/deve.sh`，确保补丁持久生效。
4. 由于当前目标路由器运行态是普通版，升级包头部必须使用 `firmwareid=10001`，否则 Web 后台会提示“无法识别这个文件”。
5. Enterprise/ShellFull 原包移除了云远控相关二进制和证书，所以最终包内嵌 `ordinary_cloud_restore.tar.gz`，升级时恢复普通版的远控组件。

## 最终成品信息

最终可用包：

```text
outputs/iKuai8_x64_3.7.21_Enterprise-ShellFull-WG-DNS-Test_Build202607030351_fw10001.bin
```

文件校验：

```text
MD5:    1138d8e2511a4bad1beaf2e8829d49fb
SHA256: 6e1740f379d826ed9cd8b4c1285f0baa6b4f821203c9489d75c2ac5f964714ac
Size:   46949736 bytes
```

头部字段：

```text
firmwareid: 10001
version:    3.7.21
sysbit:     x64
timestamp:  1758539410
payload md5:    a8c3c13bfea6f35b3c5b80223361a112
payload sha256: e1f7ea4cc46e3ed57d028ec130c08da903521a1db899da4f971d4dd232a3dabf
header_tail_len: 362623
filename_len:    782864
```

## 关键输入文件

原始 Enterprise/ShellFull 包：

```text
<local-or-workspace>/iKuai8_x64_3.7.21_Enterprise-ShellFull-WG-DNS-Test_Build202509221921.bin
```

普通版参考包：

```text
<local-or-workspace>/iKuai8_x64_3.7.21_Build202508211345.bin
```

最终工作文件：

```text
work/extracted/p1.img
work/extracted/deve.sh
work/ordinary_cloud_restore.tar.gz
work/repack_upgrade_bin.py
```

`ordinary_cloud_restore.tar.gz` 从普通版 rootfs 提取，包含云远控恢复所需组件：

```text
/usr/sbin/pmd
/usr/sbin/ik_rc_client
/usr/sbin/cre
/etc/remote2
/etc/ssl/32015
/etc/ssl/32016
/etc/ssl/32017
/etc/get_hosts
/usr/ikuai/script/utils/get_hosts.sh
/usr/ikuai/script/utils/update_hosts.sh
```

## 需要的工具

基础工具：

```bash
python3
gzip
base64
tar
shasum 或 sha256sum
md5 或 md5sum
```

本次在 macOS 上操作。由于 macOS 没有方便的 `debugfs`，额外写了只读 ext 提取脚本：

```text
work/extract_ext_paths.py
```

它只读取 ext2/ext4 镜像中的固定路径，不修改镜像。

## Web 升级包格式

`.bin` 文件结构：

```text
4 字节大端 header_tail 长度
gzip 头部去掉前 10 字节后的 header_tail
payload.gz
```

iKuai 解析时会补固定 gzip 头：

```text
1f 8b 08 00 6f 9b 4b 59 02 03
```

header JSON 必要字段：

```json
{
  "filename": "注入 shell 逻辑",
  "firmwareid": "10001",
  "version": "3.7.21",
  "sysbit": "x64",
  "timestamp": "1758539410",
  "length": "payload.gz 文件大小",
  "md5": "payload.gz 的 md5",
  "sha256": "payload.gz 的 sha256 前 32 位"
}
```

## 本包注入逻辑

核心逻辑位于：

```text
work/repack_upgrade_bin.py
work/extracted/deve.sh
```

`repack_upgrade_bin.py` 会：

1. 将 `p1.img` gzip 为 payload。
2. 计算 payload 的 MD5 和 SHA256。
3. 将 `deve.sh` base64 后写入 header JSON 的 `filename` 字段。
4. 在解析升级包时写入 `/etc/mnt/deve.sh`。
5. 写入 `/etc/log/script/install.sh`，确保启动后继续应用补丁。
6. 重新设置 `filename="真实升级包名"`，避免后续升级流程异常。

最终执行命令：

```bash
BUILD=202607030351
OUT="outputs/iKuai8_x64_3.7.21_Enterprise-ShellFull-WG-DNS-Test_Build${BUILD}_fw10001.bin"

python3 work/repack_upgrade_bin.py \
  --p1 work/extracted/p1.img \
  --deve work/extracted/deve.sh \
  --output "$OUT" \
  --build "$BUILD" \
  --version 3.7.21 \
  --firmwareid 10001 \
  --sysbit x64 \
  --timestamp 1758539410 \
  --payload-gz "work/payload-${BUILD}.gz"
```

## `deve.sh` 主要职责

`deve.sh` 会安装或修复以下内容：

```text
/usr/ikuai/script/cloud_remote_guard.sh
/usr/ikuai/script/plugin_ctpanel.sh
/usr/ikuai/function/plugin_ctpanel
/usr/ikuai/www/plugins/01.ctpanel/metadata.json
/usr/ikuai/www/plugins/01.ctpanel/index.html
/usr/ikuai/script/utils/get_hosts.sh
/usr/ikuai/script/utils/update_hosts.sh
```

功能分为四块：

1. 恢复云远控组件：解出 `ordinary_cloud_restore.tar.gz`，恢复 `ik_rc_client`、`pmd`、`cre`、证书和 host 更新脚本。
2. 修复绑定逻辑：移除 Enterprise 包里强制 `ForceBindCloud` 的伪绑定逻辑。
3. 提供开关：`RCSTATUS=off` 时清空绑定、下发防火墙阻断规则；`RCSTATUS=on` 时恢复绑定并启动远控组件。
4. 提供诊断：`plugin_ctpanel show TYPE=diag_cloud` 和 `TYPE=fix_cloud` 可返回进程、证书、host、iptables 和启动日志。

## 云远控修复点

Enterprise/ShellFull 原始改造对云端远控做了多处删除和阻断：

```text
删除 /usr/sbin/pmd
删除 /usr/sbin/ik_rc_client
删除 /usr/sbin/cre
删除 /etc/remote2
删除 /etc/ssl/32015、32016、32017
删除 get_hosts.sh / update_hosts.sh
删除 rc 中 start_remote_services
删除 monitor_process 中远控进程守护逻辑
添加 cloud_DROP 防火墙阻断链
register.sh 强制写入 ForceBindCloud / IK-Router 伪绑定
```

本包做了对应恢复：

```text
恢复普通版二进制、证书和配置
恢复 update_hosts.sh / get_hosts.sh
清理 cloud_DROP 和 CLOUD_REMOTE_BLOCK
修补 register.sh，移除伪绑定
修补 monitor_process.sh，守护 pmd / ik_rc_client / cre
启动 pmd / ik_rc_client / cre
```

## 插件功能

插件路径：

```text
系统设置 > 插件管理 > 控制面板
```

保留功能：

```text
软件源管理
```

新增/修复功能：

```text
系统功能管理 > 禁用云端远控
```

开关含义：

```text
关闭“禁用云端远控”：RCSTATUS=on，允许绑定 iKuai 云和 App 远控。
开启“禁用云端远控”：RCSTATUS=off，清空绑定状态并阻断云远控端口。
```

## 构建踩坑

### 1. `firmwareid` 必须匹配当前运行版

目标路由器升级后运行态显示为普通版，所以 `firmwareid=10002` 会提示：

```text
错误: 无法识别这个文件
```

稳定值：

```text
firmwareid=10001
```

### 2. 不要依赖第二个上传文件

曾尝试先上传 `ordinary_cloud_restore.tar.gz`，再上传升级包。实际 `/Action/upload` 在第二次上传或 `upgrade.clean_file` 后会清掉前一次上传文件，导致安装日志出现：

```text
ordinary_cloud_restore.tar.gz missing
```

最终方案是把 `ordinary_cloud_restore.tar.gz` 直接内嵌进 `deve.sh`。

### 3. header 注入长度要控制

头部 `header_tail` 明确不能超过 1048576 字节。实际还要注意 `filename` 解压后的脚本长度，过大时解析器也可能失败。

最终包参数：

```text
header_tail_len: 362623
filename_len:    782864
```

为了控制长度，本包删掉了无关的大块主 Web 静态 JS 补丁，仅保留插件 UI 和后端脚本。

### 4. 只恢复绑定不够

一开始只修复了 `register.sh` 后，云绑定可以成功，但手机 App 操作提示：

```text
未找到该设备，请检查设备是否在线
```

根因是远控长连接组件没有运行。必须恢复并启动：

```text
pmd
ik_rc_client
cre
```

## Web API 上传升级流程

可以用 Web 后台手动上传，也可以用 API 自动上传。

API 流程：

```python
import requests, hashlib, base64, time, pathlib

base = "http://<ROUTER_WEB_IP>"
pw = "<ROUTER_PASSWORD>"
pkg = pathlib.Path("outputs/iKuai8_x64_3.7.21_Enterprise-ShellFull-WG-DNS-Test_Build202607030351_fw10001.bin")

s = requests.Session()
s.post(base + "/Action/login", json={
    "username": "admin",
    "passwd": hashlib.md5(pw.encode()).hexdigest(),
    "pass": base64.b64encode(pw.encode()).decode(),
    "remember_password": ""
})

def call(func, action, param=None):
    return s.post(base + "/Action/call", json={
        "func_name": func,
        "action": action,
        "param": param or {}
    })

call("upgrade", "clean_file")

upname = f"upgrade-{int(time.time())}.bin"
with pkg.open("rb") as f:
    s.post(base + "/Action/upload", files={
        upname: (upname, f, "application/octet-stream")
    })

call("upgrade", "parse_file", {"filename": upname})
call("upgrade", "show", {"TYPE": "fileinfo"})
call("upgrade", "update_file")
```

## 校验脚本

生成后必须校验包结构：

```python
import gzip
import hashlib
import json
import struct
from pathlib import Path

p = Path("outputs/iKuai8_x64_3.7.21_Enterprise-ShellFull-WG-DNS-Test_Build202607030351_fw10001.bin")
data = p.read_bytes()
headlen = struct.unpack(">I", data[:4])[0]
fixed = bytes.fromhex("1f8b08006f9b4b590203")
header = json.loads(gzip.decompress(fixed + data[4:4 + headlen]))
payload = data[4 + headlen:]

assert header["firmwareid"] == "10001"
assert header["version"] == "3.7.21"
assert header["sysbit"] == "x64"
assert len(payload) == int(header["length"])
assert hashlib.md5(payload).hexdigest() == header["md5"]
assert hashlib.sha256(payload).hexdigest()[:32] == header["sha256"]
assert "base64 -d > /etc/mnt/deve.sh" in header["filename"]
assert "ordinary_cloud_restore.tar.gz" in header["filename"]

print("OK")
print("file md5:", hashlib.md5(data).hexdigest())
print("file sha256:", hashlib.sha256(data).hexdigest())
```

## 路由器侧验证

升级后登录路由器，调用插件诊断：

```python
call("plugin_ctpanel", "show", {"TYPE": "data"})
call("plugin_ctpanel", "show", {"TYPE": "fix_cloud"})
call("plugin_ctpanel", "show", {"TYPE": "diag_cloud"})
call("register", "show", {"TYPE": "data"})
call("register", "show", {"TYPE": "services"})
```

已验证的关键结果：

```text
plugin_ctpanel.show TYPE=data:
  sources 中保留“官方插件源”
  rcstatus = on

register.show TYPE=data:
  code = 0b620843599cbbfce96a14289eadcbaf
  comment = 1
  node = 0

register.show TYPE=services:
  status = 1
  errinfo = success

diag_cloud:
  /usr/sbin/ik_rc_client 存在并运行
  pmd 存在并运行
  cre 存在并运行
  cloud_DROP / CLOUD_REMOTE_BLOCK 无残留
```

远控在线的关键证据：

```text
tcp <ROUTER_PUBLIC_IP>:<LOCAL_PORT> -> <IKUAI_REMOTE_SERVER_IP>:2501 ESTABLISHED <PID>/ik_rc_client
```

看到上述连接后，手机 App 理论上不应再提示：

```text
未找到该设备，请检查设备是否在线
```

如果 App 仍提示离线，先等待 1-2 分钟并重启 App，再调用 `TYPE=diag_cloud` 检查 `ik_rc_client` 是否仍为 `ESTABLISHED`。

注意：文档中的 `<ROUTER_WEB_IP>`、`<ROUTER_PUBLIC_IP>`、`<IKUAI_REMOTE_SERVER_IP>` 均为脱敏占位符，实际排查时按现场环境替换。

## 常用诊断字段

`plugin_ctpanel show TYPE=diag_cloud` 会返回：

```text
rcstatus
register_row
cloud_node
hosts_register
hosts_files
remote_files
remote_conf
cloud_process
cloud_netstat
client_helpers
iptables_cloud
start_log
install_log
cloud_test
```

其中最重要：

```text
cloud_process: 是否有 ik_rc_client / pmd / cre
cloud_netstat: 是否有 ik_rc_client ESTABLISHED
remote_files: /usr/sbin 和 /etc/remote2 组件是否恢复
start_log: 启动失败原因
iptables_cloud: 是否残留 cloud_DROP 或 CLOUD_REMOTE_BLOCK
```

## 注意事项

1. 当前目标路由器是普通版运行态，最终包必须用 `firmwareid=10001`。
2. 不要再单独上传 `ordinary_cloud_restore.tar.gz` 作为依赖，最终包已经自包含。
3. “禁用云端远控”打开后，iKuai 云绑定和 App 远控会被阻断；要绑定和 App 远控，必须保持该功能关闭。
4. 软件源管理必须保留，不要覆盖 `repos.json` 中已有源。
5. 不要恢复原 Enterprise 包里的 `ForceBindCloud` 伪绑定逻辑。
6. 不要只修 `register.sh`，App 远控在线必须依赖 `ik_rc_client` 长连接。
7. 如果后续 iKuai 修改 `upgrade.sh` source `/tmp/iktmp/upgrade/fileinfo` 的行为，header 注入方法可能失效。
8. 如果后续目标路由器重新变成企业版运行态，才需要重新评估 `firmwareid=10002`。
