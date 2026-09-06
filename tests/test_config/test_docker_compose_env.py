"""docker-compose 部署回归:附件目录必须落在持久卷内。

背景:``repository.attachments_directory`` 为相对路径时按容器内工作
目录解析(Dockerfile WORKDIR /app),漏配
``THUMBELINA_REPOSITORY__ATTACHMENTS_DIRECTORY`` 时图片落到
/app/attachments(不在卷里)—— 容器重建后数据库附件记录还在、
图片字节全部丢失,历史消息坏链不可恢复。

``docker-compose.nas.yml`` 是不入库的本地部署配置(.gitignore,
"数据路径等因人而异"),存在时一并校验,不存在(如 CI/新克隆)则跳过。
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
TRACKED_COMPOSE_FILES = ("docker-compose.yml",)
LOCAL_NAS_COMPOSE = "docker-compose.nas.yml"
ATTACHMENTS_ENV_KEY = "THUMBELINA_REPOSITORY__ATTACHMENTS_DIRECTORY"
PERSISTENT_VOLUME_PATH = "/app/data/attachments"


def _compose_targets() -> list[Path]:
    targets = [REPO_ROOT / name for name in TRACKED_COMPOSE_FILES]
    nas_compose = REPO_ROOT / LOCAL_NAS_COMPOSE
    if nas_compose.exists():
        targets.append(nas_compose)
    return targets


def _env_mapping(compose_file: Path) -> dict[str, str]:
    """把 compose 的 environment 列表(["KEY=VALUE", …])解析成 dict。"""
    data = yaml.safe_load(compose_file.read_text(encoding="utf-8"))
    entries = data["services"]["thumbelina"]["environment"]
    mapping: dict[str, str] = {}
    for entry in entries:
        key, _, value = str(entry).partition("=")
        mapping[key] = value
    return mapping


def test_attachments_directory_env_points_into_persistent_volume():
    """compose 文件必须把附件目录固定到 /app/data 持久卷。"""
    for compose_file in _compose_targets():
        env = _env_mapping(compose_file)
        assert env.get(ATTACHMENTS_ENV_KEY) == PERSISTENT_VOLUME_PATH, (
            f"{compose_file.name} 缺少 "
            f"{ATTACHMENTS_ENV_KEY}={PERSISTENT_VOLUME_PATH}:"
            "附件目录不在持久卷内,容器重建后用户上传图片永久丢失"
        )


def test_compose_files_still_parse():
    """compose 文件保持合法 YAML(service/environment 结构未破坏)。"""
    for compose_file in _compose_targets():
        data = yaml.safe_load(compose_file.read_text(encoding="utf-8"))
        assert "thumbelina" in data["services"]
        assert isinstance(data["services"]["thumbelina"]["environment"], list)
