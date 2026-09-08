#!/bin/bash
set -e

echo "正在查询IP地址、子网掩码、网关和DNS服务器..."
echo "----------------------------------------------"
ip route show | awk '/default/ {print "网关: "$3}'
echo
ip -o -4 addr show | awk -F '[ /]+' '/global/ {print "IP地址: "$4"\n子网掩码: "$5}'
echo
awk '/nameserver/ {print "DNS服务器 : ", $2}' /etc/resolv.conf
echo "----------------------------------------------"

while true; do
    read -r -p "请牢记以上信息，按 y 继续，按 n 退出..." yn
    case $yn in
        [Yy]* ) break;;
        [Nn]* ) exit;;
        * ) echo "请输入 y 或 n.";;
    esac
done

echo "请选择您的系统位数："
echo "1. 32位"
echo "2. 64位"
read -r -p "请输入选项（默认为2）:" option

if [ "${option:-2}" = "1" ]; then
    sysbit="x32"
else
    sysbit="x64"
fi

img_url="https://raw.githubusercontent.com/baby666666/ikuai-install/main/iso/iKuai8_${sysbit}_3.7.19_Build202504071142_eth0-wan1-wanweb.img.gz"
workdir=$(mktemp -d)
cleanup() {
    rm -rf "$workdir"
}
trap cleanup EXIT

echo "将使用 img.gz 方式安装 iKuai，不再使用 ISO/GRUB 菜单安装。"
echo "镜像已预设：eth0 -> wan1，并开启 WAN 口 Web 访问。"

cd "$workdir"
if command -v curl >/dev/null 2>&1; then
    curl -fsSLO https://raw.githubusercontent.com/bin456789/reinstall/main/reinstall.sh
else
    wget -q https://raw.githubusercontent.com/bin456789/reinstall/main/reinstall.sh -O reinstall.sh
fi

chmod +x reinstall.sh
echo "正在调用 reinstall.sh 写入 ${sysbit} 镜像..."
bash reinstall.sh dd --img "$img_url"
