"""Task and subagent API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from thumbelina.agent.graph import ThumbelinaAgent
from thumbelina.api.deps import get_agent

router = APIRouter(tags=["tasks"])


@router.get("/subagents")
async def list_subagents(
    agent: ThumbelinaAgent = Depends(get_agent),
) -> list[dict]:
    """List all subagents with their status."""
    if agent.subagent_manager:
        agents = await agent.subagent_manager.list_agents()
        return [
            {
                "id": a.id,
                "task": a.task,
                "status": a.status.value,
                "result": a.result,
            }
            for a in agents
        ]
    return []


@router.post("/subagents/{agent_id}/cancel")
async def cancel_subagent(
    agent_id: str,
    agent: ThumbelinaAgent = Depends(get_agent),
) -> dict[str, bool]:
    """Cancel a running subagent."""
    if not agent.subagent_manager:
        raise HTTPException(status_code=404, detail="Subagent manager not available")
    cancelled = await agent.subagent_manager.cancel_agent(agent_id)
    if not cancelled:
        raise HTTPException(status_code=404, detail="Subagent not found")
    return {"cancelled": True}


@router.get("/tasks")
async def list_tasks(
    agent: ThumbelinaAgent = Depends(get_agent),
) -> list[dict]:
    """List all scheduled tasks."""
    if agent.scheduler:
        tasks = await agent.scheduler.list_tasks()
        return [
            {
                "id": t.id,
                "description": t.description,
                "scheduled_time": t.scheduled_time.isoformat(),
                "status": t.status.value,
            }
            for t in tasks
        ]
    return []


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(
    task_id: str,
    agent: ThumbelinaAgent = Depends(get_agent),
) -> dict[str, bool]:
    """Cancel a scheduled task."""
    if not agent.scheduler:
        raise HTTPException(status_code=404, detail="Scheduler not available")
    cancelled = await agent.scheduler.cancel_task(task_id)
    if not cancelled:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"cancelled": True}


@router.get("/plugins/dependencies")
async def get_plugin_dependencies(request: Request) -> dict:
    """Return the plugin dependency graph and load order.

    Requires a ``PluginManager`` to be available on ``app.state``.
    Returns 404 if the plugin manager has not been initialised.
    """
    plugin_manager = getattr(request.app.state, "plugin_manager", None)
    if plugin_manager is None:
        raise HTTPException(
            status_code=404,
            detail="Plugin manager not available",
        )
    return plugin_manager.get_dependency_graph()
