import os
import sys

# Windows 终端 UTF-8 编码修复
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

# 修复 OpenMP 运行时冲突（PyTorch + ONNX Runtime）
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

from dotenv import load_dotenv  # noqa: E402
from llama_index.core import Settings, SimpleDirectoryReader, VectorStoreIndex  # noqa: E402
from llama_index.core.node_parser import SimpleNodeParser  # noqa: E402
from llama_index.embeddings.huggingface import HuggingFaceEmbedding  # noqa: E402
from llama_index.llms.openai_like import OpenAILike  # noqa: E402

load_dotenv()

Settings.llm = OpenAILike(
    model="deepseek-v4-flash",
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    api_base="https://api.deepseek.com",
    is_chat_model=True,
)

# os.environ['HF_ENDPOINT']='https://hf-mirror.com'
# 设置向量数据库嵌入模型，负责将文本块转化为向量
# Settings.embed_model = HuggingFaceEmbedding("BAAI/bge-small-zh-v1.5")

# 使用本地下载的模型（从 hf-mirror.com 预先下载）
model_path = os.path.expanduser("~/.cache/bge-model")
Settings.embed_model = HuggingFaceEmbedding(model_name=model_path, device="cpu")

# 数据准备-加载原始文档
_input = "src/thumbelina/rag/demo/data/easy-rl-chapter1.md"
documents = SimpleDirectoryReader(input_files=[_input]).load_data()

# 将文档解析为节点
parser = SimpleNodeParser()
nodes = parser.get_nodes_from_documents(documents)

# 构建向量索引，根据文档切块，在内存中构建索引
index = VectorStoreIndex.from_documents(documents)

# # 可选-持久化索引：
# from llama_index import StorageContext, load_index_from_storage
# # 重建存储上下文
# storage_context = StorageContext.from_defaults(persist_dir="<persist_dir>")
# # 加载索引
# index = load_index_from_storage(storage_context)

# 设置查询引擎
query_engine = index.as_query_engine()

print(query_engine.get_prompts())

print(query_engine.query("文中举了哪些例子?"))
