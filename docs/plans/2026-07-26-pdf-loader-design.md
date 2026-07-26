# PDF Loader 设计文档

**日期**: 2026-07-26
**状态**: 草案

---

## 一、概述

为 RAG 模块的 `ingestion/loader.py` 新增 `PDFLoader`，支持：

1. **数字化 PDF**（文本可选中）— 直接提取文本
2. **扫描件 PDF**（纯图片）— 通过 OCR 识别文字
3. **混合 PDF**（部分页面文本、部分页面扫描）— 自动判断并合并处理
4. **PDF 表格** — 结构化提取并转为 Markdown 格式，保留上下文

## 二、现有代码结构

```
ingestion/
  loader.py       ← TextLoader, HTMLLoader 已实现；PDFLoader 待实现
  chunker.py      ← FixedSizeChunker, RecursiveChunker 已实现

knowledge_base/
  models.py       ← DocumentType.PDF 已定义
```

**关键接口**：

```python
class Loader(ABC):
    extensions: list[str] = []
    def load(self, path: str) -> list[Document]: ...
    def _get_sha256(self, content: str) -> bytes: ...
    def _get_sim_hash_64(self, content: str) -> bytes: ...
```

**约束**：
- `Document.content` 为 `str` 类型 — 表格必须转为文本格式
- 已有 SHA-256 + SimHash 去重机制
- Chunker 按文本字符数分块，表格需整体保留

---

## 三、PDF 扫描件处理策略对比

### 3.1 OCR 引擎对比

| 维度 | Tesseract (pytesseract) | PaddleOCR | EasyOCR | Surya OCR | docTR |
|------|------------------------|-----------|---------|-----------|-------|
| **GitHub Stars** | ~60,000 | ~45,000 | ~23,000 | ~15,000 | ~5,000 |
| **许可证** | Apache-2.0 | Apache-2.0 | Apache-2.0 | GPL-3.0 | Apache-2.0 |
| **维护状态** | 成熟稳定 | 非常活跃 | 活跃 | 活跃（新项目） | 活跃 |
| **中文识别精度** | 一般 | **最佳** | 良好 | 良好 | 有限 |
| **中英混排识别** | 较差 | **优秀** | 良好 | 良好 | 有限 |
| **版面分析** | 基础 | PP-Structure | 无 | 内置 | 支持 |
| **表格识别** | 无 | PP-Structure | 无 | 支持 | 有限 |
| **CPU 速度** | 快 | 较快 | 慢 | 慢 | 中等 |
| **GPU 加速** | 不支持 | 优秀 | 优秀 | 支持 | 支持 |
| **安装难度** | 需系统二进制 | PaddlePaddle | 简单 | 简单 | 简单 |
| **模型大小** | ~30MB | ~15MB（轻量） | ~100MB+ | ~500MB+ | ~100MB |

### 3.2 扫描件处理方案对比

| 方案 | 流程 | 优势 | 劣势 | 适用场景 |
|------|------|------|------|---------|
| **方案 A：Tesseract** | PDF → 逐页渲染图片 → pytesseract OCR → 文本 | 安装简单；Apache-2.0 许可 | 中文精度一般；无 GPU 加速；无版面分析 | 英文为主的简单文档 |
| **方案 B：PaddleOCR** | PDF → 逐页渲染图片 → PaddleOCR 识别 → 文本 | 中文精度最高；支持版面分析和表格识别；CPU/GPU 均可用 | PaddlePaddle 框架依赖较大 | **中英文混合文档（推荐）** |
| **方案 C：EasyOCR** | PDF → 逐页渲染图片 → EasyOCR 识别 → 文本 | API 极简；Apache-2.0 许可 | 速度慢；无版面分析/表格识别 | 快速原型验证 |
| **方案 D：Surya OCR** | PDF → Surya 全流水线（版面+OCR）→ 文本 | Transformer 架构；内置版面分析+表格+阅读顺序 | GPL-3.0 许可；显存需求高（4-8GB） | 需要版面分析的高质量场景 |
| **方案 E：PaddleOCR PP-Structure** | PDF → PP-Structure 全流水线 → 结构化输出 | 端到端版面分析+OCR+表格识别一体化；中文最优 | 体积大；与 PyTorch 生态兼容性需额外适配 | **中文文档高质量处理（推荐）** |

### 3.3 扫描件判断策略

PDF 页面是否为扫描件，可通过以下方式判断：

```python
def _is_scanned_page(page) -> bool:
    """判断页面是否为扫描件"""
    # 策略1：检查文本量
    text = page.get_text().strip()
    if len(text) < 10:  # 文本极少，大概率是扫描件
        return True

    # 策略2：检查图片数量和面积
    images = page.get_images()
    if images:
        # 计算图片面积占页面面积的比例
        page_area = page.rect.width * page.rect.height
        img_area = sum(img.width * img.height for img in images)
        if img_area / page_area > 0.8:  # 图片覆盖超过 80%
            return True

    return False
```

### 3.4 推荐方案

**默认方案：PyMuPDF 渲染 + PaddleOCR**

理由：
- PyMuPDF 负责 PDF 页面渲染为图片（速度快）
- PaddleOCR 中英文混排识别精度最高
- 轻量模型 CPU 即可运行
- 均为 Apache-2.0 许可

**懒加载策略**：OCR 引擎作为可选依赖，仅在检测到扫描件时按需初始化。

---

## 四、PDF 表格处理策略对比

### 4.1 提取工具对比

| 维度 | pdfplumber | Camelot | Tabula | Table Transformer | PaddleOCR PP-Structure | Docling (IBM) | Unstructured.io |
|------|-----------|---------|--------|-------------------|----------------------|---------------|-----------------|
| **原理** | PDF 矢量线条+字符坐标 | OpenCV 检测线条/空白分析 | Java 面积检测 | DETR 深度学习 | PaddlePaddle 二阶段 | TableFormer 深度学习 | 多策略可选 |
| **简单表格** | 好 | 优秀 | 好 | 优秀 | 优秀 | 优秀 | 好 |
| **合并单元格** | 差 | 一般 | 差 | 好 | 好 | **优秀** | 中等 |
| **无边框表格** | 一般 | Stream 模式一般 | 一般 | 好 | 好 | 好 | 中等 |
| **嵌套表格** | 不支持 | 不支持 | 不支持 | 一般 | 一般 | 一般 | 一般 |
| **多页表格** | 需手动 | 需手动 | 需手动 | 需后处理 | 需后处理 | 需后处理 | 需后处理 |
| **扫描件表格** | 不支持 | Lattice 可 | 不支持 | 需 OCR | **原生支持** | 需 OCR | 需 OCR |
| **中文支持** | 取决于字体嵌入 | 同左 | 同左 | 取决于 OCR | **优秀** | 中等 | 中等 |
| **输出格式** | list[dict] | DataFrame | DataFrame | 结构化 JSON | HTML/Excel | Markdown/JSON | HTML/JSON |
| **速度** | 快 | 中等 | 中等 | GPU 快/CPU 慢 | 中等 | 中等 | fast 快/hi_res 慢 |
| **安装难度** | 极简（纯 Python） | 复杂（Ghostscript） | 需 Java | 中等 | 较高（PaddlePaddle） | 简单 | 简单 |
| **许可证** | MIT | MIT | MIT | MIT | Apache-2.0 | MIT | Apache-2.0 |
| **维护状态** | 活跃 | **已归档** | 维护缓慢 | 活跃 | 非常活跃 | 活跃 | 活跃 |

### 4.2 端到端文档 AI 框架对比

| 维度 | Docling (IBM) | Unstructured.io | Marker | MarkItDown (Microsoft) |
|------|---------------|-----------------|--------|----------------------|
| **表格精度** | **最高** | 中高 | 中 | 低中 |
| **合并单元格** | **优秀** | 中等 | 一般 | 差 |
| **中文支持** | 中等 | 中等 | 一般 | 一般 |
| **输出格式** | Markdown/JSON | HTML/JSON | Markdown | Markdown |
| **速度** | 中等 | fast 快 | 快 | 极快 |
| **许可证** | MIT | Apache-2.0 | GPL-3.0 | MIT |
| **推荐场景** | **通用最佳选择** | 多格式文档 | 快速 PDF→MD | 极简轻量 |

### 4.3 云 API 服务对比

| 维度 | Azure Document Intelligence | AWS Textract | Google Document AI |
|------|-----------------------------|--------------|-------------------|
| **表格精度** | **最高** | 高 | 高 |
| **合并单元格** | 好 | 一般 | 一般 |
| **中文支持** | 好 | 好 | 好 |
| **延迟** | 1-5s/页 | 1-5s/页 | 1-5s/页 |
| **成本** | $0.01/页 | $0.0015/页 | $0.0015/页 |
| **离线使用** | 不支持 | 不支持 | 不支持 |

### 4.4 表格在 RAG 中的表示策略

提取的表格需要转为文本存储在 `Document.content` 中，有三种主要格式：

#### 格式一：Markdown 表格（推荐存储格式）

```markdown
| 指标 | Q1 | Q2 | Q3 |
|------|-----|-----|-----|
| 收入 | 100 | 120 | 150 |
| 利润 | 20  | 25  | 30  |
```

- ✅ 人类可读，LLM 理解良好，保留结构
- ❌ 大表格可能超出 chunk 限制

#### 格式二：JSON

```json
{
  "caption": "季度财务数据",
  "headers": ["指标", "Q1", "Q2", "Q3"],
  "rows": [["收入", "100", "120", "150"], ["利润", "20", "25", "30"]]
}
```

- ✅ 结构精确，便于程序处理
- ❌ embedding 效果一般，语法噪音影响语义理解

#### 格式三：自然语言描述（推荐 embedding 格式）

```
这是一份季度财务数据表。第一季度收入100，利润20；第二季度收入120，
利润25；第三季度收入150，利润30。整体呈上升趋势。
```

- ✅ **向量检索效果最好** — embedding 模型对自然语言语义理解最强
- ❌ 需要 LLM 生成，有额外成本和延迟

### 4.5 推荐：混合表示策略

```
原始表格
  │
  ├──▶ Markdown 格式 → 存入 chunk content（保留结构，供 LLM 引用）
  │
  └──▶ 自然语言摘要 → 生成 embedding 向量（提升检索召回率）
```

**表格分块原则**：
1. **不拆分表格** — 表格应作为单一 chunk
2. **表头跟随** — 若必须按行拆分，每行带表头
3. **包含上下文** — 标题、脚注、前后说明文字与表格同属一个 chunk
4. **metadata 增强**：

```json
{
  "content_type": "table",
  "table_caption": "季度财务数据",
  "source_page": 5,
  "doc_title": "2025年度报告"
}
```

---

## 五、PDF 文本提取库对比

| 维度 | PyMuPDF (fitz) | pdfplumber | pypdf | PDFMiner |
|------|---------------|------------|-------|----------|
| **GitHub Stars** | ~9,000 | ~5,000 | ~8,000 | ~6,000 |
| **许可证** | AGPL-3.0 ⚠️ | MIT | BSD-3-Clause | MIT |
| **文本提取质量** | 优秀 | 优秀 | 良好 | 优秀 |
| **布局保持** | 良好 | 优秀（字符级坐标） | 基础 | 优秀 |
| **表格检测** | 基础 | **优秀（内置）** | 无 | 无 |
| **图片提取** | 优秀 | 无 | 良好 | 无 |
| **速度** | **最快**（C 底层） | 最慢（pdfminer 底层） | 中等 | 慢 |
| **安装** | 简单 | 简单 | 最简单 | 简单 |
| **系统依赖** | 无 | 无 | 无 | 无 |

### 推荐

| 场景 | 推荐 | 理由 |
|------|------|------|
| 主文本提取 | **PyMuPDF** | 速度最快（10-100x 于 pdfplumber），功能全面 |
| 表格提取 | **pdfplumber** | 内置表格检测，字符级坐标，纯 Python |
| 许可敏感 | **pypdf + pdfplumber** | 全 MIT/BSD 许可，无 AGPL 传染性 |

> ⚠️ **PyMuPDF 许可警告**：AGPL-3.0 要求以 AGPL 发布整个应用，或购买 Artifex 商业授权。
> 作为个人项目若不开源，需评估许可风险。可退而使用 pypdf（BSD）作为主提取器。

---

## 六、设计方案

### 6.1 架构概览

```
PDFLoader(Loader)
  │
  ├── 文本提取层（必须）
  │   ├── PyMuPDFProvider    ← 主选：速度最快
  │   └── PdfPlumberProvider ← 备选：MIT 许可 / 表格提取
  │
  ├── 表格检测层（可选）
  │   ├── pdfplumber_tables   ← 默认：轻量，有线表格效果好
  │   └── docling_tables      ← 高质量：合并单元格支持好
  │
  ├── 扫描件检测层（自动触发）
  │   ├── _is_scanned_page()  ← 启发式判断
  │   └── OCR 引擎（懒加载）
  │       ├── PaddleOCRProvider ← 中英文最佳
  │       └── EasyOCRProvider   ← 快速替代
  │
  └── 输出合并
      └── list[Document]  ← content 为 Markdown 格式文本
```

### 6.2 核心类设计

```python
class PDFLoader(Loader):
    """PDF 文档加载器，支持数字化 PDF、扫描件和表格提取。"""

    extensions: list[str] = [DocumentType.PDF.value]

    def __init__(
        self,
        text_engine: str = "pymupdf",      # "pymupdf" | "pdfplumber" | "pypdf"
        table_strategy: str = "pdfplumber", # "none" | "pdfplumber" | "docling"
        ocr_engine: str = "paddleocr",      # "none" | "paddleocr" | "easyocr"
        ocr_language: str = "ch",           # OCR 语言包
        pages_per_doc: int = 0,             # 0=整文档一个 Document；>0=每 N 页拆分
    ): ...

    def load(self, path: str) -> list[Document]: ...

    # ---- 内部方法 ----
    def _extract_pages(self, path: str) -> list[PageResult]:
        """提取每页文本，自动检测扫描件并触发 OCR"""

    def _extract_tables(self, path: str) -> dict[int, list[TableResult]]:
        """提取表格，返回 {page_num: [table_markdown, ...]}"""

    def _is_scanned_page(self, page) -> bool:
        """启发式判断页面是否为扫描件"""

    def _ocr_page(self, page_image: bytes) -> str:
        """OCR 单页图片"""

    def _merge_content(self, pages, tables) -> str:
        """合并文本和表格为最终 Markdown 内容"""

    def _build_documents(self, path, content) -> list[Document]:
        """构建 Document 对象，计算 hash"""


@dataclass
class PageResult:
    """单页提取结果"""
    page_num: int
    text: str
    is_scanned: bool
    ocr_text: str | None = None


@dataclass
class TableResult:
    """表格提取结果"""
    page_num: int
    bbox: tuple[float, float, float, float]  # 表格在页面中的位置
    markdown: str                              # Markdown 格式
    caption: str | None = None                 # 表格标题
```

### 6.3 处理流程

```
load(path)
  │
  ├─ Step 1: 检查文件 → 验证 .pdf 后缀和文件存在性
  │
  ├─ Step 2: 提取文本（逐页）
  │   ├─ 正常页面 → 直接提取文本
  │   └─ 扫描页面 → 渲染为图片 → OCR 识别 → 获取文本
  │
  ├─ Step 3: 提取表格（全文档）
  │   ├─ pdfplumber: page.find_tables() → table.extract() → 转 Markdown
  │   └─ 或 docling: DocumentConverter → export_to_markdown()
  │
  ├─ Step 4: 合并内容
  │   └─ 遍历每页，将文本和表格 Markdown 按页码顺序交织
  │      表格位置用 Markdown 表格替换原始文本区域
  │
  ├─ Step 5: 分段（可选）
  │   └─ 如果 pages_per_doc > 0，按页数切分为多个 Document
  │
  └─ Step 6: 构建 Document
      ├─ 计算 SHA-256 和 SimHash
      └─ 返回 list[Document]
```

### 6.4 依赖管理

PDF 相关依赖应作为可选依赖（optional-dependencies），在 `pyproject.toml` 中：

```toml
[project.optional-dependencies]
rag = [
    "chromadb>=1.0.0",
    "sentence-transformers>=3.0.0",
    "simhash>=2.1.2",
    # PDF 支持
    "pymupdf>=1.24.0",           # PDF 文本提取 + 图片渲染
    "pdfplumber>=0.11.0",        # 表格提取（可选，用于高质量模式）
]
rag-ocr = [
    "thumbelina[rag]",
    "paddleocr>=2.8.0",          # 中英文 OCR
    "paddlepaddle>=2.6.0",       # PaddleOCR 底层框架
]
rag-full = [
    "thumbelina[rag-ocr]",
    "docling>=2.0.0",            # 高质量表格提取
]
```

所有依赖在代码中通过 `try/except ImportError` 懒导入，遵循项目既有的可选依赖模式。

### 6.5 表格感知分块增强

在 `chunker.py` 中需要增强表格边界检测：

```python
def _is_table_line(self, line: str) -> bool:
    """检测 Markdown 表格行"""
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|")

def _find_table_boundaries(self, text: str) -> list[tuple[int, int]]:
    """找到所有表格的起止行号，确保表格不被拆分"""
```

**分块规则**：
- 检测到 Markdown 表格时，将整个表格作为单一 chunk
- 表格前的标题/说明文字与表格合并为同一 chunk
- 仅在表格边界之外的位置执行正常分块

### 6.6 错误处理

```python
class PDFLoadError(Exception):
    """PDF 加载异常基类"""

class PDFEncryptedError(PDFLoadError):
    """加密 PDF，无法读取"""

class PDFEmptyError(PDFLoadError):
    """PDF 无文本内容且 OCR 未启用"""

class OCREngineError(PDFLoadError):
    """OCR 引擎不可用"""
```

### 6.7 元数据增强

提取到的 Document metadata 应包含：

```python
{
    "page_count": 10,
    "has_tables": True,
    "has_scanned_pages": False,
    "text_engine": "pymupdf",
    "table_strategy": "pdfplumber",
    "ocr_engine": None,
    "creation_date": "2025-01-15",
    "author": "...",
}
```

---

## 七、实现路线

| 阶段 | 内容 | 优先级 |
|------|------|--------|
| **Phase 1** | `PDFLoader` 基础实现：PyMuPDF 文本提取，无表格/OCR | P0 |
| **Phase 2** | 表格提取：pdfplumber 集成，表格转 Markdown，表格感知分块 | P0 |
| **Phase 3** | 扫描件 OCR：PaddleOCR 集成，自动检测扫描页，懒加载 | P1 |
| **Phase 4** | 高质量模式：Docling 表格提取选项 | P2 |
| **Phase 5** | Loader 路由器：`AutoLoader` 根据文件后缀自动选择 Loader | P2 |

### Phase 1 — 基础文本提取

```python
class PDFLoader(Loader):
    extensions = [DocumentType.PDF.value]

    def load(self, path: str) -> list[Document]:
        import pymupdf  # 懒导入
        doc = pymupdf.open(path)
        content = ""
        for page in doc:
            content += page.get_text()
        doc.close()
        return [Document(
            id=uuid.uuid4().hex,
            name=Path(path).name,
            source_uri=str(Path(path).resolve()),
            document_type=DocumentType.PDF,
            content=content,
            sha256=self._get_sha256(content),
            sim_hash_64=self._get_sim_hash_64(content),
        )]
```

### Phase 2 — 表格提取

在 Phase 1 基础上增加：
1. 用 pdfplumber 检测每页表格
2. 表格区域转 Markdown pipe-table 格式
3. 在文本中用 Markdown 表格替换原始表格区域
4. Chunker 增加表格边界检测

### Phase 3 — 扫描件 OCR

在 Phase 2 基础上增加：
1. 每页提取文本后判断是否为扫描件
2. 扫描页渲染为图片
3. PaddleOCR 懒加载识别
4. OCR 文本与正常文本合并

---

## 八、测试计划

| 测试用例 | 描述 |
|---------|------|
| `test_load_normal_pdf` | 加载数字化 PDF，验证文本提取正确 |
| `test_load_scanned_pdf` | 加载扫描件 PDF，验证 OCR 识别 |
| `test_load_mixed_pdf` | 加载混合 PDF（部分扫描），验证自动检测 |
| `test_load_table_pdf` | 加载含表格的 PDF，验证 Markdown 格式输出 |
| `test_load_table_with_merged_cells` | 合并单元格表格提取 |
| `test_load_encrypted_pdf` | 加密 PDF 抛出 PDFEncryptedError |
| `test_load_empty_pdf` | 空 PDF 处理 |
| `test_sha256_consistency` | 相同文件多次加载 hash 一致 |
| `test_page_splitting` | pages_per_doc 参数拆分验证 |
| `test_table_not_split_by_chunker` | 表格不被 chunker 拆分 |
| `test_lazy_ocr_import` | OCR 引擎未安装时不报错（非扫描件场景） |
