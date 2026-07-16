"""文档加载器：从不同来源读取文档内容。

规划中的加载器
--------------
- TextLoader：加载纯文本文件
- PDFLoader：解析 PDF 文档（基于 PyMuPDF / pdfplumber）
- HTMLLoader：抓取并解析网页内容
- CodeLoader：加载源代码文件，附带语言类型元数据
- DirectoryLoader：批量加载指定目录下所有支持的文档
"""

from abc import ABC, abstractmethod
from llama_index.core import SimpleDirectoryReader
from llama_index_client import Document


class Loader(ABC):
    @abstractmethod
    def load(self, path: str) -> list[Document]:
        pass


class TextLoader(Loader):
    def load(self, path) -> list[Document]:
        return SimpleDirectoryReader(path).load_data()

# test code, need delete
path = "src/thumbelina/rag/demo/data"
loader = TextLoader()
documents = loader.load(path)
for i, document in enumerate(documents):
    print(f"[{i}]: {document}\n")
