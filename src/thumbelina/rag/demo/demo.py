import os
import sys

# Windows 终端 UTF-8 编码修复
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
from llama_index.core import Settings, SimpleDirectoryReader, VectorStoreIndex
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.llms.openai_like import OpenAILike

load_dotenv()

Settings.llm = OpenAILike(
    model="deepseek-v4-flash",
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    api_base="https://api.deepseek.com",
    is_chat_model=True,
)

# 使用本地下载的模型（从 hf-mirror.com 预先下载）
model_path = os.path.expanduser("~/.cache/bge-model")
Settings.embed_model = HuggingFaceEmbedding(model_name=model_path, device="cpu")

documents = SimpleDirectoryReader(input_files=["./data/easy-rl-chapter1.md"]).load_data()

index = VectorStoreIndex.from_documents(documents)

query_engine = index.as_query_engine()

print(query_engine.get_prompts())

print(query_engine.query("文中举了哪些例子?"))
