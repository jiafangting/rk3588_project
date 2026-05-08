#!/bin/bash

# 安装 systemd 服务。
# 把 inspection.service 复制到 /etc/systemd/system/，并启用开机自启。

set -u

DIR=$(cd "$(dirname "$0")" && pwd)

sudo cp "$DIR/inspection.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable inspection
echo "开机自启已配置，重启后自动运行"
echo "手动启动命令：sudo systemctl start inspection"
echo "查看状态命令：sudo systemctl status inspection"
