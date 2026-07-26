"""RAG 模块数据库引擎和初始化。"""

from __future__ import annotations

import logging

from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from thumbelina.rag.knowledge_base.orm_models import (
    KnowledgeBaseRecord,
    RagBase,
)

logger = logging.getLogger(__name__)

_DEFAULT_KB_ID = "0"
_DEFAULT_KB_NAME = "通用知识库"
_DEFAULT_KB_DESC = "通用知识库，默认使用该知识库"


def _load_sqlite_vec(
    dbapi_conn: object, connection_record: object, connection_proxy: object = None
) -> None:
    """在每个 SQLite 连接从连接池中取出时自动加载 sqlite-vec 扩展。

    使用 ``checkout`` 事件而非 ``connect``，确保从池中复用的旧连接也会被加载。
    通过 ``connection_record.info`` 标记避免重复加载。
    """
    if connection_record.info.get("sqlite_vec_loaded"):
        return
    try:
        import sqlite3

        import sqlite_vec

        conn = dbapi_conn  # type: ignore[assignment]
        if isinstance(conn, sqlite3.Connection):
            conn.enable_load_extension(True)
            sqlite_vec.load(conn)
            conn.enable_load_extension(False)
            connection_record.info["sqlite_vec_loaded"] = True
    except ImportError:
        logger.warning("sqlite-vec 未安装，SimHash 距离查询功能不可用")
    except Exception as exc:
        logger.warning("加载 sqlite-vec 扩展失败: %s", exc)


def init_rag_db(engine: Engine) -> sessionmaker[Session]:
    """创建 RAG 表并植入默认知识库，返回会话工厂。

    同时加载 sqlite-vec 扩展并创建 simhash_index 虚拟表。

    Parameters
    ----------
    engine:
        SQLAlchemy Engine 实例，可以和 memory 模块共享同一个 SQLite 文件。

    Returns
    -------
    sessionmaker[Session]
        绑定到该引擎的会话工厂。
    """
    # 使用 checkout 事件而非 connect，确保从连接池复用的旧连接也会加载扩展。
    # connect 事件仅在创建新 DBAPI 连接时触发，已存在池中的连接不会被处理。
    event.listen(engine, "checkout", _load_sqlite_vec)

    RagBase.metadata.create_all(engine)
    _migrate_sha256_simhash_to_blob(engine)
    _create_simhash_index(engine)
    _create_chunk_fingerprints_table(engine)
    _ensure_default_knowledge_base(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _create_simhash_index(engine: Engine) -> None:
    """创建 simhash_index 虚拟表（如果不存在）。

    使用 float[64] 类型存储 SimHash 的二进制向量（每个 bit 展开为一个 float）。
    对于 0/1 二进制向量，L2 距离的平方 = 汉明距离。
    """
    try:
        with engine.connect() as conn:
            conn.execute(
                text(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS simhash_index"
                    " USING vec0(document_id TEXT PRIMARY KEY, simhash_embedding float[64])"
                )
            )
            conn.commit()
        logger.info("simhash_index 虚拟表就绪")
    except Exception as exc:
        logger.warning("创建 simhash_index 虚拟表失败（sqlite-vec 可能未安装）: %s", exc)


def _migrate_sha256_simhash_to_blob(engine: Engine) -> None:
    """确保 rag_documents 表包含 sha256 / sim_hash_64 两个 BLOB 列。

    处理两种旧 schema：
    - 列不存在：直接 ADD COLUMN（默认空 bytes）
    - 列存在但为 VARCHAR：重建表，将十六进制字符串转为 bytes

    SQLite 不支持 ALTER COLUMN，第二种情况采用重建表的方式。
    """
    try:
        with engine.connect() as conn:
            # 检查 rag_documents 表是否存在
            table_info = conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name='rag_documents'")
            ).fetchone()
            if table_info is None:
                return  # 表不存在，首次创建由 create_all 处理

            # 检查 sha256 列是否存在及其类型
            columns = conn.execute(text("PRAGMA table_info(rag_documents)")).fetchall()
            col_names = {c[1] for c in columns}
            sha256_col = next((c for c in columns if c[1] == "sha256"), None)

            if sha256_col is None:
                # 列不存在，直接添加（旧表无此列）
                logger.info("rag_documents 缺少 sha256/sim_hash_64 列，正在添加...")
                conn.execute(text(
                    "ALTER TABLE rag_documents ADD COLUMN sha256 BLOB NOT NULL DEFAULT x''"
                ))
                if "sim_hash_64" not in col_names:
                    conn.execute(text(
                        "ALTER TABLE rag_documents ADD COLUMN sim_hash_64 BLOB NOT NULL DEFAULT x''"
                    ))
                conn.commit()
                logger.info("rag_documents 新列添加完成")
                return

            col_type = sha256_col[2]  # type 列
            if col_type.upper() == "BLOB":
                return  # 已经是 BLOB，无需迁移

            # 列存在但为 VARCHAR，需要重建表迁移
            logger.info("检测到旧 schema（%s），开始迁移 rag_documents 表...", col_type)

            # 1. 重命名旧表
            conn.execute(text("ALTER TABLE rag_documents RENAME TO rag_documents_old"))

            # 2. 用新 schema 创建表
            conn.execute(
                text("""
                CREATE TABLE rag_documents (
                    id VARCHAR(36) NOT NULL,
                    knowledge_base_id VARCHAR(36) NOT NULL,
                    name VARCHAR(500) NOT NULL,
                    source_uri VARCHAR(1000) NOT NULL,
                    doc_type VARCHAR(20) NOT NULL,
                    sha256 BLOB NOT NULL,
                    sim_hash_64 BLOB NOT NULL,
                    chunk_count INTEGER NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                    PRIMARY KEY (id),
                    FOREIGN KEY(knowledge_base_id) REFERENCES knowledge_bases (id) ON DELETE CASCADE
                )
            """)
            )

            # 3. 迁移数据：十六进制字符串 → bytes
            rows = conn.execute(
                text(
                    "SELECT id, knowledge_base_id, name, source_uri, doc_type, "
                    "sha256, sim_hash_64, chunk_count, created_at FROM rag_documents_old"
                )
            ).fetchall()

            for row in rows:
                sha256_val = row[5]
                simhash_val = row[6]
                sha256_bytes = (
                    bytes.fromhex(sha256_val) if isinstance(sha256_val, str) else sha256_val
                )
                simhash_bytes = (
                    bytes.fromhex(simhash_val) if isinstance(simhash_val, str) else simhash_val
                )
                conn.execute(
                    text(
                        "INSERT INTO rag_documents"
                        " (id, knowledge_base_id, name, source_uri, doc_type,"
                        " sha256, sim_hash_64, chunk_count, created_at)"
                        " VALUES (:id, :kb_id, :name, :uri, :dtype,"
                        " :sha, :sim, :cc, :created)"
                    ),
                    {
                        "id": row[0],
                        "kb_id": row[1],
                        "name": row[2],
                        "uri": row[3],
                        "dtype": row[4],
                        "sha": sha256_bytes,
                        "sim": simhash_bytes,
                        "cc": row[7],
                        "created": row[8],
                    },
                )

            # 4. 删除旧表
            conn.execute(text("DROP TABLE rag_documents_old"))
            conn.commit()
            logger.info("rag_documents 表迁移完成，共迁移 %d 条记录", len(rows))

    except Exception as exc:
        logger.error("rag_documents 表迁移失败: %s", exc)
        raise


def _create_chunk_fingerprints_table(engine: Engine) -> None:
    """创建 chunk 指纹表及索引（如果不存在）。

    用于分块级去重：存储每个 chunk 的 SHA-256 哈希和 MinHash 签名。
    文档删除时通过外键级联清理。
    """
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS rag_chunk_fingerprints (
                    id            TEXT PRIMARY KEY,
                    document_id   TEXT NOT NULL,
                    kb_id         TEXT NOT NULL,
                    content_hash  BLOB NOT NULL,
                    minhash_sig   BLOB,
                    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (document_id) REFERENCES rag_documents(id) ON DELETE CASCADE
                )
            """))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_chunk_fingerprint_hash "
                "ON rag_chunk_fingerprints(content_hash)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_chunk_fingerprint_kb "
                "ON rag_chunk_fingerprints(kb_id)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_chunk_fingerprint_doc "
                "ON rag_chunk_fingerprints(document_id)"
            ))
        logger.info("rag_chunk_fingerprints 表就绪")
    except Exception as exc:
        logger.warning("创建 rag_chunk_fingerprints 表失败: %s", exc)


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
