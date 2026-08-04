"""Tests for RAG document loaders."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from thumbelina.rag.ingestion.loader import HTMLLoader, LoaderRegistry, TextLoader
from thumbelina.rag.common.models import DocumentType


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
        """TextLoader 和 HTMLLoader 应自动注册。"""
        names = LoaderRegistry.list_registered()
        assert "TextLoader" in names
        assert "HTMLLoader" in names

    def test_supported_extensions(self):
        """已注册 Loader 的扩展名应全部可查。"""
        exts = LoaderRegistry.list_supported_extensions()
        assert ".txt" in exts
        assert ".md" in exts
        assert ".html" in exts
        assert ".htm" in exts

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

    def test_find_unsupported_extension_raises(self):
        with pytest.raises(ValueError, match="不支持的文件类型"):
            LoaderRegistry.find("/some/path/doc.pdf")

    def test_find_returns_new_instance_each_time(self):
        """每次调用 find() 应返回新实例。"""
        l1 = LoaderRegistry.find("/a.md")
        l2 = LoaderRegistry.find("/b.md")
        assert l1 is not l2
