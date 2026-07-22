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
from thumbelina.rag.knowledge_base.models import Document, DocumentType


class Loader(ABC):
    """文档加载器接口"""
    # 文档加载器支持的文件后缀类型
    extensions: list[str] = []

    @abstractmethod
    def load(self, path: str) -> list[Document]:
        """加载文档"""


class TextLoader(Loader):
    extensions: list[str] = [".txt", ".md"]

    def load(self, path: str) -> list[Document]:
        path_obj = Path(path)
        if not (path_obj.exists() and path_obj.is_file() and path_obj.suffix.lower() in self.extensions):
            return []
        
        documents: list[Document] = []
        documents.append(Document(
            id=uuid.uuid4().hex,
            name=path_obj.name,
            source_uri=str(path_obj.resolve()),
            document_type=DocumentType.from_value(path_obj.suffix),
            content=str(path_obj.read_text(encoding="utf-8"))
        ))
        return documents
    
    # TODO 新增方法，根据文件后缀动态选择loader


if __name__ == "__main__":
    BASE_DIR = Path(__file__).parent
    TEST_FILE = str(BASE_DIR / ".." / "demo" / "data" / "doc.md")
    loader = TextLoader()
    docs = loader.load(TEST_FILE)
    for i, document in enumerate(docs):
        print(f"[{i}]: {document}\n")
