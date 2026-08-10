#!/usr/bin/env bash
#
# 在构建机（PC）上构建 Thumbelina 镜像并导出为 tar 文件，离线拷到 NAS。
# NAS 上配合 deploy/offline/load-and-run.sh 导入启动，无需 registry、无需联网构建。
#
# 先确认 NAS 架构：绿联 DXP 系列 = amd64（x86），DH 系列 = arm64（ARM）。
# 注意：多平台镜像无法离线 docker save，这里按单架构导出，架构必须与 NAS 一致。
#
# 用法：
#   ./deploy/offline/export-image.sh                       # 默认 amd64，tag=latest
#   ARCH=arm64 ./deploy/offline/export-image.sh            # 构建 arm64（绿联 DH 系列）
#   ARCH=arm64 TAG=v1.2 ./deploy/offline/export-image.sh
set -euo pipefail

ARCH="${ARCH:-amd64}"
TAG="${TAG:-latest}"
IMAGE_NAME="${IMAGE_NAME:-thumbelina}"
OUT="${OUT:-${IMAGE_NAME}-${ARCH}-${TAG}.tar}"

# 构建非本机架构（如 x86 上构建 arm64）需先启用 QEMU：
#   docker run --privileged --rm tonistiigi/binfmt --install all
BUILDER="thumbelina-builder"
docker buildx create --name "${BUILDER}" --use 2>/dev/null || docker buildx use "${BUILDER}"

echo ">>> 构建 linux/${ARCH} 镜像 ${IMAGE_NAME}:${TAG}"
docker buildx build \
  --platform "linux/${ARCH}" \
  --load \
  --tag "${IMAGE_NAME}:${TAG}" \
  --file Dockerfile \
  .

echo ">>> 导出到 ${OUT}"
docker save -o "${OUT}" "${IMAGE_NAME}:${TAG}"

echo ">>> 完成。将 ${OUT} 拷到 NAS 后执行："
echo "    ./deploy/offline/load-and-run.sh ${OUT}"
