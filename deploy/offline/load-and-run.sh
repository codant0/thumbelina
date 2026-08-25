#!/usr/bin/env bash
#
# 在部署机（绿联 NAS）上导入导出的镜像 tar 并启动。离线、无需 registry。
# 版本号自动从 tar 文件名识别（thumbelina-<arch>-<version>.tar），也接受 [版本号] 手动指定。
#
# 用法：
#   ./deploy/offline/load-and-run.sh thumbelina-amd64-v0.0.1.tar          # 版本自动从文件名识别
#   ./deploy/offline/load-and-run.sh thumbelina-arm64-latest.tar latest   # 无版本号时可手动指定 tag
set -euo pipefail

IMAGE_FILE="${1:?用法: ./deploy/offline/load-and-run.sh <镜像tar文件> [版本号]}"
IMAGE_NAME="${IMAGE_NAME:-thumbelina}"
VERSION="${2:-$(basename "${IMAGE_FILE%.tar}" | sed 's/.*-//')}"

echo ">>> 导入 ${IMAGE_FILE}"
docker load -i "${IMAGE_FILE}"

echo ">>> 启动 ${IMAGE_NAME}:${VERSION}"
export THUMBELINA_IMAGE="${IMAGE_NAME}:${VERSION}"
docker compose up -d
docker compose ps