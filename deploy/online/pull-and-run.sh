#!/usr/bin/env bash
#
# 在部署机（绿联 NAS）上从私有 registry 拉取镜像并启动。
# 需要和 build-and-push.sh 使用相同的 REGISTRY / TAG / IMAGE_NAME。
#
# 前置条件：
#   1) 已登录 registry：               docker login <REGISTRY>
#   2) 内网 HTTP registry 需在 /etc/docker/daemon.json 配置 insecure-registries
#
# 用法：
#   REGISTRY=192.168.1.100:5000 TAG=abc1234 ./deploy/online/pull-and-run.sh
#   REGISTRY=my-registry.cn.com TAG=v1.2 ./deploy/online/pull-and-run.sh
set -euo pipefail

REGISTRY="${REGISTRY:?用法：REGISTRY=registry地址 TAG=镜像tag ./deploy/online/pull-and-run.sh}"
TAG="${TAG:?用法：REGISTRY=registry地址 TAG=镜像tag ./deploy/online/pull-and-run.sh}"
IMAGE_NAME="${IMAGE_NAME:-thumbelina}"

export THUMBELINA_IMAGE="${REGISTRY}/${IMAGE_NAME}:${TAG}"

echo ">>> 拉取 ${THUMBELINA_IMAGE}"
docker compose pull thumbelina

echo ">>> 启动"
docker compose up -d
docker compose ps
