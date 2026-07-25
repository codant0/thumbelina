"""文档加载器：从不同来源读取文档内容。

规划中的加载器
--------------
- TextLoader：加载纯文本文件
- PDFLoader：解析 PDF 文档（基于 PyMuPDF / pdfplumber）
- HTMLLoader：抓取并解析网页内容
- CodeLoader：加载源代码文件，附带语言类型元数据
- DirectoryLoader：批量加载指定目录下所有支持的文档
"""

import uuid
from abc import ABC, abstractmethod
from pathlib import Path

import requests
from thumbelina.rag.knowledge_base.models import Document, DocumentType
from bs4 import BeautifulSoup


class Loader(ABC):
    """文档加载器接口"""

    # 文档加载器支持的文件后缀类型
    extensions: list[str] = []

    @abstractmethod
    def load(self, path: str) -> list[Document]:
        """加载文档"""


class TextLoader(Loader):
    """纯文本文档加载器"""

    extensions: list[str] = [DocumentType.TXT.value, DocumentType.MARKDOWN.value]

    def load(self, path: str) -> list[Document]:
        path_obj = Path(path)
        if not (
            path_obj.exists() and path_obj.is_file() and path_obj.suffix.lower() in self.extensions
        ):
            raise TypeError(f"Invalid file: {path}")

        documents: list[Document] = []
        documents.append(
            Document(
                id=uuid.uuid4().hex,
                name=path_obj.name,
                source_uri=str(path_obj.resolve()),
                document_type=DocumentType.from_value(path_obj.suffix),
                content=str(path_obj.read_text(encoding="utf-8")),
            )
        )
        return documents

    # TODO 新增方法，根据文件后缀动态选择loader


class HTMLLoader(Loader):
    """
    HTML文档加载器
        支持本地文件和网络文件两种上传方式。
        由于html存在大量无关的标签和噪音（如导航栏、广告），因此需要进行数据清洗
        这里选择BeautifulSoup作为清洗方案，实际可以考虑用再用小模型进行一次数据清洗，保证文档质量
    """

    extensions: list[str] = [DocumentType.HTML.value, DocumentType.HTM.value]

    def load(self, path: str) -> list[Document]:
        if path.lower().startswith(("http://", "https://")):
            return self._load_by_url(path=path)
        return self._load_file(path=path)

    def _load_file(self, path: str) -> list[Document]:
        path_obj = Path(path)
        if not (
            path_obj.exists() and path_obj.is_file() and path_obj.suffix.lower() in self.extensions
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
            )
        ]

    def _load_by_url(self, path: str) -> list[Document]:
        resp = requests.get(url=path, timeout=10)
        resp.raise_for_status()

        text = self._clear_html_data(resp.text)
        return [
            Document(
                id=uuid.uuid4().hex,
                name=path.split("/")[-1] or "webpage",
                source_uri=path,
                document_type=DocumentType.HTML,
                content=text,
            )
        ]

    def _clear_html_data(self, content: str) -> str:
        # 提纯纯文本，移除script/stype，获取body文本
        soup = BeautifulSoup(content, "html.parser")

        # 移除无关标签
        for tag in soup(["script", "stype", "nav", "footer", "header"]):
            tag.decompose()

        return soup.get_text(separator="\n", strip=True)


if __name__ == "__main__":
    BASE_DIR = Path(__file__).parent
    TEST_FILE = str(BASE_DIR / ".." / "demo" / "data" / "doc.md")
    loader = TextLoader()
    docs = loader.load(TEST_FILE)
    for i, document in enumerate(docs):
        print(f"[{i}]: {document}\n")
