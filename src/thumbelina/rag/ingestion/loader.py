"""文档加载器：从不同来源读取文档内容。

规划中的加载器
--------------
- TextLoader：加载纯文本文件
- PDFLoader：解析 PDF 文档（基于 PyMuPDF / pdfplumber）
- HTMLLoader：抓取并解析网页内容
- CodeLoader：加载源代码文件，附带语言类型元数据
- DirectoryLoader：批量加载指定目录下所有支持的文档
"""

import hashlib
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar

import requests
from bs4 import BeautifulSoup
from simhash import Simhash

from thumbelina.rag.knowledge_base.models import Document, DocumentType


class LoaderRegistry:
    """Loader 注册中心 —— 根据文件扩展名 / URL 协议自动匹配具体 Loader。

    所有 Loader 子类在定义时自动注册，无需手动干预。
    调用方只需传入路径，注册中心自动匹配合适的 Loader 并实例化。

    用法::

        loader = LoaderRegistry.find("/path/to/doc.md")   # → TextLoader
        loader = LoaderRegistry.find("https://...")        # → HTMLLoader
        loader = LoaderRegistry.find("/path/to/doc.pdf")   # → PDFLoader
    """

    _loaders: ClassVar[list[type["Loader"]]] = []

    @classmethod
    def register(cls, loader_cls: type["Loader"]) -> type["Loader"]:
        """注册一个 Loader 类。Loader 子类在定义时自动调用，无需手动触发。"""
        cls._loaders.append(loader_cls)
        return loader_cls

    @classmethod
    def find(cls, path: str) -> "Loader":
        """根据路径自动选择并实例化合适的 Loader。

        匹配优先级：
        1. URL 协议（http/https）→ 匹配 supports_urls=True 的 Loader
        2. 文件扩展名 → 匹配 extensions 中包含该后缀的 Loader
        3. 未匹配时抛出 ValueError

        Raises
        ------
        ValueError
            当路径无法匹配任何已注册的 Loader 时抛出。
        """
        # 1. URL 检测
        if path.lower().startswith(("http://", "https://")):
            for loader_cls in cls._loaders:
                if getattr(loader_cls, "supports_urls", False):
                    return loader_cls()
            raise ValueError(f"没有支持 URL 抓取的 Loader，路径: {path}")

        # 2. 文件扩展名检测
        ext = Path(path).suffix.lower()
        for loader_cls in cls._loaders:
            if ext in loader_cls.extensions:
                return loader_cls()

        supported = cls.list_supported_extensions()
        raise ValueError(
            f"不支持的文件类型 '{ext}'，路径: {path}。"
            f"已支持的类型: {sorted(supported)}"
        )

    @classmethod
    def list_supported_extensions(cls) -> set[str]:
        """返回所有已注册 Loader 支持的文件扩展名集合。"""
        result: set[str] = set()
        for loader_cls in cls._loaders:
            result.update(loader_cls.extensions)
        return result

    @classmethod
    def list_registered(cls) -> list[str]:
        """返回所有已注册 Loader 的类名列表（调试用）。"""
        return [loader_cls.__name__ for loader_cls in cls._loaders]


class Loader(ABC):
    """文档加载器接口 —— 子类自动注册到 LoaderRegistry。"""

    # 文档加载器支持的文件后缀类型
    extensions: ClassVar[list[str]] = []
    # 是否支持从 URL 抓取内容
    supports_urls: ClassVar[bool] = False

    def __init_subclass__(cls, **kwargs: object) -> None:
        """子类定义时自动注册到 LoaderRegistry。"""
        super().__init_subclass__(**kwargs)
        LoaderRegistry.register(cls)

    @abstractmethod
    def load(self, path: str) -> list[Document]:
        """加载文档"""

    def _get_sha256(self, content: str) -> bytes:
        return hashlib.sha256(content.encode()).digest()

    def _get_sim_hash_64(self, content: str) -> bytes:
        # 依赖三方库实现，默认返回是64位
        return Simhash(content).value.to_bytes(8, "big")


class TextLoader(Loader):
    """纯文本文档加载器"""

    # TODO 还需要优化下MARKDOWN的Loader，单独抽取出来，针对表格数据进行处理
    extensions: ClassVar[list[str]] = [
        DocumentType.TXT.value, DocumentType.MARKDOWN.value]

    def load(self, path: str) -> list[Document]:
        path_obj = Path(path)
        if not (
            path_obj.exists() and path_obj.is_file(
            ) and path_obj.suffix.lower() in self.extensions
        ):
            raise TypeError(f"Invalid file: {path}")

        content = str(path_obj.read_text(encoding="utf-8"))

        return [
            Document(
                id=uuid.uuid4().hex,
                name=path_obj.name,
                source_uri=str(path_obj.resolve()),
                document_type=DocumentType.from_value(path_obj.suffix),
                content=content,
                sha256=self._get_sha256(content),
                sim_hash_64=self._get_sim_hash_64(content),
            )
        ]


class PdfLoader(Loader):
    """PDF文档加载器"""

    extensions: ClassVar[list[str]] = [DocumentType.PDF.value]

    def load(self, path: str) -> list[Document]:
        path_obj = Path(path)
        if not (
            path_obj.exists() and path_obj.is_file(
            ) and path_obj.suffix.lower() in self.extensions
        ):
            raise TypeError(f"Invalid file: {path}")

        """TODO 
        PDF 文档需要处理的问题:
            1. 可能包含如下三类PDF文件：纯文本、纯扫描件、文本+扫描件
            2. 可能包含表格，表格可能翻页
        """


class HTMLLoader(Loader):
    """
    HTML文档加载器
        支持本地文件和网络文件两种上传方式。
        由于html存在大量无关的标签和噪音（如导航栏、广告），因此需要进行数据清洗
        这里选择BeautifulSoup作为清洗方案，实际可以考虑用再用小模型进行一次数据清洗，保证文档质量
    """

    extensions: ClassVar[list[str]] = [
        DocumentType.HTML.value, DocumentType.HTM.value]
    supports_urls: ClassVar[bool] = True  # 支持从 URL 抓取网页内容

    def load(self, path: str) -> list[Document]:
        if path.lower().startswith(("http://", "https://")):
            return self._load_by_url(path=path)
        return self._load_file(path=path)

    def _load_file(self, path: str) -> list[Document]:
        path_obj = Path(path)
        if not (
            path_obj.exists() and path_obj.is_file(
            ) and path_obj.suffix.lower() in self.extensions
        ):
            raise TypeError(f"Invalid file: {path}")
        content = path_obj.read_text(encoding="utf-8")
        text = self._clear_html_data(content=content)

        return [
            Document(
                id=uuid.uuid4().hex,
                name=path_obj.name,
                source_uri=str(path_obj.resolve()),
                document_type=DocumentType.HTML,
                content=text,
                sha256=self._get_sha256(text),
                sim_hash_64=self._get_sim_hash_64(text),
            )
        ]

    def load_url(self, url: str) -> list[Document]:
        """公开方法：从 URL 抓取并解析网页内容。"""
        if not url.lower().startswith(("http://", "https://")):
            raise ValueError(f"Invalid URL: {url}")
        return self._load_by_url(path=url)

    def _load_by_url(self, path: str) -> list[Document]:
        resp = requests.get(url=path, timeout=10)
        resp.raise_for_status()

        # 传原始字节给 BeautifulSoup，由其自动检测编码，
        # 避免 requests 在缺少 charset 时回退 ISO-8859-1 导致中文乱码
        text = self._clear_html_data(resp.content)
        return [
            Document(
                id=uuid.uuid4().hex,
                name=path.split("/")[-1] or "webpage",
                source_uri=path,
                document_type=DocumentType.HTML,
                content=text,
                sha256=self._get_sha256(text),
                sim_hash_64=self._get_sim_hash_64(text),
            )
        ]

    def _clear_html_data(self, content: str | bytes) -> str:
        # 提纯纯文本，移除script/stype，获取body文本
        soup = BeautifulSoup(content, "html.parser")

        # 移除无关标签
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        return soup.get_text(separator="\n", strip=True)


if __name__ == "__main__":
    BASE_DIR = Path(__file__).parent

    # 注册器自动匹配：根据文件扩展名选择合适的 Loader
    print(f"已注册 Loader: {LoaderRegistry.list_registered()}")
    print(f"支持的扩展名: {sorted(LoaderRegistry.list_supported_extensions())}")

    TEST_FILE = str(BASE_DIR / ".." / "demo" / "data" / "doc.md")
    loader = LoaderRegistry.find(TEST_FILE)
    print(f"\n{TEST_FILE} → {type(loader).__name__}")
    docs = loader.load(TEST_FILE)
    for i, document in enumerate(docs):
        print(f"[{i}]: {document}\n")
