#!/usr/bin/env bash
#
# 在部署机（绿联 NAS）上导入导出的镜像 tar 并启动。离线、无需 registry。
# 需要和 export-image.sh 使用相同的 ARCH / TAG / IMAGE_NAME。
#
# 用法：
#   ./deploy/offline/load-and-run.sh thumbelina-amd64-latest.tar
#   ./deploy/offline/load-and-run.sh thumbelina-arm64-v1.2.tar v1.2
set -euo pipefail

IMAGE_FILE="${1:?用法: ./deploy/offline/load-and-run.sh <镜像tar文件> [tag]}"
TAG="${2:-latest}"
IMAGE_NAME="${IMAGE_NAME:-thumbelina}"

echo ">>> 导入 ${IMAGE_FILE}"
docker load -i "${IMAGE_FILE}"

echo ">>> 启动 ${IMAGE_NAME}:${TAG}"
export THUMBELINA_IMAGE="${IMAGE_NAME}:${TAG}"
docker compose up -d
docker compose ps
