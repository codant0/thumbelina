"""Tests for RAG document loaders."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pymupdf
import pytest

from thumbelina.rag.common.models import DocumentType, PdfPageType
from thumbelina.rag.ingestion.loader import HTMLLoader, LoaderRegistry, PdfLoader, TextLoader


@pytest.fixture
def text_loader():
    return TextLoader()


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


class TestTextLoader:
    """Tests for TextLoader."""

    def test_class_exists(self, text_loader):
        assert text_loader is not None

    def test_supported_extensions(self, text_loader):
        assert ".txt" in text_loader.extensions
        assert ".md" in text_loader.extensions

    def test_load_txt_file(self, text_loader, tmp_dir):
        f = tmp_dir / "hello.txt"
        f.write_text("你好世界", encoding="utf-8")

        docs = text_loader.load(str(f))

        assert len(docs) == 1
        doc = docs[0]
        assert doc.content == "你好世界"
        assert doc.name == "hello.txt"
        assert doc.document_type is DocumentType.TXT
        assert doc.id  # 非空

    def test_load_md_file(self, text_loader, tmp_dir):
        f = tmp_dir / "readme.md"
        f.write_text("# 标题\n\n正文内容", encoding="utf-8")

        docs = text_loader.load(str(f))

        assert len(docs) == 1
        assert docs[0].document_type is DocumentType.MARKDOWN
        assert "标题" in docs[0].content

    def test_load_nonexistent_file_returns_empty(self, text_loader):
        docs = text_loader.load("/nonexistent/path/file.txt")
        assert docs == []

    def test_load_unsupported_extension_returns_empty(self, text_loader, tmp_dir):
        f = tmp_dir / "data.csv"
        f.write_text("a,b,c", encoding="utf-8")

        docs = text_loader.load(str(f))
        assert docs == []

    def test_load_directory_returns_empty(self, text_loader, tmp_dir):
        docs = text_loader.load(str(tmp_dir))
        assert docs == []

    def test_source_uri_is_absolute_path(self, text_loader, tmp_dir):
        f = tmp_dir / "test.txt"
        f.write_text("content", encoding="utf-8")

        docs = text_loader.load(str(f))

        assert Path(docs[0].source_uri).is_absolute()

    def test_load_empty_file(self, text_loader, tmp_dir):
        f = tmp_dir / "empty.txt"
        f.write_text("", encoding="utf-8")

        docs = text_loader.load(str(f))

        assert len(docs) == 1
        assert docs[0].content == ""

    def test_load_unicode_content(self, text_loader, tmp_dir):
        content = "中文内容🎉émojis"
        f = tmp_dir / "unicode.md"
        f.write_text(content, encoding="utf-8")

        docs = text_loader.load(str(f))

        assert docs[0].content == content


class TestLoaderRegistry:
    """Tests for LoaderRegistry auto-matching."""

    def test_registered_loaders(self):
        """TextLoader、HTMLLoader 和 PdfLoader 应自动注册。"""
        names = LoaderRegistry.list_registered()
        assert "TextLoader" in names
        assert "HTMLLoader" in names
        assert "PdfLoader" in names

    def test_supported_extensions(self):
        """已注册 Loader 的扩展名应全部可查。"""
        exts = LoaderRegistry.list_supported_extensions()
        assert ".txt" in exts
        assert ".md" in exts
        assert ".html" in exts
        assert ".htm" in exts
        assert ".pdf" in exts

    def test_find_txt_returns_text_loader(self):
        loader = LoaderRegistry.find("/some/path/doc.txt")
        assert isinstance(loader, TextLoader)

    def test_find_md_returns_text_loader(self):
        loader = LoaderRegistry.find("/some/path/doc.md")
        assert isinstance(loader, TextLoader)

    def test_find_html_returns_html_loader(self):
        loader = LoaderRegistry.find("/some/path/page.html")
        assert isinstance(loader, HTMLLoader)

    def test_find_htm_returns_html_loader(self):
        loader = LoaderRegistry.find("/some/path/page.htm")
        assert isinstance(loader, HTMLLoader)

    def test_find_url_returns_html_loader(self):
        loader = LoaderRegistry.find("https://example.com/article")
        assert isinstance(loader, HTMLLoader)

    def test_find_http_url_returns_html_loader(self):
        loader = LoaderRegistry.find("http://example.com")
        assert isinstance(loader, HTMLLoader)

    def test_find_pdf_returns_pdf_loader(self):
        loader = LoaderRegistry.find("/some/path/doc.pdf")
        assert isinstance(loader, PdfLoader)

    def test_find_unsupported_extension_raises(self):
        with pytest.raises(ValueError, match="不支持的文件类型"):
            LoaderRegistry.find("/some/path/data.csv")

    def test_find_returns_new_instance_each_time(self):
        """每次调用 find() 应返回新实例。"""
        l1 = LoaderRegistry.find("/a.md")
        l2 = LoaderRegistry.find("/b.md")
        assert l1 is not l2


def _make_pdf(path: Path, page_texts: list[str]) -> Path:
    """用 pymupdf 生成多页文本 PDF（ASCII 文本，避免测试依赖 CJK 字体）。"""
    doc = pymupdf.open()
    for text in page_texts:
        page = doc.new_page()
        if text:
            page.insert_text((72, 100), text)
    doc.save(str(path))
    doc.close()
    return path


def _add_full_page_image(page) -> None:
    """向页面插入一张铺满整页的图片，模拟扫描件。"""
    irect = pymupdf.IRect(0, 0, int(page.rect.width), int(page.rect.height))
    pix = pymupdf.Pixmap(pymupdf.csRGB, irect, 0)
    pix.clear_with(200)
    page.insert_image(page.rect, stream=pix.tobytes("png"))


class TestPdfLoader:
    """Tests for PdfLoader."""

    @pytest.fixture
    def pdf_loader(self):
        return PdfLoader()

    def test_load_single_page(self, pdf_loader, tmp_dir):
        f = _make_pdf(tmp_dir / "doc.pdf", ["Hello page one"])
        docs = pdf_loader.load(str(f))

        assert len(docs) == 1
        doc = docs[0]
        assert doc.document_type is DocumentType.PDF
        assert doc.content == "Hello page one"
        assert doc.page_count == 1
        assert doc.page_text == ["Hello page one"]
        assert len(doc.page_spans) == 1
        span = doc.page_spans[0]
        assert (span.page, span.start, span.end) == (1, 0, len("Hello page one"))

    def test_load_multi_page_offsets_consistent(self, pdf_loader, tmp_dir):
        pages = ["page one content", "page two content", "page three content"]
        f = _make_pdf(tmp_dir / "multi.pdf", pages)
        doc = pdf_loader.load(str(f))[0]

        assert doc.page_count == 3
        assert doc.content == "\n".join(pages)
        assert doc.page_text == pages
        # 偏移与正文严格一致：按 span 可精确切出每页文本
        for span, text in zip(doc.page_spans, pages):
            assert doc.content[span.start : span.end] == text

    def test_blank_page_skipped(self, pdf_loader, tmp_dir):
        f = _make_pdf(tmp_dir / "blank.pdf", ["first page", "", "third page"])
        doc = pdf_loader.load(str(f))[0]

        # 空白页不进入 content / page_spans，但物理总页数保持不变
        assert doc.page_count == 3
        assert [s.page for s in doc.page_spans] == [1, 3]
        assert doc.content == "first page\nthird page"

    def test_classify_text_page(self, pdf_loader, tmp_dir):
        f = _make_pdf(tmp_dir / "text.pdf", ["This is a normal text page with enough words."])
        pdf = pymupdf.open(str(f))
        try:
            text = pdf[0].get_text("text").strip()
            assert pdf_loader._classify_page(pdf[0], text) is PdfPageType.TEXT
        finally:
            pdf.close()

    def test_classify_scanned_page(self, pdf_loader):
        pdf = pymupdf.open()
        try:
            page = pdf.new_page()
            _add_full_page_image(page)
            assert pdf_loader._classify_page(page, "") is PdfPageType.SCANNED
        finally:
            pdf.close()

    def test_scanned_pdf_skipped_when_ocr_unavailable(self, pdf_loader, tmp_dir, monkeypatch):
        import thumbelina.rag.ingestion.loader as loader_mod

        monkeypatch.setattr(loader_mod, "_OCR_UNAVAILABLE", True)
        pdf = pymupdf.open()
        page = pdf.new_page()
        _add_full_page_image(page)
        path = tmp_dir / "scanned.pdf"
        pdf.save(str(path))
        pdf.close()

        assert pdf_loader.load(str(path)) == []

    def test_load_nonexistent_returns_empty(self, pdf_loader):
        assert pdf_loader.load("/nonexistent/path/file.pdf") == []


class TestOcrResultsToText:
    """Tests for PdfLoader._ocr_results_to_text（纯函数，不依赖真实 OCR 引擎）。"""

    def test_reading_order_and_line_grouping(self):
        results = [
            {
                # 乱序输入：第一行右框、第一行左框、第二行
                "rec_texts": ["world", "hello", "second line"],
                "rec_scores": [0.99, 0.98, 0.95],
                "rec_polys": [
                    [[100, 10], [150, 10], [150, 25], [100, 25]],
                    [[10, 10], [60, 10], [60, 25], [10, 25]],
                    [[10, 60], [90, 60], [90, 75], [10, 75]],
                ],
            }
        ]
        assert PdfLoader._ocr_results_to_text(results) == "hello world\nsecond line"

    def test_filters_low_confidence_boxes(self):
        results = [
            {
                "rec_texts": ["kept", "dropped"],
                "rec_scores": [0.9, 0.2],
                "rec_polys": [
                    [[10, 10], [60, 10], [60, 25], [10, 25]],
                    [[100, 10], [150, 10], [150, 25], [100, 25]],
                ],
            }
        ]
        assert PdfLoader._ocr_results_to_text(results) == "kept"

    def test_cjk_boxes_joined_without_space(self):
        results = [
            {
                "rec_texts": ["中文", "内容"],
                "rec_scores": [0.99, 0.99],
                "rec_polys": [
                    [[10, 10], [50, 10], [50, 25], [10, 25]],
                    [[55, 10], [95, 10], [95, 25], [55, 25]],
                ],
            }
        ]
        assert PdfLoader._ocr_results_to_text(results) == "中文内容"

    def test_empty_results(self):
        assert PdfLoader._ocr_results_to_text([]) == ""
        assert PdfLoader._ocr_results_to_text(None) == ""

    def test_ocr_page_returns_empty_when_engine_unavailable(self, monkeypatch):
        import thumbelina.rag.ingestion.loader as loader_mod

        monkeypatch.setattr(loader_mod, "_OCR_UNAVAILABLE", True)
        assert PdfLoader()._ocr_page(None, 1) == ""
