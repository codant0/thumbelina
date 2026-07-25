# 日志系统实现计划

**日期**: 2026-07-25  
**设计文档**: [2026-07-25-logging-system-design.md](./2026-07-25-logging-system-design.md)  
**状态**: 待执行

## 概述

根据设计文档，实现 Thumbelina 项目的日志系统补全，包括：
1. 后端使用 loguru 统一日志管理
2. 前端 Vite 日志重定向到文件
3. 支持自动滚动和压缩

## 任务清单

### Task 1: 添加 loguru 依赖

**目标**: 在项目中添加 loguru 依赖

**步骤**:
1. 修改 `pyproject.toml`，在 `dependencies` 中添加 `loguru>=0.7.0`
2. 运行 `pip install -e ".[dev]"` 安装依赖
3. 验证 loguru 可以正常导入

**验收标准**:
- [ ] `pyproject.toml` 中包含 loguru 依赖
- [ ] `python -c "import loguru; print(loguru.__version__)"` 成功执行

**预计时间**: 2 分钟

---

### Task 2: 创建日志初始化模块

**目标**: 实现 `src/thumbelina/logging_config.py`

**步骤**:
1. 创建 `src/thumbelina/logging_config.py` 文件
2. 实现 `InterceptHandler` 类，拦截标准 logging 模块消息
3. 实现 `setup_logging()` 函数，加载配置并初始化 loguru
4. 实现 `get_default_config()` 函数，返回默认配置
5. 编写单元测试 `tests/test_logging/test_logging_config.py`

**验收标准**:
- [ ] `logging_config.py` 文件存在且语法正确
- [ ] `InterceptHandler` 可以拦截标准 logging 消息
- [ ] `setup_logging()` 可以加载配置文件
- [ ] `setup_logging()` 可以使用默认配置（当配置文件不存在时）
- [ ] 所有单元测试通过

**预计时间**: 5 分钟

---

### Task 3: 创建日志配置文件

**目标**: 创建 `logging.yaml` 配置文件

**步骤**:
1. 在项目根目录创建 `logging.yaml` 文件
2. 配置 loguru handlers（控制台和文件）
3. 配置拦截规则（忽略 uvicorn.access）
4. 验证配置文件格式正确

**验收标准**:
- [ ] `logging.yaml` 文件存在且格式正确
- [ ] 配置包含控制台输出 handler
- [ ] 配置包含文件输出 handler（logs/backend.log）
- [ ] 配置包含滚动策略（50MB、30天保留、gzip 压缩）
- [ ] 配置包含拦截规则

**预计时间**: 2 分钟

---

### Task 4: 集成日志系统到应用

**目标**: 在 `create_app()` 中调用 `setup_logging()`

**步骤**:
1. 修改 `src/thumbelina/api/app.py`
2. 在 `create_app()` 函数开头导入并调用 `setup_logging()`
3. 验证日志系统正常工作

**验收标准**:
- [ ] `create_app()` 调用 `setup_logging()`
- [ ] 应用启动时自动创建 `logs/` 目录
- [ ] 后端日志输出到 `logs/backend.log`
- [ ] 现有 38+ 个文件的 `logging.getLogger()` 调用正常工作
- [ ] 应用启动和运行无异常

**预计时间**: 3 分钟

---

### Task 5: 实现前端日志写入器

**目标**: 在 `start_dev.py` 中实现 `RotatingLogWriter`

**步骤**:
1. 修改 `start_dev.py`
2. 添加必要的 import（gzip、shutil、threading、datetime）
3. 实现 `RotatingLogWriter` 类
4. 实现 `_stream_to_log` 函数
5. 修改 `_start_process` 函数，添加 `log_writer` 参数

**验收标准**:
- [ ] `RotatingLogWriter` 类实现完整
- [ ] 支持日志写入和大小滚动
- [ ] 支持 gzip 压缩
- [ ] 支持备份文件管理（保留 10 个）
- [ ] `_stream_to_log` 函数正确实现
- [ ] `_start_process` 函数支持 `log_writer` 参数

**预计时间**: 5 分钟

---

### Task 6: 修改 start_dev.py 主函数

**目标**: 更新 `main()` 函数，使用 `RotatingLogWriter`

**步骤**:
1. 修改 `main()` 函数
2. 创建 `RotatingLogWriter` 实例
3. 更新 `shutdown()` 函数，关闭日志写入器
4. 更新 `_start_process` 调用，传递 `log_writer` 参数
5. 添加日志目录路径提示

**验收标准**:
- [ ] `main()` 函数创建 `RotatingLogWriter` 实例
- [ ] `shutdown()` 函数关闭日志写入器
- [ ] 前端进程使用 `log_writer` 参数
- [ ] 后端进程不使用 `log_writer`（由 loguru 管理）
- [ ] 启动提示包含日志目录路径

**预计时间**: 3 分钟

---

### Task 7: 更新 .gitignore

**目标**: 添加日志目录和文件到 .gitignore

**步骤**:
1. 修改 `.gitignore` 文件
2. 添加 `logs/` 规则
3. 添加 `*.log` 规则
4. 添加 `*.log.gz` 规则

**验收标准**:
- [ ] `.gitignore` 包含 `logs/` 规则
- [ ] `.gitignore` 包含 `*.log` 规则
- [ ] `.gitignore` 包含 `*.log.gz` 规则
- [ ] `git status` 不显示日志文件

**预计时间**: 1 分钟

---

### Task 8: 编写集成测试

**目标**: 验证日志系统整体工作正常

**步骤**:
1. 创建 `tests/test_logging/test_integration.py`
2. 测试后端日志输出到文件
3. 测试日志滚动功能
4. 测试日志压缩功能
5. 运行所有测试

**验收标准**:
- [ ] 集成测试文件存在
- [ ] 测试后端日志输出到 `logs/backend.log`
- [ ] 测试日志滚动（超过 50MB 时）
- [ ] 测试日志压缩（.gz 文件生成）
- [ ] 所有测试通过

**预计时间**: 5 分钟

---

### Task 9: 运行完整测试套件

**目标**: 确保所有现有测试不受影响

**步骤**:
1. 运行 `pytest` 执行所有测试
2. 检查测试结果
3. 修复任何失败的测试

**验收标准**:
- [ ] `pytest` 所有测试通过
- [ ] 没有引入新的测试失败
- [ ] 代码覆盖率没有显著下降

**预计时间**: 3 分钟

---

### Task 10: 代码审查和清理

**目标**: 确保代码质量和一致性

**步骤**:
1. 运行 `ruff check src/ tests/` 检查代码风格
2. 运行 `ruff format src/ tests/` 格式化代码
3. 运行 `mypy src/` 类型检查
4. 修复任何问题
5. 检查文档是否需要更新

**验收标准**:
- [ ] `ruff check` 无错误
- [ ] `ruff format` 代码格式正确
- [ ] `mypy` 类型检查通过
- [ ] 代码风格与项目一致
- [ ] README 或相关文档已更新（如需要）

**预计时间**: 3 分钟

---

### Task 11: 提交代码

**目标**: 提交所有更改

**步骤**:
1. 查看 `git status` 确认所有更改
2. 添加所有文件到暂存区
3. 创建提交，包含清晰的提交信息
4. 推送到远程仓库（可选）

**验收标准**:
- [ ] 所有相关文件已提交
- [ ] 提交信息清晰描述更改
- [ ] 代码已推送到远程仓库（如果需要）

**预计时间**: 2 分钟

---

## 总预计时间

**总计**: 34 分钟（约 0.5 小时）

## 依赖关系

```
Task 1 (添加依赖)
    ↓
Task 2 (创建日志模块)
    ↓
Task 3 (创建配置文件)
    ↓
Task 4 (集成到应用)
    ↓
Task 5 (实现前端日志写入器)
    ↓
Task 6 (修改 start_dev.py)
    ↓
Task 7 (更新 .gitignore)
    ↓
Task 8 (编写集成测试)
    ↓
Task 9 (运行完整测试套件)
    ↓
Task 10 (代码审查和清理)
    ↓
Task 11 (提交代码)
```

## 风险和注意事项

1. **依赖冲突**: loguru 可能与现有依赖冲突，需要检查兼容性
2. **文件权限**: 确保应用有权限创建和写入 `logs/` 目录
3. **磁盘空间**: 日志文件会占用磁盘空间，需要监控
4. **性能影响**: 日志写入可能影响应用性能，需要测试
5. **现有测试**: 确保新日志系统不影响现有测试

## 执行模式

请选择执行模式：

### 选项 A: Subagent-driven（推荐）

使用子代理自动执行每个任务，包括：
- 实现子代理：执行代码编写和测试
- 规范审查子代理：验证代码符合设计规范
- 代码质量审查子代理：检查代码质量和风格

**优点**:
- 自动化程度高
- 包含自动审查
- 适合复杂任务

### 选项 B: 手动执行

手动执行每个任务，适合：
- 需要更多控制
- 学习和理解代码
- 调试特定问题

**优点**:
- 更灵活
- 更好的学习机会
- 可以随时调整

## 下一步

请告诉我你希望使用哪种执行模式，我将开始执行任务。
