"""Repository for conversation and message data access."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session, joinedload

from thumbelina.repository.models import Conversation, Message

if TYPE_CHECKING:
    from thumbelina.repository.models import Attachment

logger = logging.getLogger(__name__)

# Valid roles for messages
VALID_ROLES = {"user", "assistant", "system"}


def _serialize_attachments(attachments: list[dict[str, Any]] | None) -> str | None:
    """把附件引用列表序列化为 JSON 字符串(存入 ``Message.attachments``)。

    ``None`` 或空列表返回 ``None``(列保持 NULL,与老消息统一);
    序列化失败兜底返回 ``None`` 并记 warning,不炸写路径。
    """
    if not attachments:
        return None
    try:
        return json.dumps(attachments, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        logger.warning("Failed to serialize message attachments: %s", exc)
        return None


def _deserialize_attachments(raw: str | None) -> list[dict[str, Any]] | None:
    """把 ``Message.attachments`` 列反序列化为附件引用字典列表。

    空/``None``/坏 JSON/非 list/过滤后为空 → ``None``;
    否则只保留 ``isinstance(item, dict)`` 的元素(坏 JSON 不炸读路径)。
    """
    if not raw:
        return None
    try:
        parsed: Any = json.loads(raw)
    except (ValueError, TypeError):
        logger.debug("Ignoring malformed message attachments JSON: %r", raw[:100])
        return None
    if not isinstance(parsed, list):
        return None
    items = [item for item in parsed if isinstance(item, dict)]
    return items or None


def _attachment_to_dict(att: Attachment) -> dict[str, Any]:
    """把 ``Attachment`` ORM 行转为普通字典(created_at 为 isoformat 或 None)。"""
    return {
        "id": att.id,
        "mime": att.mime,
        "size": att.size,
        "width": att.width,
        "height": att.height,
        "sha256": att.sha256,
        "relative_path": att.relative_path,
        "created_at": att.created_at.isoformat() if att.created_at else None,
    }


class ConversationRepository:
    """Repository for managing conversations and messages.

    Parameters
    ----------
    db_url:
        SQLAlchemy database URL (e.g., "sqlite:///thumbelina.db").
    """

    def __init__(self, db_url: str) -> None:
        from thumbelina.repository.db import create_db_engine, init_db

        self.engine = create_db_engine(db_url)
        self.SessionLocal = init_db(self.engine)

    def _get_session(self) -> Session:
        """Get a new database session."""
        return self.SessionLocal()

    def close(self) -> None:
        """Dispose of the database engine and release connections."""
        self.engine.dispose()

    def _ping_sync(self) -> bool:
        """Synchronous implementation of ping."""
        with self._get_session() as session:
            session.execute(text("SELECT 1"))
            return True

    async def ping(self) -> bool:
        """Check if database connection is alive.

        Returns
        -------
        bool
            True if connection is alive.
        """
        return await asyncio.to_thread(self._ping_sync)

    def _create_conversation_sync(
        self,
        name: str | None = None,
        pinned: bool = False,
        mode: str = "chat",
        workspace: str | None = None,
        role: str | None = None,
    ) -> str:
        """Synchronous implementation of create_conversation."""
        with self._get_session() as session:
            conversation = Conversation(
                name=name, pinned=pinned, mode=mode, workspace=workspace, role=role
            )
            session.add(conversation)
            session.commit()
            session.refresh(conversation)
            return conversation.id

    async def create_conversation(
        self,
        name: str | None = None,
        pinned: bool = False,
        mode: str = "chat",
        workspace: str | None = None,
        role: str | None = None,
    ) -> str:
        return await asyncio.to_thread(
            self._create_conversation_sync, name, pinned, mode, workspace, role
        )

    def _add_message_sync(
        self,
        conversation_id: str,
        role: str,
        content: str,
        reasoning_content: str | None = None,
        attachments: list[dict[str, Any]] | None = None,
    ) -> None:
        """Synchronous implementation of add_message."""
        if role not in VALID_ROLES:
            raise ValueError(f"Invalid role: {role!r}. Must be one of: {VALID_ROLES}")

        with self._get_session() as session:
            # Verify conversation exists
            conversation = session.get(Conversation, conversation_id)
            if conversation is None:
                raise ValueError(f"Conversation not found: {conversation_id}")

            message = Message(
                conversation_id=conversation_id,
                role=role,
                content=content,
                reasoning_content=reasoning_content,
                attachments=_serialize_attachments(attachments),
            )
            session.add(message)
            session.commit()

    async def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        reasoning_content: str | None = None,
        attachments: list[dict[str, Any]] | None = None,
    ) -> None:
        """Add a message to a conversation.

        Parameters
        ----------
        conversation_id:
            ID of the conversation to add the message to.
        role:
            Role of the message sender (user, assistant, system).
        content:
            Content of the message.
        reasoning_content:
            Optional captured thinking/reasoning text for assistant messages.
        attachments:
            Optional list of attachment reference dicts (shape:
            ``[{id, mime, width?, height?, alt?}]``). JSON-encoded into the
            message row; serialization failure degrades to NULL.

        Raises
        ------
        ValueError
            If the conversation does not exist or role is invalid.
        """
        return await asyncio.to_thread(
            self._add_message_sync,
            conversation_id,
            role,
            content,
            reasoning_content,
            attachments,
        )

    def _get_messages_sync(self, conversation_id: str) -> list[dict[str, Any]]:
        """Synchronous implementation of get_messages."""
        with self._get_session() as session:
            # Verify conversation exists
            conversation = session.get(Conversation, conversation_id)
            if conversation is None:
                raise ValueError(f"Conversation not found: {conversation_id}")

            # Get messages ordered by creation time
            stmt = (
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at)
            )
            result = session.execute(stmt)
            messages = result.scalars().all()

            return [
                {
                    "id": msg.id,
                    "conversation_id": msg.conversation_id,
                    "role": msg.role,
                    "content": msg.content,
                    "reasoning_content": msg.reasoning_content,
                    "attachments": _deserialize_attachments(msg.attachments),
                    "created_at": msg.created_at.isoformat(),
                }
                for msg in messages
            ]

    async def get_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        """Get all messages in a conversation.

        Parameters
        ----------
        conversation_id:
            ID of the conversation to get messages from.

        Returns
        -------
        list[dict[str, Any]]
            List of message dictionaries.

        Raises
        ------
        ValueError
            If the conversation does not exist.
        """
        return await asyncio.to_thread(self._get_messages_sync, conversation_id)

    def _get_conversations_sync(self, mode: str | None = None) -> list[dict[str, Any]]:
        """Synchronous implementation of get_conversations."""
        with self._get_session() as session:
            stmt = select(Conversation).order_by(
                Conversation.pinned.desc(),
                Conversation.updated_at.desc(),
            )
            if mode is not None:
                stmt = stmt.where(Conversation.mode == mode)
            result = session.execute(stmt)
            conversations = result.scalars().all()

            return [
                {
                    "id": conv.id,
                    "name": conv.name,
                    "pinned": conv.pinned or False,
                    "mode": conv.mode or "chat",
                    "workspace": conv.workspace,
                    "endpoint_id": conv.endpoint_id,
                    "model": conv.model,
                    "knowledge_base_id": conv.knowledge_base_id,
                    "role": conv.role,
                    "thinking_enabled": conv.thinking_enabled or False,
                    "thinking_effort": conv.thinking_effort or "medium",
                    "created_at": conv.created_at.isoformat(),
                    "updated_at": conv.updated_at.isoformat(),
                    "summary": conv.summary,
                }
                for conv in conversations
            ]

    async def get_conversations(self, mode: str | None = None) -> list[dict[str, Any]]:
        """Get conversations, optionally filtered by mode."""
        return await asyncio.to_thread(self._get_conversations_sync, mode)

    def _get_all_conversations_with_messages_sync(self) -> list[dict[str, Any]]:
        """Synchronous implementation of get_all_conversations_with_messages."""
        with self._get_session() as session:
            stmt = (
                select(Conversation)
                .options(joinedload(Conversation.messages))
                .order_by(Conversation.created_at.desc())
            )
            result = session.execute(stmt)
            conversations = result.unique().scalars().all()

            return [
                {
                    "id": conv.id,
                    "name": conv.name,
                    "pinned": conv.pinned or False,
                    "endpoint_id": conv.endpoint_id,
                    "model": conv.model,
                    "knowledge_base_id": conv.knowledge_base_id,
                    "role": conv.role,
                    "mode": conv.mode or "chat",
                    "workspace": conv.workspace,
                    "thinking_enabled": conv.thinking_enabled or False,
                    "thinking_effort": conv.thinking_effort or "medium",
                    "created_at": conv.created_at.isoformat(),
                    "updated_at": conv.updated_at.isoformat(),
                    "summary": conv.summary,
                    "messages": [
                        {
                            "id": msg.id,
                            "conversation_id": msg.conversation_id,
                            "role": msg.role,
                            "content": msg.content,
                            "reasoning_content": msg.reasoning_content,
                            "attachments": _deserialize_attachments(msg.attachments),
                            "created_at": msg.created_at.isoformat(),
                        }
                        for msg in conv.messages
                    ],
                }
                for conv in conversations
            ]

    async def get_all_conversations_with_messages(self) -> list[dict[str, Any]]:
        """Get all conversations with their messages in a single query."""
        return await asyncio.to_thread(self._get_all_conversations_with_messages_sync)

    def _get_conversation_sync(self, conversation_id: str) -> dict[str, Any] | None:
        """Synchronous implementation of get_conversation."""
        with self._get_session() as session:
            conversation = session.get(Conversation, conversation_id)

            if conversation is None:
                return None

            return {
                "id": conversation.id,
                "name": conversation.name,
                "pinned": conversation.pinned or False,
                "endpoint_id": conversation.endpoint_id,
                "model": conversation.model,
                "knowledge_base_id": conversation.knowledge_base_id,
                "role": conversation.role,
                "mode": conversation.mode or "chat",
                "workspace": conversation.workspace,
                "thinking_enabled": conversation.thinking_enabled or False,
                "thinking_effort": conversation.thinking_effort or "medium",
                "created_at": conversation.created_at.isoformat(),
                "updated_at": conversation.updated_at.isoformat(),
                "summary": conversation.summary,
            }

    async def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        """Get a single conversation by ID.

        Parameters
        ----------
        conversation_id:
            ID of the conversation to get.

        Returns
        -------
        dict[str, Any] | None
            Conversation dictionary, or None if not found.
        """
        return await asyncio.to_thread(self._get_conversation_sync, conversation_id)

    def _delete_conversation_sync(self, conversation_id: str) -> bool:
        """Synchronous implementation of delete_conversation."""
        with self._get_session() as session:
            conversation = session.get(Conversation, conversation_id)

            if conversation is None:
                return False

            session.delete(conversation)
            session.commit()
            return True

    async def delete_conversation(self, conversation_id: str) -> bool:
        """Delete a conversation and all its messages.

        Parameters
        ----------
        conversation_id:
            ID of the conversation to delete.

        Returns
        -------
        bool
            True if the conversation was deleted, False if not found.
        """
        return await asyncio.to_thread(self._delete_conversation_sync, conversation_id)

    def _clear_messages_sync(self, conversation_id: str) -> bool:
        """Synchronous implementation of clear_messages."""
        with self._get_session() as session:
            conversation = session.get(Conversation, conversation_id)

            if conversation is None:
                return False

            session.execute(delete(Message).where(Message.conversation_id == conversation_id))
            conversation.summary = None
            session.commit()
            return True

    async def clear_messages(self, conversation_id: str) -> bool:
        """Delete all messages of a conversation while keeping the conversation.

        Also clears the cached summary so stale context is not reused.

        Parameters
        ----------
        conversation_id:
            ID of the conversation whose messages should be cleared.

        Returns
        -------
        bool
            True if messages were cleared, False if the conversation was not found.
        """
        return await asyncio.to_thread(self._clear_messages_sync, conversation_id)

    def _set_summary_sync(self, conversation_id: str, summary: str) -> bool:
        """Synchronous implementation of set_summary."""
        with self._get_session() as session:
            conversation = session.get(Conversation, conversation_id)
            if conversation is None:
                return False
            conversation.summary = summary
            session.commit()
            return True

    async def set_summary(self, conversation_id: str, summary: str) -> bool:
        """Set the summary for a conversation.

        Parameters
        ----------
        conversation_id:
            ID of the conversation to set summary for.
        summary:
            Summary text.

        Returns
        -------
        bool
            True if set successfully, False if conversation not found.
        """
        return await asyncio.to_thread(self._set_summary_sync, conversation_id, summary)

    def _rename_conversation_sync(self, conversation_id: str, name: str) -> bool:
        """Synchronous implementation of rename_conversation."""
        with self._get_session() as session:
            conversation = session.get(Conversation, conversation_id)
            if conversation is None:
                return False
            conversation.name = name
            session.commit()
            return True

    async def rename_conversation(self, conversation_id: str, name: str) -> bool:
        """Update the human-readable name of a conversation.

        Parameters
        ----------
        conversation_id:
            ID of the conversation to rename.
        name:
            New name. Pass an empty string to clear the name.

        Returns
        -------
        bool
            True if renamed successfully, False if conversation not found.
        """
        return await asyncio.to_thread(self._rename_conversation_sync, conversation_id, name)

    def _set_endpoint_sync(self, conversation_id: str, endpoint_id: str | None) -> bool:
        """Synchronous implementation of set_conversation_endpoint."""
        with self._get_session() as session:
            conversation = session.get(Conversation, conversation_id)
            if conversation is None:
                return False
            conversation.endpoint_id = endpoint_id
            session.commit()
            return True

    async def set_conversation_endpoint(
        self, conversation_id: str, endpoint_id: str | None
    ) -> bool:
        """Associate a conversation with a configured LLM endpoint.

        Parameters
        ----------
        conversation_id:
            ID of the conversation to update.
        endpoint_id:
            ID of the configured endpoint, or None to revert to the default.

        Returns
        -------
        bool
            True if set successfully, False if conversation not found.
        """
        return await asyncio.to_thread(self._set_endpoint_sync, conversation_id, endpoint_id)

    def _set_model_sync(self, conversation_id: str, model: str | None) -> bool:
        """Synchronous implementation of set_conversation_model."""
        with self._get_session() as session:
            conversation = session.get(Conversation, conversation_id)
            if conversation is None:
                return False
            conversation.model = model
            session.commit()
            return True

    async def set_conversation_model(self, conversation_id: str, model: str | None) -> bool:
        """Set the specific model used for a conversation.

        Parameters
        ----------
        conversation_id:
            ID of the conversation to update.
        model:
            Model name within the conversation's endpoint, or None to use the
            endpoint's active/default model.

        Returns
        -------
        bool
            True if set successfully, False if conversation not found.
        """
        return await asyncio.to_thread(self._set_model_sync, conversation_id, model)

    def _set_knowledge_base_sync(self, conversation_id: str, knowledge_base_id: str | None) -> bool:
        """Synchronous implementation of set_conversation_knowledge_base."""
        with self._get_session() as session:
            conversation = session.get(Conversation, conversation_id)
            if conversation is None:
                return False
            conversation.knowledge_base_id = knowledge_base_id
            session.commit()
            return True

    async def set_conversation_knowledge_base(
        self, conversation_id: str, knowledge_base_id: str | None
    ) -> bool:
        """Bind (or unbind) a RAG knowledge base to a conversation.

        Parameters
        ----------
        conversation_id:
            ID of the conversation to update.
        knowledge_base_id:
            ID of the knowledge base, or None to unbind.

        Returns
        -------
        bool
            True if set successfully, False if conversation not found.
        """
        return await asyncio.to_thread(
            self._set_knowledge_base_sync, conversation_id, knowledge_base_id
        )

    def _set_role_sync(self, conversation_id: str, role: str | None) -> bool:
        """Synchronous implementation of set_conversation_role."""
        with self._get_session() as session:
            conversation = session.get(Conversation, conversation_id)
            if conversation is None:
                return False
            conversation.role = role
            session.commit()
            return True

    async def set_conversation_role(self, conversation_id: str, role: str | None) -> bool:
        """Set the agent persona role for a conversation.

        Parameters
        ----------
        conversation_id:
            ID of the conversation to update.
        role:
            Role name matching a ``prompts/roles/<role>.md`` file, or None
            to revert to the global default role.

        Returns
        -------
        bool
            True if set successfully, False if conversation not found.
        """
        return await asyncio.to_thread(self._set_role_sync, conversation_id, role)

    def _set_thinking_sync(self, conversation_id: str, enabled: bool, effort: str) -> bool:
        """Synchronous implementation of set_conversation_thinking."""
        with self._get_session() as session:
            conversation = session.get(Conversation, conversation_id)
            if conversation is None:
                return False
            conversation.thinking_enabled = enabled
            conversation.thinking_effort = effort
            session.commit()
            return True

    async def set_conversation_thinking(
        self, conversation_id: str, enabled: bool, effort: str
    ) -> bool:
        """Set thinking-mode settings for a conversation.

        Parameters
        ----------
        conversation_id:
            ID of the conversation to update.
        enabled:
            Whether thinking mode is enabled.
        effort:
            Thinking intensity: ``low``, ``medium``, or ``high``.

        Returns
        -------
        bool
            True if set successfully, False if conversation not found.
        """
        return await asyncio.to_thread(self._set_thinking_sync, conversation_id, enabled, effort)

    def _search_messages_sync(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Synchronous implementation of search_messages."""
        with self._get_session() as session:
            # 使用参数化查询防止 SQL 注入，转义 LIKE 通配符
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            search_pattern = f"%{escaped}%"
            stmt = (
                select(Message)
                .where(Message.content.like(search_pattern, escape="\\"))
                .order_by(Message.created_at.desc())
                .limit(limit)
            )
            result = session.execute(stmt)
            messages = result.scalars().all()

            return [
                {
                    "id": msg.id,
                    "conversation_id": msg.conversation_id,
                    "role": msg.role,
                    "content": msg.content,
                    "created_at": msg.created_at.isoformat(),
                }
                for msg in messages
            ]

    async def search_messages(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Search messages by keyword using SQL LIKE.

        Parameters
        ----------
        query:
            Text to search for in message content.
        limit:
            Maximum number of results.

        Returns
        -------
        list[dict[str, Any]]
            List of matching message dicts.
        """
        return await asyncio.to_thread(self._search_messages_sync, query, limit)

    # ------------------------------------------------------------------
    # Attachment CRUD(设计文档 §3.2 / Task B1)
    # ------------------------------------------------------------------

    def _create_attachment_sync(
        self,
        mime: str,
        size: int,
        relative_path: str,
        width: int | None = None,
        height: int | None = None,
        sha256: str | None = None,
    ) -> dict[str, Any]:
        """Synchronous implementation of create_attachment."""
        from thumbelina.repository.models import Attachment

        with self._get_session() as session:
            att = Attachment(
                mime=mime,
                size=size,
                relative_path=relative_path,
                width=width,
                height=height,
                sha256=sha256,
            )
            session.add(att)
            session.commit()
            session.refresh(att)
            return _attachment_to_dict(att)

    async def create_attachment(
        self,
        *,
        mime: str,
        size: int,
        relative_path: str,
        width: int | None = None,
        height: int | None = None,
        sha256: str | None = None,
    ) -> dict[str, Any]:
        """Record a new attachment and return its metadata dict.

        Parameters
        ----------
        mime:
            MIME type of the attachment (e.g. ``image/png``).
        size:
            File size in bytes.
        relative_path:
            Path relative to the attachment root directory
            (e.g. ``2026/09/<uuid>.png``). The caller owns writing the bytes.
        width:
            Optional image width in pixels.
        height:
            Optional image height in pixels.
        sha256:
            Optional hex digest for dedup.

        Returns
        -------
        dict[str, Any]
            The stored attachment metadata (including generated id and
            created_at).
        """
        return await asyncio.to_thread(
            self._create_attachment_sync, mime, size, relative_path, width, height, sha256
        )

    def _get_attachment_sync(self, attachment_id: str) -> dict[str, Any] | None:
        """Synchronous implementation of get_attachment."""
        from thumbelina.repository.models import Attachment

        with self._get_session() as session:
            att = session.get(Attachment, attachment_id)
            if att is None:
                return None
            return _attachment_to_dict(att)

    async def get_attachment(self, attachment_id: str) -> dict[str, Any] | None:
        """Get a single attachment by ID.

        Returns
        -------
        dict[str, Any] | None
            Attachment metadata dict, or None if not found.
        """
        return await asyncio.to_thread(self._get_attachment_sync, attachment_id)

    def _get_attachments_sync(self, attachment_ids: list[str]) -> dict[str, dict[str, Any]]:
        """Synchronous implementation of get_attachments."""
        from thumbelina.repository.models import Attachment

        if not attachment_ids:
            return {}
        with self._get_session() as session:
            rows = (
                session.execute(select(Attachment).where(Attachment.id.in_(attachment_ids)))
                .scalars()
                .all()
            )
            return {att.id: _attachment_to_dict(att) for att in rows}

    async def get_attachments(self, attachment_ids: list[str]) -> dict[str, dict[str, Any]]:
        """Batch-get attachments by IDs.

        Parameters
        ----------
        attachment_ids:
            IDs to look up; an empty list short-circuits to ``{}``.

        Returns
        -------
        dict[str, dict[str, Any]]
            Mapping of ``{id: metadata dict}``; missing IDs are absent.
        """
        return await asyncio.to_thread(self._get_attachments_sync, attachment_ids)

    def _delete_attachment_sync(self, attachment_id: str) -> bool:
        """Synchronous implementation of delete_attachment."""
        from thumbelina.repository.models import Attachment

        with self._get_session() as session:
            att = session.get(Attachment, attachment_id)
            if att is None:
                return False
            session.delete(att)
            session.commit()
            return True

    async def delete_attachment(self, attachment_id: str) -> bool:
        """Physically delete an attachment row (no soft delete).

        Returns
        -------
        bool
            True if the row was deleted, False if not found.
        """
        return await asyncio.to_thread(self._delete_attachment_sync, attachment_id)
