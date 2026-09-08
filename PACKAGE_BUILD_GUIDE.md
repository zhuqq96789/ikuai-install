# iKuai WireGuard 修改包制作说明

这份说明给后续接手的 GPT 或维护者使用，目标是复现当前仓库里的两个成品：

- 全新安装镜像：`iso/iKuai8_x64_3.7.21_Enterprise-ShellFull-WG-DNS-Test_Build202509221921_eth0-wan1-wanweb.img.gz`
- Web 升级包：`iso/iKuai8_x64_3.7.21_Enterprise-ShellFull-WG-DNS-Test_Build202509221921.bin`

## 当前实现思路

iKuai x86 系统升级包只会写入启动分区，也就是 `/dev/${BOOTHDD}1`。WireGuard 修改需要运行时补丁文件 `/etc/mnt/deve.sh`，该文件位于系统盘第 3 分区。因此不要通过重新加密 `/boot/rootfs` 来做修改，实测容易无限重启。

当前稳定方案：

1. 全新安装镜像使用完整磁盘镜像，直接在第 3 分区放入 `/deve.sh`。
2. Web 升级包仍使用系统升级包格式 `firmwareid=10001`，payload 写第 1 分区。
3. 为了让 Web 升级也保留功能，在 `.bin` 头部 JSON 的 `filename` 字段里注入一次性 shell 安装逻辑。iKuai 解析升级包时会把头部 JSON 写成 `/tmp/iktmp/upgrade/fileinfo` 并 source，这时先写入 `/etc/mnt/deve.sh` 和 `/etc/log/script/install.sh`，再执行正常系统升级流程。

## 需要的工具

建议在 Linux 环境操作，macOS 也可以，但处理 ext 分区会麻烦。

基础工具：

```bash
python3
gzip
sha256sum
md5sum
parted 或 sfdisk
losetup
mount
e2fsprogs
debugfs
```

可选工具：

```bash
qemu-img
binwalk
7z
```

## 关键输入文件

至少需要：

```text
原始 iKuai 3.7.21 Enterprise/ShellFull 镜像或升级包
已经验证可用的 deve.sh
```

当前稳定的 `deve.sh` 内容来自已验证可启动镜像的第 3 分区：

```text
/deve.sh
```

它的职责：

- 启动时修补 `/usr/ikuai/script/wireguard.sh`。
- 启动时修补 `/usr/ikuai/script/stream_ipport.sh`。
- 修补 WireGuard Web 前端 JS。
- 给 WireGuard 数据库补充字段。
- 修复本地公钥/私钥生成。
- 实现 WireGuard 接入流量源进源出。
- 实现 WireGuard 客户端接入流量优先按端口分流决定出口。
- 让端口分流线路支持真实 WAN、OpenVPN、PPTP、L2TP、IKEv2/IPSec、WireGuard 等接口。
- 实现 WireGuard 接口默认地址、端口、隧道地址、DNS 默认值。
- 实现中国 IP 库自动更新到 IP 分组，供分流规则选择。
- 写入标记文件便于检查版本。

## WireGuard 分流核心逻辑

这版分流优先级必须保持为：

1. WireGuard 客户端进入 iKuai 后，先经过 `流控分流 > 分流设置 > 端口分流`。
2. 如果端口分流命中源地址、目的地址、协议和线路，就按端口分流选择的出口走，例如 `ovpn_sc`、`wg1`、`wan2`。
3. 如果端口分流没有命中，WireGuard 才按源进源出处理，使用客户端连接进来的 WAN 作为默认返回出口。

为了解决 WG 客户端命中端口分流但实际仍走默认 WAN 的问题，`stream_ipport.sh` 里增加了 `WG_STREAM_PREROUTE` 兜底链：

- 在 `mangle PREROUTING` 最前面挂载 `WG_STREAM_PREROUTE`。
- 先用 `--dst-type LOCAL -j RETURN` 排除 WireGuard 握手、路由器 DNS、管理地址等发往路由器本机的流量。
- 对单线路端口分流规则直接 `MARK --set-mark` 到目标接口的 mark。
- 保存 connmark，避免后续包丢失标记。
- 对 VPN/WG 这类非 WAN 接口自动补 `ip rule fwmark -> table`。
- 对非 WAN 出口自动补 `POSTROUTING MASQUERADE`。

这个兜底链是必须保留的。只改 Web 线路列表不够，旧的 `NTH_CONNMARK -> ik_cntl mark_rule` 在 WG 入站转发场景下可能不会在首次路由查找前完成 skb mark，结果仍会走默认 WAN。

## 全新安装镜像制作

全新安装镜像是完整磁盘镜像压缩包，后缀为 `.img.gz`。

制作流程：

1. 准备一个可启动的 iKuai 完整磁盘镜像 `disk.img`。
2. 挂载第 3 分区。
3. 写入 `/deve.sh`。
4. 设置权限。
5. 卸载分区。
6. gzip 压缩整个磁盘镜像。

示例：

```bash
sudo losetup -Pf disk.img
losetup -a

# 假设设备为 /dev/loop0，第 3 分区为 /dev/loop0p3
sudo mkdir -p /mnt/ikuai-p3
sudo mount /dev/loop0p3 /mnt/ikuai-p3
sudo cp deve.sh /mnt/ikuai-p3/deve.sh
sudo chmod 755 /mnt/ikuai-p3/deve.sh
sync
sudo umount /mnt/ikuai-p3
sudo losetup -d /dev/loop0

gzip -c disk.img > iKuai8_x64_3.7.21_Enterprise-ShellFull-WG-DNS-Test_Build202509221921_eth0-wan1-wanweb.img.gz
```

校验：

```bash
sha256sum iKuai8_x64_3.7.21_Enterprise-ShellFull-WG-DNS-Test_Build202509221921_eth0-wan1-wanweb.img.gz
```

## 从完整镜像提取 Web 升级包 payload

Web 升级包的 payload 不是整盘镜像，而是第 1 分区镜像 gzip 后的内容。

从完整磁盘镜像提取第 1 分区：

```bash
sudo losetup -Pf disk.img
losetup -a

# 假设设备为 /dev/loop0
sudo dd if=/dev/loop0p1 of=p1.img bs=4M status=progress
sudo losetup -d /dev/loop0
```

生成 payload：

```bash
gzip -n -6 -c p1.img > payload.gz
```

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
  "filename": "...",
  "firmwareid": "10001",
  "version": "3.7.21",
  "sysbit": "x64",
  "timestamp": "1758539410",
  "length": "payload.gz 文件大小",
  "md5": "payload.gz 的 md5",
  "sha256": "payload.gz 的 sha256 前 32 位"
}
```

## Web 升级包注入逻辑

为了让 Web 升级后保留 WireGuard 功能，把安装逻辑放进 header JSON 的 `filename` 字段。核心逻辑是：

1. `filename` 字段先闭合字符串。
2. 写入 base64 编码的 `deve.sh` 到 `/etc/mnt/deve.sh`。
3. 写入 `/etc/log/script/install.sh`，让系统每次启动都应用补丁。
4. 立即执行一次 `/etc/log/script/install.sh`。
5. 最后重新设置正常的 `filename` 变量，避免后续升级流程异常。

注意：这是利用 iKuai 升级脚本会 source `/tmp/iktmp/upgrade/fileinfo` 的行为。仅适用于当前验证过的 iKuai 3.7.21 x64 Enterprise。

升级包里不要调用 `/etc/mnt/deve.sh boot_begin`。`boot_begin` 只适合全新安装镜像初始化网口时使用；Web 升级包必须保留用户现有网口绑定，不能把 `eth0` 强制绑定到 `wan1`。

当前成品进一步做了内容隔离：

- `.img.gz` 使用完整 `deve.sh`，保留 `boot_begin` 和原来的 `eth0 -> wan1 + wanweb` 全新安装初始化逻辑。
- `.bin` 使用升级专用 `deve.sh`，整个删除 `boot_begin` 分支和 eth0 绑定 SQL。即使以后其它启动逻辑误传参数，升级包也不能修改现有网口绑定。

生成 `.bin` 前，从完整脚本制作升级专用脚本：

```python
from pathlib import Path

src = Path("deve.sh").read_text()
start = src.rfind('\ncase "$1" in\nboot_begin)\n')
end = src.find("\nesac\nexit 0", start)
assert start >= 0 and end >= 0

upgrade = src[:start] + "\nexit 0" + src[end + len("\nesac\nexit 0"):]
assert "boot_begin)" not in upgrade
assert "update wan_config set bandif='$mac'" not in upgrade

Path("deve-upgrade.sh").write_text(upgrade)
```

随后让 `build_upgrade_bin.py` 的 `deve_path` 指向：

```python
deve_path = Path("deve-upgrade.sh")
```

## 生成 Web 升级包脚本

把下面脚本保存为 `build_upgrade_bin.py`，同目录放置：

```text
p1.img
deve.sh
```

当前仓库里的打包源脚本可直接使用：

```text
work/deve_wgwan.sh
```

如果按本教程新建临时构建目录，把它复制或改名为 `deve.sh` 后再生成升级包。

然后执行：

```bash
python3 build_upgrade_bin.py
```

脚本内容：

```python
import base64
import gzip
import hashlib
import json
import struct
import textwrap
from pathlib import Path

build = "202509221910"
payload_name = f"iKuai8_x64_3.7.21_Enterprise-ShellFull-WG-DNS-Test_Build{build}.bin"
out = Path(payload_name)

p1 = Path("p1.img")
deve_path = Path("deve.sh")
payload_gz = Path("payload.gz")

with p1.open("rb") as fin, payload_gz.open("wb") as raw:
    with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=6, mtime=0) as fout:
        while True:
            chunk = fin.read(1024 * 1024)
            if not chunk:
                break
            fout.write(chunk)

payload = payload_gz.read_bytes()
payload_md5 = hashlib.md5(payload).hexdigest()
payload_sha256 = hashlib.sha256(payload).hexdigest()

deve = deve_path.read_text()
deve_b64 = "\n".join(textwrap.wrap(base64.b64encode(deve.encode()).decode(), 76))

boot_install = """#!/bin/sh
mkdir -p /tmp/iktmp
if [ -f /etc/mnt/deve.sh ]; then
    chmod 755 /etc/mnt/deve.sh 2>/dev/null || true
    /etc/mnt/deve.sh >/tmp/iktmp/wg_wan_runtime_install.log 2>&1 || true
fi
exit 0
"""

injection = f'''x";
mkdir -p /etc/mnt /etc/mnt/ikuai /etc/log/script /tmp/iktmp 2>/dev/null
base64 -d > /etc/mnt/deve.sh <<'WG_DEVE_B64_{build}'
{deve_b64}
WG_DEVE_B64_{build}
chmod 755 /etc/mnt/deve.sh 2>/dev/null || true
cat > /etc/log/script/install.sh <<'WG_BOOT_INSTALL_{build}'
{boot_install}WG_BOOT_INSTALL_{build}
chmod 755 /etc/log/script/install.sh 2>/dev/null || true
/etc/log/script/install.sh >/tmp/iktmp/wg_upgrade_header_install.log 2>&1 || true
echo '{build} wg web-upgrade installer applied' > /etc/mnt/ikuai/wg_wan_web_upgrade_version 2>/dev/null || true
echo '{build} wg web-upgrade installer applied' > /tmp/iktmp/wg_wan_web_upgrade_version 2>/dev/null || true
filename="{payload_name}'''

header = {
    "filename": injection,
    "firmwareid": "10001",
    "version": "3.7.21",
    "sysbit": "x64",
    "timestamp": "1758539410",
    "length": str(len(payload)),
    "md5": payload_md5,
    "sha256": payload_sha256[:32],
}

header_json = json.dumps(header, separators=(",", ":"), ensure_ascii=False).encode()
header_gz = gzip.compress(header_json, compresslevel=9, mtime=0)
header_tail = header_gz[10:]

if len(header_tail) >= 1048576:
    raise SystemExit(f"header too large: {len(header_tail)}")

out.write_bytes(struct.pack(">I", len(header_tail)) + header_tail + payload)

print("output:", out)
print("payload md5:", payload_md5)
print("payload sha256:", payload_sha256)
print("file sha256:", hashlib.sha256(out.read_bytes()).hexdigest())
```

## Web 升级包校验脚本

生成后必须校验包结构：

```python
import gzip
import hashlib
import json
import struct
from pathlib import Path

p = Path("iKuai8_x64_3.7.21_Enterprise-ShellFull-WG-DNS-Test_Build202509221921.bin")
data = p.read_bytes()
headlen = struct.unpack(">I", data[:4])[0]
fixed = bytes.fromhex("1f8b08006f9b4b590203")
header = json.loads(gzip.decompress(fixed + data[4:4 + headlen]))
payload = data[4 + headlen:]

assert header["firmwareid"] == "10001"
assert len(payload) == int(header["length"])
assert hashlib.md5(payload).hexdigest() == header["md5"]
assert hashlib.sha256(payload).hexdigest()[:32] == header["sha256"]
assert "base64 -d > /etc/mnt/deve.sh" in header["filename"]
assert "deve.sh boot_begin" not in header["filename"]

print("OK")
print("file sha256:", hashlib.sha256(data).hexdigest())
```

## 当前成品校验值

当前仓库成品：

```text
608dee463b581453cd56f72d9a8bc014af39f4ba80721d9d04cc6909d222ca33  iso/iKuai8_x64_3.7.21_Enterprise-ShellFull-WG-DNS-Test_Build202509221921_eth0-wan1-wanweb.img.gz
8deec685c9c22bd7854d3081e790bf22657a519a2bcfd96b6c520467e3aa990c  iso/iKuai8_x64_3.7.21_Enterprise-ShellFull-WG-DNS-Test_Build202509221921.bin
```

## 测试步骤

1. Web 后台上传 `.bin`，必须能通过文件识别和 MD5 校验。
2. 升级后系统不能无限重启。
3. SSH 检查：

```bash
cat /etc/mnt/ikuai/wg_wan_web_upgrade_version
cat /etc/mnt/ikuai/wg_wan_hook_version
ls -l /etc/mnt/deve.sh /etc/log/script/install.sh
```

4. WireGuard 页面检查：

```text
网络设置 > VPN客户端 > WireGuard
```

5. 验证新增接口默认值：

```text
10.10.1.1/24, 50001
10.10.2.1/24, 50002
```

6. 验证新增隧道默认值：

```text
允许目标网段: 10.20.1.1/24
客户端 DNS: 8.8.8.8
```

7. 使用 WAN2 外网 IP 连接 WireGuard，查询出口 IP，应从 WAN2 返回，不应走默认 WAN1。

8. 验证 WireGuard 客户端流量可被端口分流改出口：

```text
流控分流 > 分流设置 > 端口分流

分流方式: 外网线路
线路: ovpn_sc 或其它 VPN/WG 线路
协议: 任意
源地址: 手机 WG 地址段，例如 10.20.2.0/24
目的地址: 留空
```

手机通过 WireGuard 连入 iKuai 后，访问公网查询 IP。端口分流命中时，公网出口应为所选线路；没有端口分流规则时，才按 WireGuard 源进源出走接入 WAN。

9. 验证端口分流线路列表必须包含真实接口：

```text
wan1/wan2
ovpn_xxx
pptp_xxx
l2tp_xxx
iked_xxx 或 ipsec_xxx
wg1/wg2/wg3
```

10. 如果分流到 OpenVPN 后公网 IP 仍不是 OpenVPN 对端，需要确认 OpenVPN 本身是否能作为公网出口：

```text
OpenVPN 客户端已连接并有 tunnel_ip
OpenVPN 服务端允许客户端转发公网流量
OpenVPN 服务端做了 NAT/MASQUERADE
```

iKuai 客户端配置里 `redirect_gateway=0`、`accept_push_route=0` 不一定代表不能分流到 OpenVPN；本包会为该接口补默认 dev 路由。但最终公网出口是否成功，还取决于 OpenVPN 服务端是否允许并 NAT 这些转发流量。

## 注意事项

- 不要重新加密 `/boot/rootfs`，之前测试会导致无限重启。
- Web 系统升级包只能可靠写第 1 分区，所以第 3 分区补丁必须通过 header 注入或完整磁盘镜像写入。
- Web 升级包不要调用 `deve.sh boot_begin`，否则可能改动用户原有网口绑定，造成升级后无法上网。
- `.bin` 内嵌脚本必须删除整个 `boot_begin` 分支和 eth0 绑定 SQL；`.img.gz` 才保留该逻辑。
- 不要只在 Web 前端加入 VPN/WG 线路选项，必须同步修补 `stream_ipport.sh` 的运行时路由和 mangle 规则。
- `WG_STREAM_PREROUTE` 必须先排除 `--dst-type LOCAL`，否则客户端访问路由器 DNS、管理地址或 WireGuard 握手流量可能被错误分流，表现为修改规则后 WireGuard 无法连接。
- WG 客户端走其它 VPN/WG 出口时，端口分流规则的源地址要填客户端地址段，例如隧道 peer 是 `10.20.2.1/24`，规则源地址填 `10.20.2.0/24`。
- 如果 iKuai 后续版本修改了 `upgrade.sh` 的 source 行为，这个 `.bin` 注入方法可能失效。
- 文件名可以改，但建议同步修改 header JSON 里的 `filename`，否则 Web 页面显示可能不一致。
