# 日志系统设计文档

**日期**: 2026-07-25  
**状态**: 设计完成，待实现  
**作者**: Claude Code

## 概述

为 Thumbelina 项目补全日志能力，实现前后端日志统一输出到 `logs/` 目录，支持自动滚动和压缩。

## 设计目标

1. **统一日志目录**: 所有日志输出到 `logs/` 目录，按前后端分开存储
2. **自动滚动**: 支持基于文件大小和时间的双重滚动条件
3. **自动压缩**: 滚动后的日志文件自动压缩为 `.gz` 格式
4. **零侵入**: 现有 38+ 个文件的 `logging.getLogger(__name__)` 无需修改
5. **可配置**: 通过独立的 `logging.yaml` 配置文件管理日志策略

## 架构设计

### 目录结构

```
thumbelina/
├── logs/                              # 日志目录（.gitignore 忽略）
│   ├── backend.log                    # 后端当前日志
│   ├── backend.2026-07-24.log.gz     # 滚动压缩的后端日志
│   ├── frontend.log                   # Vite 服务器当前日志
│   └── frontend.2026-07-24.log.gz    # 滚动压缩的前端日志
├── logging.yaml                       # 日志配置文件
├── src/thumbelina/
│   ├── logging_config.py             # 日志初始化模块
│   └── ...
└── start_dev.py                       # 修改：Vite 日志重定向
```

### 技术选型

| 组件 | 技术方案 | 理由 |
|------|---------|------|
| 后端日志库 | **loguru** | 原生支持大小+时间双条件滚动、自动压缩、优雅的 API |
| 标准 logging 兼容 | **InterceptHandler** | 拦截标准 logging 模块消息，转发给 loguru |
| 前端日志 | **自定义 RotatingLogWriter** | Vite 是 Node.js 进程，用 Python 实现日志写入和滚动 |
| 配置管理 | **独立 logging.yaml** | 与应用配置解耦，更灵活的日志策略管理 |

## 详细设计

### 1. 后端日志系统

#### 1.1 配置文件 (`logging.yaml`)

```yaml
version: 1
disable_existing_loggers: false

# loguru 配置
loguru:
  handlers:
    # 控制台输出（保留彩色）
    - sink: stderr
      level: INFO
      format: "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
      colorize: true

    # 后端文件日志（大小+时间双条件滚动）
    - sink: logs/backend.log
      level: DEBUG
      format: "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}"
      rotation: "50 MB"          # 文件超过 50MB 时滚动
      retention: "30 days"       # 保留 30 天的日志
      compression: "gz"          # 滚动后压缩为 .gz
      encoding: utf-8

# 标准 logging 拦截配置
intercept:
  loggers: ["*"]                  # 拦截所有 logger
  ignore: ["uvicorn.access"]      # 不拦截 uvicorn 访问日志
```

#### 1.2 日志初始化模块 (`src/thumbelina/logging_config.py`)

```python
"""日志配置模块 - 使用 loguru 统一日志管理"""
import sys
import logging
from pathlib import Path
from loguru import logger
import yaml


class InterceptHandler(logging.Handler):
    """拦截标准 logging 模块的消息，转发给 loguru"""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def setup_logging(config_path: str = "logging.yaml") -> None:
    """加载日志配置并初始化 loguru

    Parameters
    ----------
    config_path : str
        日志配置文件路径，默认为项目根目录下的 logging.yaml
    """
    config_file = Path(config_path)

    # 加载配置文件，不存在时使用默认配置
    if config_file.exists():
        with open(config_file, encoding="utf-8") as f:
            config = yaml.safe_load(f)
    else:
        config = get_default_config()

    # 确保 logs 目录存在
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    # 清除 loguru 默认 handler
    logger.remove()

    # 配置 loguru handlers
    for handler in config.get("loguru", {}).get("handlers", []):
        handler_copy = handler.copy()
        sink = handler_copy.pop("sink")

        # 将路径字符串转换为 Path 对象
        if isinstance(sink, str) and not sink.startswith("<"):
            sink = Path(sink)

        logger.add(sink, **handler_copy)

    # 拦截标准 logging 模块
    intercept_config = config.get("intercept", {})
    ignore_loggers = intercept_config.get("ignore", [])

    # 配置根 logger
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)

    # 拦截所有已存在的 logger
    for name in logging.root.manager.loggerDict:
        if name not in ignore_loggers:
            logging.getLogger(name).handlers = [InterceptHandler()]
            logging.getLogger(name).propagate = False


def get_default_config() -> dict:
    """返回默认配置（当 logging.yaml 不存在时使用）

    Returns
    -------
    dict
        默认日志配置字典
    """
    return {
        "loguru": {
            "handlers": [
                {
                    "sink": "stderr",
                    "level": "INFO",
                    "format": "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
                    "colorize": True,
                },
                {
                    "sink": "logs/backend.log",
                    "level": "DEBUG",
                    "format": "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
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
```

#### 1.3 集成点

在 `src/thumbelina/api/app.py` 的 `create_app()` 函数中调用：

```python
from thumbelina.logging_config import setup_logging

def create_app(config: AppConfig | None = None) -> FastAPI:
    # 初始化日志系统（必须在其他模块导入之前）
    setup_logging()

    # ... 其他代码保持不变 ...
```

### 2. 前端日志系统

#### 2.1 修改 `start_dev.py`

添加 `RotatingLogWriter` 类，实现：
- 大小滚动：文件超过 50MB 时自动滚动
- 自动压缩：滚动后的日志压缩为 `.gz` 格式
- 备份管理：保留最近 10 个备份
- 双重输出：同时写入文件和终端

```python
class RotatingLogWriter:
    """带大小滚动和压缩的日志写入器"""

    def __init__(self, log_path: Path, max_size: int = 50 * 1024 * 1024,
                 backup_count: int = 10):
        self.log_path = log_path
        self.max_size = max_size
        self.backup_count = backup_count
        self._file = None
        self._current_size = 0
        self._lock = threading.Lock()
        self._open_file()

    def _open_file(self):
        """打开日志文件"""
        self._file = open(self.log_path, "a", encoding="utf-8")
        self._current_size = self.log_path.stat().st_size if self.log_path.exists() else 0

    def _rotate(self):
        """滚动日志文件并压缩旧文件"""
        if self._file:
            self._file.close()

        # 删除最旧的备份（如果超过备份数量）
        for i in range(self.backup_count, 0, -1):
            src = self.log_path.with_suffix(f".{i}.log.gz")
            if src.exists():
                if i == self.backup_count:
                    src.unlink()
                else:
                    dst = self.log_path.with_suffix(f".{i + 1}.log.gz")
                    src.rename(dst)

        # 压缩当前日志
        compressed_path = self.log_path.with_suffix(".1.log.gz")
        with open(self.log_path, "rb") as f_in:
            with gzip.open(compressed_path, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)

        # 清空当前日志文件
        self._file = open(self.log_path, "w", encoding="utf-8")
        self._current_size = 0

    def write(self, data: str):
        """写入日志，必要时滚动"""
        with self._lock:
            self._file.write(data)
            self._file.flush()
            self._current_size += len(data.encode("utf-8"))

            if self._current_size >= self.max_size:
                self._rotate()

    def close(self):
        """关闭日志文件"""
        with self._lock:
            if self._file:
                self._file.close()
                self._file = None
```

#### 2.2 修改 `_start_process` 函数

添加 `log_writer` 参数，支持日志重定向：

```python
def _start_process(name: str, cmd: list[str], cwd: str, procs, buffers, threads,
                   log_writer: RotatingLogWriter = None):
    """启动子进程，输出重定向到日志文件"""
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    procs[name] = proc
    buffers[name] = []

    if log_writer:
        t = threading.Thread(
            target=_stream_to_log,
            args=(proc.stdout, name, log_writer, buffers[name]),
            daemon=True,
        )
    else:
        # 后端日志由 loguru 管理，这里只捕获不写文件
        t = threading.Thread(
            target=_stream_and_capture,
            args=(proc.stdout, name, buffers[name]),
            daemon=True,
        )
    t.start()
    threads.append(t)
```

#### 2.3 更新 `main()` 函数

```python
def main():
    root = Path(__file__).resolve().parent
    frontend = root / "frontend"

    # 确保 logs 目录存在
    LOG_DIR = Path("logs")
    LOG_DIR.mkdir(exist_ok=True)

    # 创建前端日志写入器
    frontend_log_writer = RotatingLogWriter(LOG_DIR / "frontend.log")

    procs: dict[str, subprocess.Popen] = {}
    output_buffers: dict[str, list[str]] = {}
    threads: list[threading.Thread] = []

    def shutdown(*_):
        # ... 现有代码 ...

        # 关闭日志写入器
        frontend_log_writer.close()

        # ... 其他清理代码 ...

    # 1. Start backend（不重定向，由 loguru 管理）
    _start_process(
        "backend",
        [...],
        str(root), procs, output_buffers, threads,
        log_writer=None,  # 后端日志由 loguru 管理
    )

    # 2. Start frontend（带日志重定向）
    _start_process(
        "frontend",
        [...],
        str(frontend), procs, output_buffers, threads,
        log_writer=frontend_log_writer,  # 前端日志写入文件
    )

    # ... 其他代码 ...
```

### 3. 配置更新

#### 3.1 更新 `.gitignore`

在文件末尾添加：

```gitignore
# 日志文件
logs/
*.log
*.log.gz
```

#### 3.2 添加 loguru 依赖

在 `pyproject.toml` 中添加：

```toml
dependencies = [
    # ... 现有依赖 ...
    "loguru>=0.7.0",
]
```

## 日志滚动策略

### 后端日志 (loguru)

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `rotation` | `"50 MB"` | 文件超过 50MB 时滚动 |
| `retention` | `"30 days"` | 保留 30 天的日志 |
| `compression` | `"gz"` | 滚动后压缩为 .gz 格式 |

loguru 支持同时指定多个滚动条件，例如：
- `"50 MB"` - 仅基于大小
- `"1 day"` - 仅基于时间
- `["50 MB", "1 day"]` - 任一条件满足时滚动

### 前端日志 (RotatingLogWriter)

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `max_size` | 50MB | 文件超过 50MB 时滚动 |
| `backup_count` | 10 | 保留最近 10 个备份 |
| `compression` | gzip | 滚动后压缩为 .gz 格式 |

## 日志格式

### 后端日志

**控制台输出（彩色）：**
```
2026-07-25 10:30:45 | INFO     | thumbelina.api.app:lifespan:206 - Application started
```

**文件输出：**
```
2026-07-25 10:30:45.123 | INFO     | thumbelina.api.app:lifespan:206 - Application started
```

### 前端日志

```
[2026-07-25 10:30:45] [frontend]   VITE v5.0.0  ready in 300 ms
```

## 依赖项

### Python 依赖

- `loguru>=0.7.0` - 日志库

### 标准库依赖

- `logging` - 标准日志模块（通过 InterceptHandler 兼容）
- `yaml` - YAML 配置文件解析
- `gzip` - 日志压缩
- `shutil` - 文件操作
- `threading` - 线程安全

## 测试策略

### 单元测试

1. **logging_config.py 测试**
   - 测试 `setup_logging()` 函数
   - 测试 `InterceptHandler` 拦截标准 logging 消息
   - 测试配置文件加载和默认配置

2. **RotatingLogWriter 测试**
   - 测试日志写入
   - 测试大小滚动触发
   - 测试压缩功能
   - 测试备份文件管理

### 集成测试

1. **后端日志集成**
   - 验证 loguru 拦截所有标准 logging 消息
   - 验证日志文件创建和滚动
   - 验证日志格式正确

2. **前端日志集成**
   - 验证 Vite 输出重定向到日志文件
   - 验证日志文件滚动和压缩

## 实施步骤

1. **添加依赖**: 更新 `pyproject.toml`，添加 loguru
2. **创建日志模块**: 实现 `logging_config.py`
3. **创建配置文件**: 创建 `logging.yaml`
4. **集成到应用**: 修改 `create_app()` 调用 `setup_logging()`
5. **修改 start_dev.py**: 实现 `RotatingLogWriter`，修改 `_start_process` 和 `main()`
6. **更新 .gitignore**: 添加日志目录和文件忽略规则
7. **编写测试**: 添加单元测试和集成测试
8. **文档更新**: 更新 README 和相关文档

## 注意事项

1. **日志目录创建**: `setup_logging()` 和 `start_dev.py` 都会自动创建 `logs/` 目录
2. **文件编码**: 所有日志文件使用 UTF-8 编码
3. **线程安全**: `RotatingLogWriter` 使用锁保证线程安全
4. **性能影响**: loguru 的性能开销很小，不会影响应用性能
5. **磁盘空间**: 日志文件会占用磁盘空间，建议定期清理或调整保留策略
6. **uvicorn 访问日志**: 默认不拦截 `uvicorn.access`，避免重复记录 HTTP 请求

## 扩展性

### 未来扩展

1. **日志级别动态调整**: 通过 API 动态修改日志级别
2. **远程日志**: 支持发送日志到远程日志服务（如 ELK、Loki）
3. **结构化日志**: 使用 JSON 格式输出日志，便于日志分析
4. **日志告警**: 基于日志内容触发告警通知
5. **日志查询 API**: 提供 API 查询和过滤日志

### 配置示例

**按时间和大小同时滚动：**
```yaml
loguru:
  handlers:
    - sink: logs/backend.log
      rotation: ["50 MB", "00:00"]  # 50MB 或每天午夜滚动
      retention: "30 days"
      compression: "gz"
```

**JSON 格式日志：**
```yaml
loguru:
  handlers:
    - sink: logs/backend.json
      format: "{time:YYYY-MM-DDTHH:mm:ss.SSS} | {level} | {name}:{function}:{line} | {message}"
      serialize: true  # 输出为 JSON
```

## 参考资料

- [loguru 官方文档](https://loguru.readthedocs.io/)
- [Python logging 模块文档](https://docs.python.org/3/library/logging.html)
- [loguru 配置示例](https://loguru.readthedocs.io/en/stable/overview.html#essential-example)
