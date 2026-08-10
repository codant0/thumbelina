#!/usr/bin/env bash
#
# 在构建机（PC/CI）上构建 Thumbelina 多架构镜像并推送到私有 registry。
# NAS 端无需构建，直接拉取镜像运行。
#
# 前置条件：
#   1) Docker 已安装且含 buildx 插件（Docker 23+ 自带）
#   2) 已登录 registry：               docker login <REGISTRY>
#   3) 构建非本机架构（如 x86 上构建 arm64）需启用 QEMU：
#        docker run --privileged --rm tonistiigi/binfmt --install all
#   4) 内网 HTTP registry 需在 /etc/docker/daemon.json 配置 insecure-registries
#
# 用法：
#   REGISTRY=192.168.1.100:5000 ./deploy/online/build-and-push.sh
#   REGISTRY=my-registry.cn.com TAG=v1.2 ./deploy/online/build-and-push.sh
#   REGISTRY=... TAG=... PIP_INDEX_URL=https://pypi.org/simple NPM_REGISTRY=https://registry.npmjs.org ./deploy/online/build-and-push.sh
set -euo pipefail

REGISTRY="${REGISTRY:?用法：REGISTRY=registry地址 ./deploy/online/build-and-push.sh [tag]}"
IMAGE_NAME="${IMAGE_NAME:-thumbelina}"
TAG="${1:-${TAG:-$(git rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M)}}"
PLATFORMS="${PLATFORMS:-linux/amd64,linux/arm64}"
FULL_IMAGE="${REGISTRY}/${IMAGE_NAME}:${TAG}"

# 可选覆盖国内镜像源（默认已内置清华 pip / npmmirror）
BUILD_ARGS=()
[[ -n "${PIP_INDEX_URL:-}" ]] && BUILD_ARGS+=(--build-arg "PIP_INDEX_URL=${PIP_INDEX_URL}")
[[ -n "${PIP_TRUSTED_HOST:-}" ]] && BUILD_ARGS+=(--build-arg "PIP_TRUSTED_HOST=${PIP_TRUSTED_HOST}")
[[ -n "${NPM_REGISTRY:-}" ]] && BUILD_ARGS+=(--build-arg "NPM_REGISTRY=${NPM_REGISTRY}")

BUILDER="thumbelina-builder"
docker buildx create --name "${BUILDER}" --use 2>/dev/null || docker buildx use "${BUILDER}"

echo ">>> 构建并推送 ${FULL_IMAGE} (${PLATFORMS})"
docker buildx build "${BUILD_ARGS[@]}" \
  --platform "${PLATFORMS}" \
  --push \
  --tag "${FULL_IMAGE}" \
  --file Dockerfile \
  .

echo ">>> 完成。NAS 上执行："
echo "    REGISTRY=${REGISTRY} TAG=${TAG} ./deploy/online/pull-and-run.sh"
