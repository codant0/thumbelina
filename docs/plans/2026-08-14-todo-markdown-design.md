# TODO 功能设计（基于本地 Markdown 文件）

- **日期**：2026-08-14
- **状态**：已批准
- **分支**：`feat/todo-markdown`

## 1. 需求概述

在当前 Web 前端与 FastAPI 后端中实现独立的 TODO 功能：

1. **TODO list 编辑** — 待办清单的增删改查、完成状态切换
2. **随手记** — 轻量笔记的追加、编辑、删除
3. **存储基于本地 Markdown 文件**，人类可读、可用任意编辑器手工修改

## 2. 已确认的需求决策

| 决策点 | 结论 |
|---|---|
| 文件组织 | 双文件：`TODO/todolist.md` + `TODO/notes.md` |
| 前端交互 | 结构化 UI（用户不接触 Markdown 语法） |
| 随手记能力 | 增、删、改（新条目插入文件顶部） |
| 后端架构 | 方案 A：独立 `todo/` 模块 + REST 路由 |
| 核心约束 | **模块独立、可插拔**，零内部耦合，优雅降级 |

## 3. Markdown 文件格式

### 3.1 `TODO/todolist.md`（兼容项目根目录现有文件）

```markdown
- [ ] 未完成的待办
- [x] 已完成的待办
```

- 逐行解析 `- [ ]` / `- [x]` 复选框行 → `TodoItem(index, text, done)`
- **非复选框行（标题、注释等）原样保留**，写回时不丢失

### 3.2 `TODO/notes.md`（新条目在最上面）

```markdown
## 2026-08-14 21:30
随手记内容，可以多行

## 2026-08-13 09:15
更早的条目
```

- 以 `## YYYY-MM-DD HH:MM` 标题分割条目 → `Note(index, timestamp, content)`
- 新增条目插入文件顶部；首个标题前的自由内容原样保留

### 3.3 条目 ID 策略

Markdown 文件是人类可读的真相源，**不往文件写入 UUID**。ID 即条目序号（index），
每次写操作后后端返回完整最新列表，前端整体刷新，规避 index 漂移。

## 4. API 设计

路由文件 `src/thumbelina/api/routes/todo.py`，命名空间 `/api/v1/todo`。
所有写操作返回最新完整列表。

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/v1/todo/items` | 列出待办 `[{index, text, done}]` |
| `POST` | `/api/v1/todo/items` | 新增待办 `{text}` → 完整列表 |
| `PATCH` | `/api/v1/todo/items/{index}` | 修改 `{text?, done?}` → 完整列表 |
| `DELETE` | `/api/v1/todo/items/{index}` | 删除 → 完整列表 |
| `GET` | `/api/v1/todo/notes` | 列出随手记 `[{index, timestamp, content}]` |
| `POST` | `/api/v1/todo/notes` | 追加随手记 `{content}`（插入顶部）→ 完整列表 |
| `PUT` | `/api/v1/todo/notes/{index}` | 修改条目内容 → 完整列表 |
| `DELETE` | `/api/v1/todo/notes/{index}` | 删除条目 → 完整列表 |
| `GET` | `/api/v1/todo/status` | 模块可用性探测 |

## 5. 独立性与可插拔

1. **零内部耦合**：`todo/` 模块只依赖标准库（pathlib/asyncio/re/dataclasses），
   不 import agent、memory、llm 等内部模块。Agent 初始化失败不影响 TODO 功能。
2. **配置开关**：`AppConfig` 增加 `todo` 配置段：
   ```yaml
   todo:
     enabled: true       # 关闭后路由整体不可用
     directory: TODO     # Markdown 文件目录，相对路径基于工作目录
   ```
3. **优雅降级**：lifespan 中 try/except 初始化 `TodoService`，失败或
   `enabled: false` 时 `app.state.todo_service = None`；路由依赖
   `get_todo_service` 返回 503，服务器照常启动。
4. **并发安全**：`asyncio.Lock` 串行化写操作；"临时文件 + 原子替换"写入，
   避免写坏 Markdown。

## 6. 前端设计

- **导航**：`Header.tsx` 的 `Page` 类型增加 `'todo'`，lucide-react `ListTodo` 图标，
  中英 i18n 键齐全
- **页面**：`components/Todo/TodoPage.tsx`，宽屏左右双栏（左待办/右随手记），
  窄屏上下堆叠；遵循现有设计令牌（teal+orange、BEM 类名）
- **待办面板**：复选框切换完成态、行内文本编辑、删除按钮、输入框 + 添加按钮
- **随手记面板**：输入区 + 追加按钮；时间倒序卡片列表，行内编辑/删除
- **API 客户端**：`api/todo.ts`；503 时显示"TODO 模块未启用"降级提示
- **i18n**：`en.json` / `zh-CN.json` 同步补全

## 7. 测试策略（TDD）

- **后端** `tests/test_todo/`：
  - `test_parser.py` — 复选框行解析/序列化往返、非复选框行保留、notes 分块、
    空/缺文件处理
  - `test_service.py` — tmp_path 夹具下的增删改查、原子写入、并发
  - `test_api.py` — TestClient 端到端 + 503 降级
- **前端**：`api/todo.ts` 客户端单测（vitest + mock fetch）
