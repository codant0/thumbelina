#!/usr/bin/env bash
#
# 版本号工具（供 deploy 下脚本 source 复用）：
#   版本号为 vX.Y.Z 三部分；自动递增仅末位 +1（v0.0.1 → v0.0.2）。
#   当前版本保存在仓库根目录 VERSION 文件。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERSION_FILE="${VERSION_FILE:-$(cd "${SCRIPT_DIR}/../.." && pwd)/VERSION}"

# 校验并规范化版本号：缺 v 前缀自动补，格式非法返回 1
version_normalize() {
  local v="$1"
  [[ "${v}" == v* ]] || v="v${v}"
  if [[ ! "${v}" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "错误：无效版本号 '${1}'，应为 vX.Y.Z（如 v0.0.1）" >&2
    return 1
  fi
  echo "${v}"
}

# 读取当前版本（不递增）
version_current() {
  if [[ ! -f "${VERSION_FILE}" ]]; then
    echo "错误：缺少版本文件 ${VERSION_FILE}" >&2
    return 1
  fi
  version_normalize "$(cat "${VERSION_FILE}")"
}

# 读取当前版本，末位 +1 回写 VERSION 文件，输出新版本号
version_autobump() {
  local current major minor patch next
  if [[ -f "${VERSION_FILE}" ]]; then
    current="$(version_normalize "$(cat "${VERSION_FILE}")")" || return 1
  else
    current="v0.0.1"
    echo ">>> 未找到 ${VERSION_FILE}，从 v0.0.1 开始" >&2
  fi
  IFS=. read -r major minor patch <<< "${current#v}"
  next="v${major}.${minor}.$((patch + 1))"
  echo "${next}" > "${VERSION_FILE}"
  echo ">>> 版本自动递增：${current} → ${next}（已回写 VERSION 文件，记得提交）" >&2
  echo "${next}"
}