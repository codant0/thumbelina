# PDF Loader 实现计划

## Context

RAG 模块的 `ingestion/loader.py` 已有 `TextLoader` 和 `HTMLLoader`，但 `PDFLoader` 尚未实现。`DocumentType.PDF` 枚举已定义，设计文档已完成（`docs/plans/2026-07-26-pdf-loader-design.md`）。

## 目标

在 `ingestion/loader.py` 中实现 `PDFLoader`，支持：
1. 数字化 PDF 文本提取
2. 表格结构化提取并转 Markdown
3. 扫描件 PDF 的 OCR 识别（自动检测触发）
4. 表格感知的分块增强

## 实现步骤

### Phase 1: 基础 PDF 文本提取（P0）

1. **`src/thumbelina/rag/ingestion/loader.py`** — 新增 `PDFLoader` 类
   - 懒导入 `pymupdf`
   - `load(path)` 方法：打开 PDF → 逐页提取文本 → 合并 → 构建 `Document`
   - 计算 SHA-256 和 SimHash（复用基类方法）
   - 文件后缀和存在性校验（与 TextLoader 一致）

2. **`tests/test_rag/test_ingestion/test_loader.py`** — 新增测试
   - `test_load_normal_pdf`：加载普通 PDF，验证文本提取
   - `test_load_nonexistent_pdf`：文件不存在抛异常
   - `test_load_wrong_extension`：非 PDF 后缀抛异常
   - `test_sha256_consistency`：相同文件多次加载 hash 一致

3. **`pyproject.toml`** — 可选依赖
   ```toml
   [project.optional-dependencies]
   rag = [
       "chromadb>=1.0.0",
       "sentence-transformers>=3.0.0",
       "simhash>=2.1.2",
       "pymupdf>=1.24.0",
       "pdfplumber>=0.11.0",
   ]
   ```

### Phase 2: 表格提取（P0）

4. **`loader.py`** — 表格检测与提取
   - 懒导入 `pdfplumber`
   - `_extract_tables(path)` 方法：逐页检测表格 → 转 Markdown pipe-table
   - `_merge_content(pages, tables)` 方法：按页码交织文本和表格
   - 表格区域在原文中替换为 Markdown 格式

5. **`ingestion/chunker.py`** — 表格感知分块
   - 新增 `_is_table_line(line)` 方法
   - `_find_table_boundaries(text)` 方法
   - `RecursiveChunker.chunk()` 在分块时遇到表格边界跳过，保证表格整体保留

6. **测试**
   - `test_load_table_pdf`：含简单表格的 PDF
   - `test_load_table_with_merged_cells`：合并单元格表格
   - `test_table_not_split_by_chunker`：表格不被拆分

### Phase 3: 扫描件 OCR（P1）

7. **`loader.py`** — 扫描件检测与 OCR
   - `_is_scanned_page(page)` 方法：基于文本量和图片面积启发式判断
   - `_ocr_page(page_image)` 方法：PyMuPDF 渲染图片 → OCR 识别
   - OCR 引擎懒加载：默认 PaddleOCR，try/except ImportError 降级

8. **测试**
   - `test_load_scanned_pdf`：扫描件 PDF
   - `test_load_mixed_pdf`：混合 PDF
   - `test_lazy_ocr_import`：OCR 未安装时不报错（非扫描件场景）

### Phase 4: 高质量模式与 AutoLoader（P2）

9. **`loader.py`** — Docling 集成
   - 可选 `text_engine="docling"` 参数
   - 懒导入 `docling`

10. **`loader.py`** — `AutoLoader` 路由器
    - 根据文件后缀自动选择 `TextLoader` / `HTMLLoader` / `PDFLoader`
    - 修复现有 TODO（第 68 行）

## 文件变更清单

| 文件 | 变更类型 | 描述 |
|------|---------|------|
| `src/thumbelina/rag/ingestion/loader.py` | 修改 | 新增 PDFLoader、AutoLoader |
| `src/thumbelina/rag/ingestion/chunker.py` | 修改 | 表格感知分块 |
| `pyproject.toml` | 修改 | 新增可选依赖 |
| `tests/test_rag/test_ingestion/test_loader.py` | 修改 | 新增 PDF 测试用例 |
| `tests/test_rag/test_ingestion/test_chunker.py` | 修改 | 表格分块测试 |
| `docs/plans/2026-07-26-pdf-loader-design.md` | 已完成 | 设计文档 |

## 验证方式

```bash
# 安装依赖
pip install -e ".[dev,rag]"

# 运行 RAG 测试
pytest tests/test_rag/test_ingestion/ -x -v

# 手动验证（准备测试 PDF 文件）
python -c "
from thumbelina.rag.ingestion.loader import PDFLoader
loader = PDFLoader()
docs = loader.load('path/to/test.pdf')
print(f'Pages: {len(docs)}, Content length: {len(docs[0].content)}')
"
```

## 注意事项

- **PyMuPDF 许可**：AGPL-3.0，需评估对项目的影响。如需规避，Phase 1 可改用 pypdf（BSD）
- **OCR 体积**：PaddleOCR 依赖 PaddlePaddle，安装体积较大，需设为可选依赖
- **测试 PDF 文件**：需在 `rag/test_data/` 目录下准备测试用 PDF 文件（含文本、表格、扫描件各一份）
