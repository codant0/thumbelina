"""REST routes for the TODO module (todo list + quick notes).

All data endpoints depend on :func:`get_todo_service`, which returns 503 when
the module is disabled or failed to initialize. Every write operation returns
the full, up-to-date list so clients can refresh their state wholesale.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from thumbelina.api.deps import get_todo_service
from thumbelina.todo.models import Note, TodoItem
from thumbelina.todo.service import TodoService

router = APIRouter(prefix="/todo", tags=["todo"])


class TodoItemCreate(BaseModel):
    """Payload for creating a todo item."""

    text: str = Field(min_length=1)


class TodoItemUpdate(BaseModel):
    """Payload for updating a todo item (text, done state and/or remark)."""

    text: str | None = None
    done: bool | None = None
    remark: str | None = None


class NoteCreate(BaseModel):
    """Payload for creating a quick note."""

    content: str = Field(min_length=1)


class NoteUpdate(BaseModel):
    """Payload for replacing a note's content."""

    content: str = Field(min_length=1)


class TodoItemOut(BaseModel):
    """Serialized todo item."""

    index: int
    text: str
    done: bool
    remark: str = ""
    group: str | None = None


class TodoItemsOut(BaseModel):
    """Full todo item list."""

    items: list[TodoItemOut]


class NoteOut(BaseModel):
    """Serialized quick note."""

    index: int
    timestamp: str
    content: str
    group: str | None = None


class TodoNotesOut(BaseModel):
    """Full quick note list."""

    notes: list[NoteOut]


class TodoStatusOut(BaseModel):
    """TODO module availability."""

    enabled: bool


def _items_payload(items: list[TodoItem]) -> TodoItemsOut:
    return TodoItemsOut(
        items=[
            TodoItemOut(
                index=item.index,
                text=item.text,
                done=item.done,
                remark=item.remark,
                group=item.group,
            )
            for item in items
        ]
    )


def _notes_payload(notes: list[Note]) -> TodoNotesOut:
    return TodoNotesOut(
        notes=[
            NoteOut(
                index=note.index,
                timestamp=note.timestamp,
                content=note.content,
                group=note.group,
            )
            for note in notes
        ]
    )


def _require_non_blank(value: str, field: str) -> str:
    """Strip ``value`` and raise 422 if nothing remains (min_length misses blanks)."""
    stripped = value.strip()
    if not stripped:
        raise HTTPException(status_code=422, detail=f"{field} must not be blank")
    return stripped


@router.get("/status", response_model=TodoStatusOut)
async def todo_status(request: Request) -> TodoStatusOut:
    """Report whether the TODO module is available (never returns 503)."""
    service = getattr(request.app.state, "todo_service", None)
    return TodoStatusOut(enabled=service is not None)


@router.get("/items", response_model=TodoItemsOut, response_model_exclude_none=True)
async def list_items(service: TodoService = Depends(get_todo_service)) -> TodoItemsOut:
    """List all todo items."""
    return _items_payload(await service.list_items())


@router.post("/items", response_model=TodoItemsOut, response_model_exclude_none=True)
async def create_item(
    payload: TodoItemCreate,
    service: TodoService = Depends(get_todo_service),
) -> TodoItemsOut:
    """Add a new todo item and return the full updated list."""
    text = _require_non_blank(payload.text, "text")
    return _items_payload(await service.add_item(text))


@router.patch("/items/{index}", response_model=TodoItemsOut, response_model_exclude_none=True)
async def update_item(
    index: int,
    payload: TodoItemUpdate,
    service: TodoService = Depends(get_todo_service),
) -> TodoItemsOut:
    """Update the text, done state and/or remark of the item at ``index``."""
    text: str | None = None
    if payload.text is not None:
        text = _require_non_blank(payload.text, "text")
    remark: str | None = None
    if payload.remark is not None:
        remark = payload.remark.strip()
    try:
        return _items_payload(
            await service.update_item(index, text=text, done=payload.done, remark=remark)
        )
    except IndexError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/items/{index}", response_model=TodoItemsOut, response_model_exclude_none=True)
async def delete_item(
    index: int,
    service: TodoService = Depends(get_todo_service),
) -> TodoItemsOut:
    """Delete the item at ``index`` and return the full updated list."""
    try:
        return _items_payload(await service.delete_item(index))
    except IndexError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/notes", response_model=TodoNotesOut, response_model_exclude_none=True)
async def list_notes(service: TodoService = Depends(get_todo_service)) -> TodoNotesOut:
    """List all quick notes (newest first)."""
    return _notes_payload(await service.list_notes())


@router.post("/notes", response_model=TodoNotesOut, response_model_exclude_none=True)
async def create_note(
    payload: NoteCreate,
    service: TodoService = Depends(get_todo_service),
) -> TodoNotesOut:
    """Add a new note at the top and return the full updated list."""
    content = _require_non_blank(payload.content, "content")
    return _notes_payload(await service.add_note(content))


@router.put("/notes/{index}", response_model=TodoNotesOut, response_model_exclude_none=True)
async def update_note(
    index: int,
    payload: NoteUpdate,
    service: TodoService = Depends(get_todo_service),
) -> TodoNotesOut:
    """Replace the content of the note at ``index`` (timestamp is kept)."""
    content = _require_non_blank(payload.content, "content")
    try:
        return _notes_payload(await service.update_note(index, content))
    except IndexError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/notes/{index}", response_model=TodoNotesOut, response_model_exclude_none=True)
async def delete_note(
    index: int,
    service: TodoService = Depends(get_todo_service),
) -> TodoNotesOut:
    """Delete the note at ``index`` and return the full updated list."""
    try:
        return _notes_payload(await service.delete_note(index))
    except IndexError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
