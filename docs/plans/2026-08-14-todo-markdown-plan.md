# TODO 功能实现计划（基于本地 Markdown 文件）

- **设计文档**：`docs/plans/2026-08-14-todo-markdown-design.md`
- **分支**：`feat/todo-markdown`
- **执行方式**：TDD —— 每个任务先写失败测试，再实现，绿后提交
- **验证命令**：
  - 后端：`pytest tests/test_todo/ tests/test_api/test_todo.py -x -q`、`ruff check src/ tests/`、`ruff format src/ tests/`、`mypy src/thumbelina/todo/ src/thumbelina/api/routes/todo.py`
  - 前端：`cd frontend && npm run test`、`npm run lint`、`npm run build`

**硬性约束**：
1. `src/thumbelina/todo/` 只允许 import 标准库，禁止 import 项目内其他模块（可插拔）
2. Markdown 文件是真相源：任何写操作 = 读文件 → 修改内存结构 → 整体序列化回写
3. 写回文件用"临时文件 + `os.replace` 原子替换"，全程持 `asyncio.Lock`
4. 非复选框行（todolist.md）与首个 `##` 标题前的内容（notes.md）必须原样保留
5. 每个任务完成后单独 commit（conventional commits，中文描述）

---

## Task 1：数据模型与 Markdown 解析器（TDD）

**文件**：
- 测试：`tests/test_todo/__init__.py`、`tests/test_todo/test_parser.py`
- 实现：`src/thumbelina/todo/__init__.py`、`src/thumbelina/todo/models.py`、`src/thumbelina/todo/parser.py`

### 1.1 先写测试 `tests/test_todo/test_parser.py`

覆盖用例：
- `test_parse_todolist_checkbox_lines`：`"- [ ] 买牛奶"` / `"- [x] 写周报"` / `"- [X] 大写也可"` → 正确 text/done
- `test_parse_todolist_preserves_raw_lines`：混入标题 `# 标题` 与空行，解析结果按原顺序产出 segments（RawLine 与 TodoItem 交替），序列化后与原文一致（往返测试）
- `test_parse_todolist_empty`：空字符串 → 空列表
- `test_todo_item_index`：TodoItem.index 只统计复选框行，从 0 递增（raw 行不占 index）
- `test_parse_notes_blocks`：两个 `## 2026-08-14 21:30` 标题块 → 2 个 Note，content 正确去除块尾空行
- `test_parse_notes_preamble`：首个 `##` 之前的内容作为 preamble 返回，序列化后仍在文件顶部
- `test_parse_notes_empty`：空字符串 → preamble 为 ""，notes 为空
- `test_serialize_notes_round_trip`：preamble + notes 序列化 → 再解析，结构不变

运行：`pytest tests/test_todo/test_parser.py -x -q` → **应失败**（模块不存在）

### 1.2 实现

`models.py`：
```python
@dataclass
class TodoItem:
    index: int
    text: str
    done: bool

@dataclass
class RawLine:          # todolist.md 中的非复选框行，原样保留
    text: str

@dataclass
class Note:
    index: int
    timestamp: str      # "YYYY-MM-DD HH:MM"
    content: str
```

`parser.py`：
```python
CHECKBOX_RE = re.compile(r"^- \[( |x|X)\] (.*)$")
NOTE_HEADER_RE = re.compile(r"^## (\d{4}-\d{2}-\d{2} \d{2}:\d{2})\s*$")

def parse_todolist(text: str) -> list[TodoItem | RawLine]: ...
def serialize_todolist(segments: list[TodoItem | RawLine]) -> str: ...
def parse_notes(text: str) -> tuple[str, list[Note]]: ...
def serialize_notes(preamble: str, notes: list[Note]) -> str: ...
```

序列化细节：todolist 末尾保留一个换行；notes 块之间用一个空行分隔，文件末尾单换行。

运行测试 → **全部通过**。`ruff check` + `ruff format`。

**提交**：`feat(todo): 添加 Markdown 解析器与数据模型`

---

## Task 2：TodoService 文件读写服务（TDD）

**文件**：
- 测试：`tests/test_todo/test_service.py`
- 实现：`src/thumbelina/todo/service.py`

### 2.1 先写测试（用 `tmp_path` fixture）

覆盖用例：
- `test_init_creates_directory`：目录不存在时 `init()` 创建（`mkdir(parents=True, exist_ok=True)`）
- `test_init_preserves_existing_files`：预先写入已有 todolist.md/notes.md，init 后内容不变
- `test_add_and_list_items`：空目录下 add 两条 → list 返回 index 0/1
- `test_update_item_text_and_done`：分别更新 text、done；越界 index 抛 `IndexError`
- `test_delete_item`：删除后剩余项 index 重新连续
- `test_add_note_prepends`：add 两条 note，第一条在列表前面（index 0 是最新的）；文件中新条目在顶部
- `test_update_note` / `test_delete_note`：越界抛 `IndexError`
- `test_manual_file_edit_visible`：service 写入后，手工改写文件，下一次 list 反映手工修改（每次操作都重读文件）
- `test_atomic_write`：写入后目录中无残留临时文件，文件内容完整
- `test_concurrent_adds`：`asyncio.gather` 并发 add 10 条 item → list 恰好 10 条，无丢失

运行 → **应失败**

### 2.2 实现 `service.py`

```python
class TodoService:
    def __init__(self, directory: str | Path) -> None: ...
    async def init(self) -> None
    async def list_items(self) -> list[TodoItem]
    async def add_item(self, text: str) -> list[TodoItem]
    async def update_item(self, index: int, *, text: str | None = None,
                          done: bool | None = None) -> list[TodoItem]
    async def delete_item(self, index: int) -> list[TodoItem]
    async def list_notes(self) -> list[Note]
    async def add_note(self, content: str) -> list[Note]
    async def update_note(self, index: int, content: str) -> list[Note]
    async def delete_note(self, index: int) -> list[Note]
```

实现要点：
- 单一 `asyncio.Lock`，每个写操作 `async with self._lock:` 内完成 读→改→写
- 时间戳：`datetime.now().strftime("%Y-%m-%d %H:%M")`
- `_write_atomic(path, text)`：写同目录 `path.with_suffix(path.suffix + ".tmp")` 后 `os.replace`
- 文件不存在时读取视为空内容（首次 add 自动创建文件）
- 越界检查：`0 <= index < len(items)` 否则 `raise IndexError`

运行测试 → **全部通过**。`ruff` + `mypy src/thumbelina/todo/`（strict，注意 `TodoItem | RawLine` 联合类型的窄化）。

**提交**：`feat(todo): 添加 TodoService 文件读写服务（原子写入+并发锁）`

---

## Task 3：配置段 TodoConfig（TDD）

**文件**：
- 测试：`tests/test_config/test_todo_config.py`
- 实现：`src/thumbelina/config/models.py`、`thumbelina.yaml.example`

### 3.1 先写测试

- `test_todo_config_defaults`：`AppConfig().todo.enabled is True`、`directory == "TODO"`
- `test_todo_config_override`：`AppConfig(todo={"enabled": False, "directory": "X"})` 生效

运行 → **应失败**

### 3.2 实现

`config/models.py` 增加：
```python
class TodoConfig(BaseModel):
    """TODO module configuration (local Markdown files)."""
    enabled: bool = Field(default=True, description="Enable the TODO module")
    directory: str = Field(default="TODO", description="Directory for Markdown files")
```
`AppConfig` 增加字段 `todo: TodoConfig = Field(default_factory=TodoConfig)`。

`thumbelina.yaml.example` 末尾增加注释段：
```yaml
# TODO module: local Markdown-based todo list & quick notes
todo:
  enabled: true
  directory: TODO
```

运行测试 → 通过。检查 `tests/test_config/` 已有测试不回归：`pytest tests/test_config/ -x -q`。

**提交**：`feat(config): 添加 todo 配置段（enabled/directory）`

---

## Task 4：API 路由 + 依赖注入 + lifespan 接线（TDD）

**文件**：
- 测试：`tests/test_api/test_todo.py`
- 实现：`src/thumbelina/api/routes/todo.py`、`src/thumbelina/api/deps.py`、`src/thumbelina/api/app.py`

### 4.1 先写测试 `tests/test_api/test_todo.py`

自建 fixture（不复用 conftest 的 `client`，避免污染）：
```python
@pytest.fixture
def todo_client(tmp_path, mock_agent, mock_memory):
    config = AppConfig(
        llm=LLMConfig(provider="openai", model="test", api_key="k"),
        memory=MemoryConfig(database_url="sqlite:///:memory:"),
        todo=TodoConfig(directory=str(tmp_path / "TODO")),
    )
    # 与 tests/test_api/conftest.py 相同的三个 patch 后 create_app + TestClient
```

覆盖用例：
- `test_status_enabled`：`GET /api/v1/todo/status` → `{"enabled": true}`
- `test_items_crud`：GET 空 → POST `{"text": "买牛奶"}` → 返回完整列表 → PATCH done=true → PATCH text → DELETE，每步断言完整列表
- `test_post_item_rejects_empty`：`{"text": "  "}` → 422
- `test_patch_invalid_index_404`：越界 → 404
- `test_notes_crud`：POST 两条 → 最新的 index 为 0 且带 timestamp → PUT 修改 content → DELETE
- `test_post_note_rejects_empty`：422
- `test_503_when_disabled`：`TodoConfig(enabled=False)` 的 client → 所有数据端点 503，`status` 返回 `{"enabled": false}`
- 复用 `mock_agent`/`mock_memory` fixture（从 conftest 自动可用）

运行 → **应失败**

### 4.2 实现

**`routes/todo.py`**：
```python
router = APIRouter(prefix="/todo", tags=["todo"])

class TodoItemCreate(BaseModel):
    text: str = Field(min_length=1)
class TodoItemUpdate(BaseModel):
    text: str | None = None
    done: bool | None = None
class NoteCreate(BaseModel):
    content: str = Field(min_length=1)
class NoteUpdate(BaseModel):
    content: str = Field(min_length=1)
```
端点按设计文档第 4 节。`IndexError` → `HTTPException(404)`。
`/status` 端点不用 503 依赖：`getattr(request.app.state, "todo_service", None)` 直接判断，返回 `{"enabled": bool}`。
其余端点用 `Depends(get_todo_service)`。
text/content 入库前 `.strip()`；strip 后为空也按 422 处理（在 handler 内检查，因 min_length 不拦空白串）。

**`deps.py`** 增加：
```python
def get_todo_service(request: Request) -> TodoService:
    service = getattr(request.app.state, "todo_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="TODO module is not available")
    return service
```
注意 deps.py 已 import 多个内部模块，追加 `from thumbelina.todo.service import TodoService` 即可（deps 不属于 todo 模块，不违反零耦合约束）。

**`app.py`** lifespan（feedback_repo 初始化块之后）：
```python
# Initialize TODO module (independent and pluggable)
todo_service = None
if config.todo.enabled:
    try:
        from thumbelina.todo.service import TodoService

        todo_service = TodoService(config.todo.directory)
        await todo_service.init()
    except Exception:
        logger.warning("TODO module not initialized", exc_info=True)
app.state.todo_service = todo_service
```
路由注册区追加 `app.include_router(todo.router, prefix="/api/v1")`（含 routes 包 import）。

运行测试 → 通过。跑全量 API 测试防回归：`pytest tests/test_api/ -x -q`。

**提交**：`feat(todo): 添加 /api/v1/todo REST 端点与可插拔接线`

---

## Task 5：前端 API 客户端（TDD）

**文件**：
- 测试：`frontend/src/api/todo.test.ts`
- 实现：`frontend/src/api/todo.ts`

### 5.1 先写测试

参照 `frontend/src/api/llmConfig.test.ts` 的 mock fetch 模式：
- `fetchTodoItems` / `fetchNotes`：正常解析 JSON
- `addTodoItem` / `updateTodoItem` / `deleteTodoItem`：方法、URL、body 正确，返回完整列表
- `addNote` / `updateNote` / `deleteNote`：同上
- `fetchTodoStatus`：返回 `{enabled}`
- 非 ok 响应抛错

运行：`cd frontend && npx vitest run src/api/todo.test.ts` → **应失败**

### 5.2 实现 `todo.ts`

```ts
export interface TodoItem { index: number; text: string; done: boolean }
export interface TodoNote { index: number; timestamp: string; content: string }
export interface TodoListResponse { items: TodoItem[] }
export interface TodoNotesResponse { notes: TodoNote[] }

export async function fetchTodoStatus(): Promise<{ enabled: boolean }>
export async function fetchTodoItems(): Promise<TodoItem[]>
export async function addTodoItem(text: string): Promise<TodoItem[]>
export async function updateTodoItem(index: number, patch: { text?: string; done?: boolean }): Promise<TodoItem[]>
export async function deleteTodoItem(index: number): Promise<TodoItem[]>
export async function fetchNotes(): Promise<TodoNote[]>
export async function addNote(content: string): Promise<TodoNote[]>
export async function updateNote(index: number, content: string): Promise<TodoNote[]>
export async function deleteNote(index: number): Promise<TodoNote[]>
```
所有函数统一 `res.ok` 检查，失败抛 `Error`（含 status）。

运行 → 通过。**提交**：`feat(frontend): 添加 TODO API 客户端`

---

## Task 6：TodoPage 组件与样式（TDD）

**文件**：
- 测试：`frontend/src/components/Todo/TodoPage.test.tsx`
- 实现：`frontend/src/components/Todo/TodoPage.tsx`、样式追加到 `frontend/src/App.css`

### 6.1 先写测试（jsdom + mock fetch）

- `renders todo and notes panels`：mock 列表响应，断言两个面板标题与条目文本渲染
- `shows degraded message when disabled`：mock status `{enabled:false}` → 显示降级提示（i18n key `todo.disabled`）
- `add todo item`：输入 + 点击添加按钮 → 断言 POST 被调用且列表刷新
- `toggle todo done`：点击复选框 → PATCH 被调用
- `delete note`：点击删除 → DELETE 被调用

运行 → **应失败**

### 6.2 实现

组件结构（数据流集中在 TodoPage，面板为受控组件）：
```
TodoPage.tsx
├── TodoListPanel（内联子组件即可）
│   ├── 新增输入框 + 添加按钮
│   └── 条目行：checkbox（切换 done）+ 文本（双击/编辑按钮进入行内编辑，Enter 保存，Esc 取消）+ 删除按钮
└── NotesPanel
    ├── textarea + 追加按钮
    └── 卡片列表：时间戳头 + 内容 + 编辑（行内 textarea）/删除按钮
```
- 挂载时 `fetchTodoStatus()`；`enabled === false` 只渲染降级提示
- 所有写操作后直接用返回的完整列表 `setState`（不重新 GET）
- 加载态 / 错误态（`common.loading`、`common.error`）
- i18n 键全部走 `useTranslation`，文案键定义在 Task 7 一并添加，本任务先列出键名清单：
  `nav.todo`、`todo.title`、`todo.items`、`todo.notes`、`todo.placeholder`、`todo.add`、
  `todo.notePlaceholder`、`todo.addNote`、`todo.disabled`、`todo.empty`、`todo.emptyNotes`、`todo.edit`、`todo.delete`

样式：追加到 `App.css`，BEM 命名（`.todo-page`、`.todo-page__panel`、`.todo-item`…），
遵循设计令牌（teal 主色变量、卡片圆角阴影与现有页面一致），响应式：
`grid-template-columns: 1fr 1fr`，窄屏（max-width: 900px）单列。

运行测试 → 通过。**提交**：`feat(frontend): 添加 TodoPage 双栏页面（待办+随手记）`

---

## Task 7：导航接线与 i18n（TDD）

**文件**：`frontend/src/components/Layout/Header.tsx`、`frontend/src/App.tsx`、
`frontend/src/i18n/locales/en.json`、`frontend/src/i18n/locales/zh-CN.json`、
`frontend/src/components/Layout/Header.test.tsx`

### 7.1 先改 `Header.test.tsx`：断言 `nav-todo` 按钮渲染 → 运行失败

### 7.2 实现

- `Header.tsx`：`Page` 联合类型加 `'todo'`；`navKeys` 插入（放在 `'tasks'` 之后）；
  `NAV_ICONS` 用 `ClipboardList`（`ListTodo` 已被 tasks 占用）；`NAV_I18N` 加 `todo: 'nav.todo'`
- `App.tsx`：import `TodoPage`，switch 中 `case 'todo': return <TodoPage />`
- i18n 两个 locale 文件补 `nav.todo`（"TODO" / "待办"）及 Task 6 列出的 `todo.*` 全部键

运行：`npx vitest run src/components/Layout/Header.test.tsx` → 通过；
全量前端测试 + lint + build：`npm run test && npm run lint && npm run build`

**提交**：`feat(frontend): 导航接入 TODO 页面并补全中英文案`

---

## Task 8：全量验证与 README

1. 后端全量：`pytest -x -q`、`ruff check src/ tests/`、`ruff format --check src/ tests/`、`mypy src/`
2. 前端全量：`cd frontend && npm run test && npm run lint && npm run build`
3. 更新 `README.md` 与 `README_CN.md` 功能列表，增加 TODO 模块说明（本地 Markdown 存储、配置项）
4. 冒烟验证（如可启动）：`python start_dev.py` 后手动确认导航出现、增删改查与文件落盘正确；不可启动则跳过并说明

**提交**：`docs(readme): 补充 TODO 模块说明`

---

## 验收标准

- [ ] `pytest` 全绿（新增 ~30 个用例），`ruff`/`mypy` 无告警
- [ ] 前端 `npm run test` / `lint` / `build` 全绿
- [ ] `TODO/todolist.md` 现有内容不丢失，手工编辑文件后 Web 刷新可见
- [ ] `todo.enabled: false` 时服务器正常启动，前端显示降级提示
- [ ] README 中英文档已更新
