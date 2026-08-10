# RAG 异步上传与可视化进度 — 设计文档

- **日期**: 2026-08-06
- **分支**: `feat/rag-async-upload-progress`
- **状态**: 已批准

## 1. 背景与问题

当前 RAG 三种上传入口（单文件、URL、批量/文件夹）均为**请求内同步阻塞**：

- `POST /api/v1/rag/knowledge-bases/{kb_id}/documents`（单文件）
- `POST /api/v1/rag/knowledge-bases/{kb_id}/documents/url`（URL 抓取）
- `POST /api/v1/rag/knowledge-bases/{kb_id}/documents/batch`（批量）

整个索引流水线（加载 → 文档去重 → 分块 → 向量化 → 写入向量库）在单个 HTTP 请求内通过
`asyncio.to_thread` 执行完毕后才返回。大文件（如大型 PDF + 本地 HF embedding 模型）可能耗时
数十秒至数分钟，期间：

1. HTTP 客户端/反向代理可能超时；
2. 前端只能显示 spinner，批量上传进度条从 0% 直接跳 100%，无真实进度反馈；
3. 用户无法取消一个失控的长任务。

## 2. 目标

- 三种上传入口全部改为**提交后台任务，立即返回 `task_id`（HTTP 202）**。
- 前端通过**轮询**获取任务进度，展示**阶段 + 分块级**的可视化进度。
- 支持**取消**任务（协作式）。
- 任务状态**纯内存**保存（YAGNI：上传任务不可断点续传，重启后无需恢复）。

## 3. 已确认的关键决策

| 决策点 | 结论 |
|---|---|
| 进度传递机制 | HTTP 轮询（1s 间隔，单一列表端点） |
| 进度粒度 | 阶段（解析/分块/向量化/入库）+ 分块批级（embedding 分批回调） |
| 改造范围 | 单文件、URL、批量三种入口全部异步化 |
| 任务存储 | 纯内存（进程内 dict + 锁，保留最近 50 条已完成任务） |
| 并发策略 | `asyncio.Semaphore(1)` 串行执行索引任务，多任务排队（pending） |

## 4. 架构设计

### 4.1 任务管理器 — `src/thumbelina/rag/pipeline/upload_tasks.py`（新模块）

```python
@dataclass
class UploadTask:
    id: str                       # uuid hex
    kb_id: str
    kind: str                     # "file" | "url" | "batch"
    status: str                   # "pending" | "running" | "completed" | "failed" | "cancelled"
    stage: str                    # "queued" | "saving" | "loading" | "chunking" |
                                  # "embedding" | "storing" | "done"
    total_files: int = 0
    done_files: int = 0
    current_file: str = ""
    chunk_done: int = 0           # 当前文件已向量化分块数
    chunk_total: int = 0          # 当前文件总分块数
    error: str | None = None
    result: dict | None = None    # {"uploaded": [...], "skipped": [...], "errors": [...]}
    created_at: datetime
    cancel_event: threading.Event # 协作式取消标志

class UploadTaskManager:
    def create(kb_id, kind, ...) -> UploadTask
    def get(task_id) -> UploadTask | None
    def list_by_kb(kb_id) -> list[UploadTask]
    def cancel(task_id) -> bool
    async def run(task, coro_factory) -> None   # 信号量排队 + 线程执行 + 生命周期收尾
```

要点：

- 状态保存在内存 dict 中，所有读写经 `threading.Lock` 保护（进度回调在工作线程中触发）。
- 进度回调由 Indexer 在工作线程中调用 → 直接加锁更新任务字段；轮询端点在事件循环中读取，
  无需跨线程调度。
- `Semaphore(1)`：embedding 为 CPU 密集且共享模型实例，串行执行最可预测；排队任务
  status=pending、stage=queued。
- 已完成/失败/取消任务保留最近 50 条，超出自动淘汰（FIFO）。
- 挂载点：`app.state.rag_upload_tasks`（RAG 初始化成功时创建，遵循既有 try/except 优雅降级）。

### 4.2 Indexer 进度回调 — `src/thumbelina/rag/pipeline/indexer.py` 改造

- `index()` / `index_batch()` 新增可选参数：

  ```python
  progress_cb: Callable[[ProgressEvent], None] | None = None
  cancel_event: threading.Event | None = None
  ```

- 新数据类 `ProgressEvent(stage, file_index, total_files, chunk_done, chunk_total, filename)`。
- `_embed_and_store` 将 texts 按 **每批 32 条** 切分循环调用 `embed_batch` + `vector_store.add`，
  每批回调一次 `embedding` 进度（`chunk_done` 累加）——向量化是耗时主体，分批后进度条平滑真实。
- 流水线各阶段入口回调对应 stage：loading / chunking / embedding / storing。
- 每批循环边界检查 `cancel_event.is_set()` → 抛出 `IndexCancelledError`；
  `index()` 外层捕获并中止，由任务管理器标记 `cancelled`。
- `progress_cb=None` 时行为与现状完全一致（向后兼容，CLI/其他调用方不受影响）。

### 4.3 API 契约 — `src/thumbelina/api/routes/rag.py` 改造

| 端点 | 变化 | 响应 |
|---|---|---|
| `POST /rag/knowledge-bases/{kb_id}/documents` | 同步 → 异步 | **202** `{"task_id": str}` |
| `POST /rag/knowledge-bases/{kb_id}/documents/batch` | 同步 → 异步 | **202** `{"task_id": str}` |
| `POST /rag/knowledge-bases/{kb_id}/documents/url` | 同步 → 异步 | **202** `{"task_id": str}` |
| `GET /rag/upload-tasks/{task_id}` | **新增** | 任务详情（全部进度字段 + result） |
| `GET /rag/knowledge-bases/{kb_id}/upload-tasks` | **新增** | 该 KB 的任务列表（轮询端点；刷新页面后恢复展示） |
| `DELETE /rag/upload-tasks/{task_id}` | **新增** | 取消任务 `{"cancelled": true}` |

任务详情响应模型：

```json
{
  "id": "…", "kb_id": "…", "kind": "batch",
  "status": "running", "stage": "embedding",
  "total_files": 12, "done_files": 4,
  "current_file": "report.pdf",
  "chunk_done": 48, "chunk_total": 320,
  "error": null, "result": null,
  "created_at": "2026-08-06T12:00:00"
}
```

执行流程（以文件上传为例）：

1. 校验 KB 存在、文件类型；
2. 文件流式落盘临时目录 `/tmp_file`（复用现有逻辑）；
3. 创建任务（status=pending），`asyncio.create_task(manager.run(...))`；
4. 立即返回 202 + `task_id`；
5. 后台：获取信号量 → status=running → `to_thread(indexer.index_batch, paths, progress_cb, cancel_event)`
   → 成功则写 document 元数据、status=completed、填充 result；失败 status=failed + error；
   无论成败 finally 清理临时文件。

### 4.4 前端 API 客户端与轮询 hook

- `frontend/src/api/rag.ts`：
  - 新增 `createFileUploadTask(kbId, files)`、`createUrlUploadTask(kbId, url)`、
    `listUploadTasks(kbId)`、`getUploadTask(taskId)`、`cancelUploadTask(taskId)`；
  - 删除旧同步 `uploadDocument / uploadDocumentsBatch / uploadDocumentByUrl`。
- `frontend/src/types/rag.ts`：新增 `UploadTask`、`UploadTaskCreateResponse` 类型。
- 新 hook `frontend/src/hooks/useUploadTasks.ts`：
  - 维护 `tasks: UploadTask[]` 状态；
  - 存在活跃任务（pending/running）时以 1s 间隔轮询 `listUploadTasks(kbId)`（单一请求）；
    无活跃任务时停止轮询；
  - 提交上传后立即触发一次轮询；
  - 任务从活跃转为终态时回调 `onSettled` → 刷新文档列表与知识库统计。

### 4.5 前端进度 UI — `KnowledgeBasePage.tsx`

移除现有静态 `batchProgress` / `batchUploading` 逻辑，三种上传统一走任务系统。
上传区下方渲染任务卡片列表：

```
┌────────────────────────────────────────────────┐
│ 📄 report.pdf 等 12 个文件        [处理中]  [✕] │
│ ▰▰▰▰▰▰▱▱▱▱  5/12 文件 · 向量化 48/320 分块      │
├────────────────────────────────────────────────┤
│ 🔗 https://example.com/a          [排队中]  [✕] │
├────────────────────────────────────────────────┤
│ ✅ notes.md · 24 分块                  [已完成] │
│ ❌ big.pdf — 加载失败: 文件损坏          [失败]   │
└────────────────────────────────────────────────┘
```

- 状态徽章：排队中 / 处理中 / 已完成 / 失败（附错误详情）/ 已取消；
- 进度条百分比 = 综合文件进度与分块进度（running 文件内部按 chunk_done/chunk_total 插值）；
- 活跃任务显示取消按钮；终态任务（completed/failed/cancelled）可手动关闭移除；
- 样式遵循设计令牌：BEM 类名 `kb-upload-task__*`、teal/orange 主题、lucide-react 图标；
- i18n 条目同步加入 `locales/en.json` 与 `locales/zh-CN.json`。

### 4.6 测试计划（TDD）

后端：

- `tests/test_rag/test_pipeline/test_upload_tasks.py`（新）：
  创建/查询/按 KB 列表/取消/50 条淘汰/信号量排队。
- `tests/test_rag/test_pipeline/test_indexer.py`（扩展）：
  progress_cb 阶段序列、embedding 分批计数、cancel_event 中断、无回调时行为不变。
- `tests/test_api/test_rag.py`（扩展）：
  三上传端点返回 202 + task_id；任务状态端点 pending→completed；失败路径；取消端点。

前端（vitest）：

- `useUploadTasks` hook：轮询启停、任务更新、终态回调（mock fetch + fake timers）；
- `KnowledgeBasePage`：任务卡片渲染与状态徽章、取消按钮交互。

## 5. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 服务器重启丢失内存任务记录 | 已接受（纯内存决策）；已入库文档不受影响，前端刷新后仅丢失进度展示 |
| 多任务并发写同一 ChromaDB store 冲突 | Semaphore(1) 串行执行，天然规避 |
| 前端关闭页面后任务"失联" | 任务列表端点按 KB 查询，重新打开页面即恢复展示 |
| 临时文件泄漏 | 任务执行 finally 块清理；启动时可选清理残留（沿用现状，不扩大范围） |

## 6. 不做的事（YAGNI）

- 不做任务数据库持久化 / 上传历史审计；
- 不做断点续传；
- 不做 WebSocket/SSE 推送（轮询已满足需求）;
- 不改动 Indexer 以外的 RAG 流水线组件（loader/chunker/embedder 接口不变）。
