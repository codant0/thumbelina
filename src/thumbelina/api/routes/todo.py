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
from thumbelina.todo.service import (
    GroupNameConflictError,
    GroupNotFoundError,
    TodoService,
)

router = APIRouter(prefix="/todo", tags=["todo"])


class TodoItemCreate(BaseModel):
    """Payload for creating a todo item."""

    text: str = Field(min_length=1)


class TodoItemUpdate(BaseModel):
    """Payload for updating a todo item (text, done state, remark and/or group).

    ``group``: ``""`` clears the assignment (the item becomes ungrouped);
    any non-empty string attaches the item to that group, creating its
    ``# heading`` if necessary.  Whether the field was actually sent matters
    (``null`` is "leave unchanged"), so handlers check ``model_fields_set``.
    """

    text: str | None = None
    done: bool | None = None
    remark: str | None = None
    group: str | None = None


class NoteCreate(BaseModel):
    """Payload for creating a quick note."""

    content: str = Field(min_length=1)


class NoteUpdate(BaseModel):
    """Payload for updating a quick note.

    ``content`` and ``group`` are both optional; at least one is expected.
    ``content: null`` leaves the text untouched so a drag that only changes
    the group can send ``{"group": "…"}``.  ``group: ""`` clears the group.
    """

    content: str | None = None
    group: str | None = None


class GroupCreate(BaseModel):
    """Payload for creating a new group."""

    name: str = Field(min_length=1)


class GroupRename(BaseModel):
    """Payload for renaming a group."""

    name: str = Field(min_length=1)


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


def _patch_group(payload: TodoItemUpdate | NoteUpdate, field: str) -> str | None:
    """Extract a group patch from a request payload.

    Returns the stripped group target (``""`` clears the group) or ``None``
    when the client did not explicitly send the field.  Pydantic cannot tell
    "absent" from ``null`` through the attribute, so we consult
    ``model_fields_set`` to distinguish "leave the group alone" from an
    explicit clear.
    """
    if field not in payload.model_fields_set:
        return None
    value = getattr(payload, field)
    if value is None:
        return None  # JSON null == "do not touch" (a no-op request)
    return str(value).strip()


@router.patch("/items/{index}", response_model=TodoItemsOut, response_model_exclude_none=True)
async def update_item(
    index: int,
    payload: TodoItemUpdate,
    service: TodoService = Depends(get_todo_service),
) -> TodoItemsOut:
    """Update the text, done state, remark and/or group of the item at ``index``.

    ``group`` is the field that lets the UI drag an item into a different
    bucket: send ``""`` to ungroup it or a group name to move it there.
    """
    text: str | None = None
    if payload.text is not None:
        text = _require_non_blank(payload.text, "text")
    remark: str | None = None
    if payload.remark is not None:
        remark = payload.remark.strip()
    group = _patch_group(payload, "group")
    try:
        return _items_payload(
            await service.update_item(
                index,
                text=text,
                done=payload.done,
                remark=remark,
                group=group,
            )
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
    """Replace the content of the note at ``index`` and/or reassign its group.

    Timestamp is kept.  At least one of ``content`` / ``group`` must be
    present; a drag that only moves the note sends ``{"group": "…"}`` and
    leaves the text alone.
    """
    if "content" not in payload.model_fields_set and "group" not in payload.model_fields_set:
        raise HTTPException(status_code=422, detail="nothing to update")
    content: str | None = None
    if payload.content is not None:
        content = _require_non_blank(payload.content, "content")
    group = _patch_group(payload, "group")
    try:
        return _notes_payload(await service.update_note(index, content, group=group))
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


# ----------------------------------------------------------------------
# Group CRUD
# ----------------------------------------------------------------------


@router.post("/items/groups", response_model=TodoItemsOut, response_model_exclude_none=True)
async def create_item_group(
    payload: GroupCreate,
    service: TodoService = Depends(get_todo_service),
) -> TodoItemsOut:
    """Append a ``# name`` marker so the new group exists in the file."""
    name = _require_non_blank(payload.name, "name")
    await service.create_group("items", name)
    return _items_payload(await service.list_items())


@router.patch(
    "/items/groups/{name}",
    response_model=TodoItemsOut,
    response_model_exclude_none=True,
)
async def rename_item_group(
    name: str,
    payload: GroupRename,
    service: TodoService = Depends(get_todo_service),
) -> TodoItemsOut:
    """Rename the ``# name`` marker and reassign every item in the group."""
    old = _require_non_blank(name, "name")
    new = _require_non_blank(payload.name, "name")
    try:
        await service.rename_group("items", old, new)
    except GroupNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except GroupNameConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _items_payload(await service.list_items())


@router.delete(
    "/items/groups/{name}",
    response_model=TodoItemsOut,
    response_model_exclude_none=True,
)
async def delete_item_group(
    name: str,
    service: TodoService = Depends(get_todo_service),
) -> TodoItemsOut:
    """Remove the ``# name`` marker; members fall back to "ungrouped"."""
    target = _require_non_blank(name, "name")
    try:
        await service.delete_group("items", target)
    except GroupNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _items_payload(await service.list_items())


@router.post("/notes/groups", response_model=TodoNotesOut, response_model_exclude_none=True)
async def create_note_group(
    payload: GroupCreate,
    service: TodoService = Depends(get_todo_service),
) -> TodoNotesOut:
    """Append a ``# name`` marker so the new group exists in ``notes.md``."""
    name = _require_non_blank(payload.name, "name")
    await service.create_group("notes", name)
    return _notes_payload(await service.list_notes())


@router.patch(
    "/notes/groups/{name}",
    response_model=TodoNotesOut,
    response_model_exclude_none=True,
)
async def rename_note_group(
    name: str,
    payload: GroupRename,
    service: TodoService = Depends(get_todo_service),
) -> TodoNotesOut:
    """Rename the ``# name`` marker in ``notes.md`` and reassign every note."""
    old = _require_non_blank(name, "name")
    new = _require_non_blank(payload.name, "name")
    try:
        await service.rename_group("notes", old, new)
    except GroupNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except GroupNameConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _notes_payload(await service.list_notes())


@router.delete(
    "/notes/groups/{name}",
    response_model=TodoNotesOut,
    response_model_exclude_none=True,
)
async def delete_note_group(
    name: str,
    service: TodoService = Depends(get_todo_service),
) -> TodoNotesOut:
    """Remove the ``# name`` marker from ``notes.md``; members go ungrouped."""
    target = _require_non_blank(name, "name")
    try:
        await service.delete_group("notes", target)
    except GroupNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _notes_payload(await service.list_notes())
