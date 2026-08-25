#!/usr/bin/env bash
#
# 在部署机（绿联 NAS）上从私有 registry 拉取镜像并启动。
# 需要和 build-and-push.sh 使用相同的 REGISTRY / VERSION / IMAGE_NAME。
# 未指定版本号时，使用仓库根目录 VERSION 文件的当前版本（不递增）。
#
# 前置条件：
#   1) 已登录 registry：               docker login <REGISTRY>
#   2) 内网 HTTP registry 需在 /etc/docker/daemon.json 配置 insecure-registries
#
# 用法：
#   REGISTRY=192.168.1.100:5000 ./deploy/online/pull-and-run.sh          # 使用 VERSION 文件当前版本
#   REGISTRY=my-registry.cn.com ./deploy/online/pull-and-run.sh v1.2.3   # 手动指定版本
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../lib/version.sh
source "${SCRIPT_DIR}/../lib/version.sh"

REGISTRY="${REGISTRY:?用法：REGISTRY=registry地址 [版本号] ./deploy/online/pull-and-run.sh}"
IMAGE_NAME="${IMAGE_NAME:-thumbelina}"
VERSION_ARG="${1:-${VERSION:-}}"
if [[ -n "${VERSION_ARG}" ]]; then
  VERSION="$(version_normalize "${VERSION_ARG}")"
else
  VERSION="$(version_current)"
fi

export THUMBELINA_IMAGE="${REGISTRY}/${IMAGE_NAME}:${VERSION}"

echo ">>> 拉取 ${THUMBELINA_IMAGE}"
docker compose pull thumbelina

echo ">>> 启动"
docker compose up -d
docker compose ps