"""日志配置模块 - 使用 loguru 统一日志管理。

提供标准 logging 模块到 loguru 的桥接，支持从 YAML 配置文件加载日志策略。
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

import yaml
from loguru import logger


class InterceptHandler(logging.Handler):
    """拦截标准 logging 模块的消息，转发给 loguru。

    该处理器替换标准 logging 的 handler，将所有通过 ``logging.getLogger()``
    记录的消息透明地转发到 loguru，从而实现零侵入的统一日志管理。
    """

    def emit(self, record: logging.LogRecord) -> None:
        """将一条标准 logging 日志记录转发给 loguru。

        Parameters
        ----------
        record : logging.LogRecord
            标准 logging 模块的日志记录。
        """
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # 向上查找调用栈，跳过 logging 和本模块的帧
        frame = logging.currentframe()
        depth = 2
        while frame is not None and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back  # type: ignore[assignment]
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def setup_logging(config_path: str = "logging.yaml") -> None:
    """加载日志配置并初始化 loguru。

    如果指定的配置文件不存在，自动使用 :func:`get_default_config` 提供的
    默认配置。初始化过程会：

    1. 确保 ``logs/`` 目录存在
    2. 清除 loguru 的默认 handler
    3. 根据配置添加控制台和文件 handler
    4. 将标准 logging 模块的消息拦截并转发给 loguru

    Parameters
    ----------
    config_path : str
        日志配置文件路径，默认为项目根目录下的 ``logging.yaml``。
    """
    config_file = Path(config_path)

    # 加载配置文件，不存在时使用默认配置
    if config_file.exists():
        with open(config_file, encoding="utf-8") as f:
            config: dict[str, Any] = yaml.safe_load(f)
    else:
        config = get_default_config()

    # 确保 logs 目录存在
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    # 确保 stderr 使用 UTF-8（Windows 下默认为 GBK，中文会乱码）
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    # 清除 loguru 默认 handler
    logger.remove()

    # 配置 loguru handlers
    for handler in config.get("loguru", {}).get("handlers", []):
        handler_copy = handler.copy()
        sink = handler_copy.pop("sink")

        # 将 stderr / stdout 字符串映射到 sys 对象
        if isinstance(sink, str):
            if sink == "stderr":
                sink = sys.stderr
            elif sink == "stdout":
                sink = sys.stdout

        logger.add(sink, **handler_copy)

    # 拦截标准 logging 模块
    intercept_config = config.get("intercept", {})
    ignore_loggers: list[str] = intercept_config.get("ignore", [])

    # 配置根 logger
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)

    # 拦截所有已存在的 logger
    for name in logging.root.manager.loggerDict:
        if name not in ignore_loggers:
            logging.getLogger(name).handlers = [InterceptHandler()]
            logging.getLogger(name).propagate = False


def get_default_config() -> dict[str, Any]:
    """返回默认配置（当 ``logging.yaml`` 不存在时使用）。

    默认配置包含：

    - **控制台 handler**: 输出到 stderr，INFO 级别，彩色格式
    - **文件 handler**: 输出到 ``logs/backend.log``，DEBUG 级别，
      50 MB 滚动、30 天保留、gzip 压缩

    Returns
    -------
    dict[str, Any]
        默认日志配置字典。
    """
    return {
        "loguru": {
            "handlers": [
                {
                    "sink": "stderr",
                    "level": "INFO",
                    "format": (
                        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
                        "<level>{level: <8}</level> | "
                        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:"
                        "<cyan>{line}</cyan> - <level>{message}</level>"
                    ),
                    "colorize": True,
                },
                {
                    "sink": "logs/backend.log",
                    "level": "DEBUG",
                    "format": (
                        "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
                        "{level: <8} | "
                        "{name}:{function}:{line} - {message}"
                    ),
                    "rotation": "50 MB",
                    "retention": "30 days",
                    "compression": "gz",
                    "encoding": "utf-8",
                },
            ]
        },
        "intercept": {
            "loggers": ["*"],
            "ignore": ["uvicorn.access"],
        },
    }
