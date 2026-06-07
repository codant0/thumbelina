"""Thumbelina - AI-powered application built with FastAPI and LangGraph."""

import warnings

try:
    from langchain_core._api.deprecation import LangChainPendingDeprecationWarning

    warnings.filterwarnings(
        "ignore",
        message=r"The default value of `allowed_objects` will change in a future version",
        category=LangChainPendingDeprecationWarning,
    )
except ImportError:
    pass

__version__ = "0.1.0"
