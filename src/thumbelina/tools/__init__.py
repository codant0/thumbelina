"""Built-in tools for the Thumbelina agent.

工具按五类组织(spec §2):感知/执行落在本包 ``perception.py`` /
``execution.py``,沟通/协作/事件由 ``communication.py`` /
``collaboration.py`` / ``event.py`` 的工厂在装配期构造(需要 graph、
通知桥等运行时依赖,不在 ``get_all_tools`` 范围内)。
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import BaseTool

from thumbelina.tools.execution import RunShellTool, WriteFileTool
from thumbelina.tools.perception import perception_tools

__all__ = ["get_all_tools"]


def get_all_tools(search_config: Any = None) -> list[BaseTool]:
    """Return all built-in tools.

    Parameters
    ----------
    search_config:
        Optional :class:`~thumbelina.config.models.ToolsConfig` (or an
        object exposing ``.web_search``). When provided and web search is
        enabled, the ``web_search`` tool is included, bound to the live
        config so runtime hot-swaps take effect.
    """
    return perception_tools(search_config) + [WriteFileTool(), RunShellTool()]
