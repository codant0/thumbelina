"""文档加载器：从不同来源读取文档内容。

规划中的加载器
--------------
- TextLoader：加载纯文本文件
- PDFLoader：解析 PDF 文档（基于 PyMuPDF / pdfplumber）
- HTMLLoader：抓取并解析网页内容
- CodeLoader：加载源代码文件，附带语言类型元数据
- DirectoryLoader：批量加载指定目录下所有支持的文档
"""
