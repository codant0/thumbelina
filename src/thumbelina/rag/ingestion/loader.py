"""文档加载器：从不同来源读取文档内容。

规划中的加载器
--------------
- TextLoader：加载纯文本文件
- PDFLoader：解析 PDF 文档（基于 PyMuPDF，扫描件可选 PaddleOCR 兜底）
- HTMLLoader：抓取并解析网页内容
- CodeLoader：加载源代码文件，附带语言类型元数据
- DirectoryLoader：批量加载指定目录下所有支持的文档
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

import requests
from bs4 import BeautifulSoup
from simhash import Simhash

from thumbelina.rag.common.models import Document, DocumentType, PageSpan, PdfPageType

if TYPE_CHECKING:
    from paddleocr import PaddleOCR

logger = logging.getLogger(__name__)

# PaddleOCR 引擎单例：初始化耗时数秒（加载模型），跨 Loader 实例共享
_OCR_ENGINE: PaddleOCR | None = None
# 标记 OCR 不可用（未安装或初始化失败），避免逐页重复探测
_OCR_UNAVAILABLE = False


def _get_ocr_engine() -> PaddleOCR | None:
    """懒加载并缓存 PaddleOCR 引擎；不可用（未安装/初始化失败）时返回 None。"""
    global _OCR_ENGINE, _OCR_UNAVAILABLE
    if _OCR_UNAVAILABLE:
        return None
    if _OCR_ENGINE is None:
        try:
            from paddleocr import PaddleOCR as _PaddleOCR
        except ImportError:
            logger.warning(
                "paddleocr 未安装，扫描件页面将被跳过。"
                "如需扫描件处理请安装: pip install -e '.[rag-ocr]'"
            )
            _OCR_UNAVAILABLE = True
            return None
        try:
            _OCR_ENGINE = _PaddleOCR(
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
            )
        except Exception as exc:  # 缺少 paddlepaddle、模型下载失败等
            logger.warning("PaddleOCR 初始化失败，扫描件页面将被跳过: %s", exc)
            _OCR_UNAVAILABLE = True
            return None
    return _OCR_ENGINE


def _is_cjk(char: str) -> bool:
    """粗略判断字符是否为中文（CJK 统一表意文字）。"""
    return "一" <= char <= "鿿" or "㐀" <= char <= "䶿"


def _join_box_texts(texts: list[str]) -> str:
    """拼接同一行内相邻文本框的文本：中文相邻无需空格，西文之间补空格。"""
    result = texts[0]
    for text in texts[1:]:
        if _is_cjk(result[-1]) or _is_cjk(text[0]):
            result += text
        else:
            result += " " + text
    return result


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
    """PDF 文档加载器。

    支持三类 PDF：纯文本、纯扫描件、文本+扫描件混合：

    - 有文本层的页面直接用 PyMuPDF 提取；
    - 扫描件页面（文字稀疏且图片覆盖大部分页面）回退到 PaddleOCR 识别
      （需安装 rag-ocr 可选依赖，否则跳过并告警）；
    - 页码不写入正文，而是记录每页文本在 content 中的偏移区间
      （``page_spans``），由分块器按偏移反查 chunk 页码，
      避免页码标记割裂跨页语义、污染向量。

    TODO 表格未进行优化：后续可用 page.find_tables() 提取表格并整体成块，
    扫描件表格走 PP-Structure 表格识别。
    """

    extensions: ClassVar[list[str]] = [DocumentType.PDF.value]

    # 稀疏文本阈值：页面字符数少于此值认为文字稀疏
    SPARSE_TEXT_CHARS: ClassVar[int] = 20
    # 扫描件判定的图片覆盖阈值：图片面积超过页面该比例视为图片主导
    SCANNED_IMAGE_COVER: ClassVar[float] = 0.6
    # OCR 渲染图像 DPI（200 兼顾识别率与性能，小字体文档可调至 300）
    OCR_DPI: ClassVar[int] = 200
    # 过滤置信度低于该阈值的 OCR 文本框
    OCR_MIN_SCORE: ClassVar[float] = 0.5

    def load(self, path: str) -> list[Document]:
        path_obj = Path(path)
        if not (
            path_obj.exists() and path_obj.is_file()
            and path_obj.suffix.lower() in self.extensions
        ):
            raise TypeError(f"Invalid file: {path}")

        try:
            import pymupdf
        except ImportError as exc:
            raise RuntimeError(
                "PDF 加载需要 pymupdf: pip install -e '.[rag]'"
            ) from exc

        doc = pymupdf.open(path)
        try:
            parts: list[str] = []
            page_texts: list[str] = []
            page_spans: list[PageSpan] = []
            offset = 0
            for index, page in enumerate(doc):
                page_no = index + 1
                page_text = self._extract_page_text(page, page_no)
                if not page_text:
                    logger.warning(
                        "第 %d 页无可提取文本（扫描件需安装 rag-ocr 可选依赖），已跳过: %s",
                        page_no, path,
                    )
                    continue
                if parts:
                    offset += 1  # 页面间用 "\n" 连接
                start = offset
                parts.append(page_text)
                offset += len(page_text)
                page_texts.append(page_text)
                page_spans.append(PageSpan(page=page_no, start=start, end=offset))

            content = "\n".join(parts)
            if not content:
                logger.warning("PDF 无任何可提取内容: %s", path)
                return []
            return [
                Document(
                    id=uuid.uuid4().hex,
                    name=path_obj.name,
                    source_uri=str(path_obj.resolve()),
                    document_type=DocumentType.PDF,
                    content=content,
                    page_text=page_texts,
                    page_count=doc.page_count,
                    page_spans=page_spans,
                    sha256=self._get_sha256(content),
                    sim_hash_64=self._get_sim_hash_64(content),
                )
            ]
        finally:
            doc.close()

    def _extract_page_text(self, page: Any, page_no: int) -> str:
        """提取单页文本：优先文本层；扫描件页面回退到 OCR。"""
        text: str = page.get_text("text").strip()
        if self._classify_page(page, text) == PdfPageType.SCANNED:
            # 纯扫描页：文本层不可用，交由 OCR 识别；OCR 无结果时退回原文本
            return self._ocr_page(page, page_no) or text
        # TEXT / MIXED：文本层可用（MIXED 页文字充足，图片仅为配图）
        return text

    def _classify_page(self, page: Any, text: str) -> PdfPageType:
        """判定页面类型：文字稀疏且图片覆盖大部分页面 → 扫描件。

        图片主导但文字充足 → MIXED（文本层仍是主要来源）；其余 → TEXT。
        """
        page_area = float(page.rect.width * page.rect.height)
        if page_area <= 0:
            return PdfPageType.TEXT
        sparse_text = len(text) < self.SPARSE_TEXT_CHARS
        image_area = sum(
            max(0.0, img["bbox"][2] - img["bbox"][0])
            * max(0.0, img["bbox"][3] - img["bbox"][1])
            for img in page.get_image_info()
        )
        image_dominant = image_area > self.SCANNED_IMAGE_COVER * page_area
        if sparse_text and image_dominant:
            return PdfPageType.SCANNED
        if image_dominant:
            return PdfPageType.MIXED
        return PdfPageType.TEXT

    def _ocr_page(self, page: Any, page_no: int) -> str:
        """使用 PaddleOCR 识别扫描件页面文本；引擎不可用或失败时返回空串。"""
        engine = _get_ocr_engine()
        if engine is None:
            return ""
        try:
            import numpy as np

            # alpha=False 输出 RGB 三通道，可直接转 numpy 数组
            pix = page.get_pixmap(dpi=self.OCR_DPI, alpha=False)
            image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                pix.height, pix.width, pix.n
            ).copy()  # frombuffer 结果只读，复制一份供预处理写入
            results = engine.predict(image)
        except Exception:
            logger.warning("第 %d 页 OCR 识别失败", page_no, exc_info=True)
            return ""
        return self._ocr_results_to_text(results)

    @staticmethod
    def _ocr_results_to_text(results: Any) -> str:
        """将 OCR 文本框按阅读顺序（先上下、后左右）重组为文本。

        OCR 输出为无序文本框集合：按 y 坐标聚行、行内按 x 排序，
        并过滤低置信度框。
        """
        # (y 中心, x 最小值, 框高, 文本)
        boxes: list[tuple[float, float, float, str]] = []
        for res in results or []:
            try:
                rec_texts = res["rec_texts"]
                rec_scores = res["rec_scores"]
                rec_polys = res["rec_polys"]
            except (KeyError, TypeError):
                continue
            for text, score, poly in zip(rec_texts, rec_scores, rec_polys):
                text = str(text).strip()
                if not text or score < PdfLoader.OCR_MIN_SCORE:
                    continue
                xs = [float(pt[0]) for pt in poly]
                ys = [float(pt[1]) for pt in poly]
                boxes.append(
                    ((min(ys) + max(ys)) / 2, min(xs), max(max(ys) - min(ys), 1.0), text)
                )
        if not boxes:
            return ""

        boxes.sort(key=lambda b: (b[0], b[1]))
        heights = sorted(b[2] for b in boxes)
        median_h = heights[len(heights) // 2]

        lines: list[list[tuple[float, float, float, str]]] = []
        for box in boxes:
            # 与上一文本框垂直距离不超过 0.6 倍行高（中位数）时视为同一行
            if lines and abs(box[0] - lines[-1][-1][0]) <= median_h * 0.6:
                lines[-1].append(box)
            else:
                lines.append([box])
        return "\n".join(_join_box_texts([box[3] for box in line]) for line in lines)


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
