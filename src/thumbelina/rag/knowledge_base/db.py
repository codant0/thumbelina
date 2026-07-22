"""RAG 模块数据库引擎和初始化。"""

from __future__ import annotations

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from thumbelina.rag.knowledge_base.orm_models import (
    KnowledgeBaseRecord,
    RagBase,
)

_DEFAULT_KB_ID = "0"
_DEFAULT_KB_NAME = "通用知识库"
_DEFAULT_KB_DESC = "通用知识库，默认使用该知识库"


def init_rag_db(engine: Engine) -> sessionmaker[Session]:
    """创建 RAG 表并植入默认知识库，返回会话工厂。

    Parameters
    ----------
    engine:
        SQLAlchemy Engine 实例，可以和 memory 模块共享同一个 SQLite 文件。

    Returns
    -------
    sessionmaker[Session]
        绑定到该引擎的会话工厂。
    """
    RagBase.metadata.create_all(engine)
    _ensure_default_knowledge_base(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _ensure_default_knowledge_base(engine: Engine) -> None:
    """如果 id='0' 的通用知识库不存在则自动创建。"""
    with Session(engine) as session:
        existing = session.get(KnowledgeBaseRecord, _DEFAULT_KB_ID)
        if existing is None:
            session.add(
                KnowledgeBaseRecord(
                    id=_DEFAULT_KB_ID,
                    name=_DEFAULT_KB_NAME,
                    description=_DEFAULT_KB_DESC,
                )
            )
            session.commit()
