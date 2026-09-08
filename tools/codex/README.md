# Codex 构建与验证工具

这些脚本来自 `3.7.21 + 3.7.25 Patch3725` 安全加固流程，用于后续 GPT/Codex 继续分析、合并、构建和验证。

## 推荐阅读顺序

先读：

```text
docs/patch-3725/SECURITY_PATCH_BUNDLE_MANUAL_ZH.md
docs/patch-3725/README.md
```

再按需使用本目录脚本。

## 脚本分类

解包/解密：

```text
extract_ikuai_payload.py
decrypt_ikuai_ikmf_v3.py
decrypt_rootfs_v3_python.py
ext4_extract_ro.py
ext_read.py
```

差异分析：

```text
prepare_security_compare.py
compare_rootfs_security.py
audit_security_artifacts.py
```

合并/构建：

```text
merge_3725_security_into_3721.py
build_deve_3721_3725_security_runtime.py
build_ikuai_upgrade_with_deve_compressed.py
```

验证：

```text
test_3725_helpers.py
inspect_ikuai_bin.py
validate_ikuai_upgrade.py
validate_3721_security_patch.py
validate_stream_ctpanel.py
validate_wg_ipgroup_features.py
validate_openvpn_ca.py
```

## 运行约定

这些脚本默认从仓库根目录运行，并使用 `work/` 作为临时工作区。新版本固件建议放到：

```text
work/input/
```

构建 `deve` 脚本时，如果需要额外的 Web 修复基线脚本，可通过环境变量指定：

```bash
WEBFIX_DEVE=work/deve-202509-docstable-developergrub-upgrade.sh \
python3 tools/codex/build_deve_3721_3725_security_runtime.py
```

路由器验证脚本需要当前操作者提供目标地址和密码，不要把真实地址或密码写进仓库。
