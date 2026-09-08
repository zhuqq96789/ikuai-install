# Patch3725 安全补丁包综合手册

本文档把最近几天的 iKuai Patch3725 安全补丁包资料整合成一个入口，方便下次 Codex 直接接手、验证当前包，或继续生成新的安全补丁固件。

## 当前结论

当前最新已验证固件：

```text
iso/iKuai8_x64_3.7.25_Patch3725_Build202609090052.bin
```

GitHub Raw：

```text
https://raw.githubusercontent.com/baby666666/ikuai-install/main/iso/iKuai8_x64_3.7.25_Patch3725_Build202609090052.bin
```

校验：

```text
MD5    eecc044b6139714d7c0c23911d091758
SHA256 eec2d29352ac8ca002f13e3b2195f1363d9e4e47b94953e0852b4aebb11149b0
SIZE   47382848 bytes
```

系统显示版本：

```text
3.7.25 x64 Enterprise Patch Build202609090052
```

技术事实：

- 底层功能/授权基线仍是 `3.7.21 x64 Enterprise`。
- 安全补丁来源为 `3.7.24` 和 `3.7.25`。
- 不替换 signed rootfs。
- 不整体合入新版授权、证书、云绑定、配置数据库。
- 通过升级后追加运行态补丁实现安全修复和功能恢复。
- 当前包已经过路由器真实升级和功能回归验证。

## 下次 Codex 阅读顺序

新电脑或新会话接手时，按这个顺序阅读：

```text
docs/patch-3725/SECURITY_PATCH_BUNDLE_MANUAL_ZH.md
```

机器可读审计资料：

```text
docs/patch-3725/changes.json
docs/patch-3725/merge-into-3721.json
docs/patch-3725/helper-tests-3721-merged.json
docs/patch-3725/text-changes.patch
```

## 仓库内关键文件

正式固件：

```text
iso/iKuai8_x64_3.7.25_Patch3725_Build202609090052.bin
iso/SHA256SUMS
```

当前运行态补丁脚本：

```text
patches/patch-3725/deve-3.7.21-wg-security-3725-runtime.sh
```

脚本 SHA256：

```text
414f9db8912cae29550b8efa615255d789153057d8d1ee4dfe778bf6b1d93a8e
```

构建和验证工具：

```text
tools/codex/
```

## 必须保留的功能

每次构建新包后都必须验证：

- WireGuard `wg1` 存在。
- WireGuard 页面包含二维码、导入、导出入口。
- `wireguard.show TYPE=interface` 返回 `wg1`。
- `wireguard.show TYPE=wg_iface` 返回 `wg1`。
- `wireguard.show TYPE=defaults` 可用。
- `wireguard.show TYPE=gen_privatekey` 可用。
- `stream_ipport.show TYPE=interface` 返回 `wg1`。
- 可以临时添加并删除禁用状态的 `wg1` 端口分流规则。
- OpenVPN 客户端可以临时添加、读回并删除带 CA 证书的禁用配置。
- `ipgroup.show TYPE=china_iplib` 返回中国 IP 库配置。
- 插件控制面板可用。
- 云端远控默认关闭，`plugin_ctpanel.show TYPE=data` 返回 `rcstatus=off`。
- 云端远控禁用时，`syslog-sysevent` 不再新增 `route_collect 云平台远控服务重新启动`。

## 已合入的安全补丁类型

已合入并验证的加固范围：

- DNS 相关修复继续保留。
- SQL helper 参数转义和字段类型校验。
- URL decode 去除危险 `eval`。
- `etc/ikcommon` 去除危险动态执行。
- `json.sh`、`check_varl.sh`、`route_rule.sh`、`iproute.sh` 等公共 helper 加固。
- `monitor_process.sh` 不再执行 `/tmp/iktmp/*.status` 这类路径脚本。
- `monitor_process.sh` 在 `RCSTATUS=off` 时跳过 `ik_rc_client`。
- `monitor_process.sh` 在 `RCSTATUS=off` 时跳过 `cre/route_collect`，避免云远控禁用后系统日志刷屏。
- `openvpn-client.sh` 会自动补齐 3.7.25 脚本需要、但 3.7.21 配置库可能缺失的 `check_link_mode` 和 `check_link_host` 列，避免添加 CA 证书时 SQL 写入失败。
- AC、OpenVPN、WebAuth、ACL、IPv6、route/stream 相关输入校验。
- Web 上传/下载路径加固。
- `/command/file` 禁用或错误返回验证。
- `/etc/release` 只做最小字段更新，用于界面显示 Patch 版本。

## 明确不整体合入的内容

不要整体合入：

```text
signed rootfs
etc/defaults/config_db.conf
etc/ssl/default/*
设备授权、云绑定、证书链相关文件
会改变 3.7.21 授权方式的 console/SSH 链
```

原因：

- 可能破坏升级校验。
- 可能破坏 WireGuard schema。
- 可能改变既有授权方式。
- 可能导致企业版功能不可用。

## 新电脑快速验证当前包

```bash
git clone https://github.com/baby666666/ikuai-install.git
cd ikuai-install

python3 tools/codex/inspect_ikuai_bin.py \
  iso/iKuai8_x64_3.7.25_Patch3725_Build202609090052.bin

sha256sum -c iso/SHA256SUMS
```

macOS 使用：

```bash
shasum -a 256 -c iso/SHA256SUMS
```

`inspect_ikuai_bin.py` 必须看到：

```text
firmwareid: 10001
version: 3.7.25
sysbit: x64
timestamp: 202609090052
payload_md5_ok: True
payload_sha256_prefix_ok: True
```

## 路由器验证当前包

真实路由器地址和密码由用户临时提供，不写进 GitHub：

```bash
export IKUAI_URL='https://<router-ip-or-host>'
export IKUAI_PASSWORD='<router-admin-password>'
```

先 parse：

```bash
python3 tools/codex/validate_ikuai_upgrade.py \
  --base-url "$IKUAI_URL" \
  --password "$IKUAI_PASSWORD" \
  --package iso/iKuai8_x64_3.7.25_Patch3725_Build202609090052.bin \
  --insecure \
  --upload-timeout 600
```

确认 parse 通过后再升级：

```bash
python3 tools/codex/validate_ikuai_upgrade.py \
  --base-url "$IKUAI_URL" \
  --password "$IKUAI_PASSWORD" \
  --package iso/iKuai8_x64_3.7.25_Patch3725_Build202609090052.bin \
  --upgrade \
  --insecure \
  --upload-timeout 600 \
  --wait 300
```

升级后功能回归：

```bash
python3 tools/codex/validate_3721_security_patch.py \
  --base-url "$IKUAI_URL" \
  --password "$IKUAI_PASSWORD" \
  --insecure \
  --expect-version 3.7.25 \
  --expect-build-date 202609090052 \
  --expect-enterprise 1

python3 tools/codex/validate_stream_ctpanel.py \
  --base-url "$IKUAI_URL" \
  --password "$IKUAI_PASSWORD" \
  --insecure \
  --log-wait 75

python3 tools/codex/validate_wg_ipgroup_features.py \
  --base-url "$IKUAI_URL" \
  --password "$IKUAI_PASSWORD" \
  --insecure

python3 tools/codex/validate_openvpn_ca.py \
  --base-url "$IKUAI_URL" \
  --password "$IKUAI_PASSWORD" \
  --insecure
```

## 生成下一版固件

本节为后续生成新版本补丁包的权威流程。核心流程：

1. 新建本地临时目录。

   ```bash
   mkdir -p work/input outputs work/security-<target-version>
   ```

2. 获取新官方固件到 `work/input/`。

3. 解包、解密、抽取 rootfs。

4. 对比官方相邻版本差异，先写安全差异报告。

5. 只选择性合入安全补丁，不整体覆盖 rootfs。

6. 生成运行态补丁树。

7. 生成 `deve` 运行态脚本。

8. 用压缩注入构建候选升级包。

9. 本地检查包头、payload、helper 测试。

10. 路由器 parse、真实升级、功能回归。

11. 全部通过后再复制到 `iso/`，更新 `SHA256SUMS` 和文档。

## 下一版命名模板

假设目标为 `3.7.26`：

```text
iso/iKuai8_x64_3.7.26_Patch3726_BuildYYYYMMDDHHMM.bin
patches/patch-3726/deve-3.7.21-wg-security-3726-runtime.sh
docs/patch-3726/
work/security-3.7.26/
work/rootfs-3.7.21-security-3726-patched-tree/
outputs/iKuai8_x64_3.7.26_Patch3726_BuildYYYYMMDDHHMM_CANDIDATE.bin
```

版本显示模板：

```text
VERSION=3.7.26
VERSION_NUM=300070026
BUILD_DATE=YYYYMMDDHHMM
VERSTRING="3.7.26 x64 Enterprise Patch BuildYYYYMMDDHHMM"
```

## 交付标准

满足以下条件才能交付：

- 本地脚本语法检查通过。
- Python 构建/验证脚本编译通过。
- 固件包头和 payload 校验通过。
- 路由器 parse 通过。
- 路由器真实升级成功。
- 系统版本显示为目标 Patch 版本。
- WireGuard、二维码/导入/导出、端口分流 `wg1`、中国 IP、云端远控、安全探针全部通过。
- OpenVPN 客户端 CA 证书新增、读回、删除通过。
- 禁用云端远控时不新增 `route_collect` 云远控重启日志。
- 正式文件写入 `iso/`。
- `iso/SHA256SUMS`、README、验证摘要、生成流程文档同步更新。
- 提交前确认没有真实路由器地址、密码、本机绝对路径。

## 发布检查

提交前：

```bash
git status --short
git diff --stat
rg -n '/Users/|<router-admin-password>|<router-ip-or-host>|password|passwd' .
```

提交并推送：

```bash
git add iso patches docs README.md tools/codex
git commit -m "Add iKuai <version> security patch firmware"
git push origin main
```

推送后确认：

```bash
git ls-remote --heads origin main
```
