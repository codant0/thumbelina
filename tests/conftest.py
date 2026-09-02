"""Project-wide pytest fixtures.

`setup_logging` (in :mod:`thumbelina.logging_config`) sets every stdlib
logger's ``propagate = False`` so loguru can intercept them.  When
``tests/test_logging/test_logging_config.py`` runs (it calls
``setup_logging()``), that side effect persists for the rest of the
session — which breaks ``caplog`` in unrelated tests (caplog relies on
propagation reaching the root logger).

This autouse fixture snapshots every logger's propagate flag before
each test and restores it afterwards, so the order of tests in CI does
not matter.
"""

from __future__ import annotations

import logging

import pytest


@pytest.fixture(autouse=True)
def _restore_log_propagate():
    snapshot: dict[str, bool] = {
        name: logging.getLogger(name).propagate
        for name in logging.root.manager.loggerDict
        if isinstance(name, str)
    }
    yield
    for name, propagate in snapshot.items():
        logger = logging.getLogger(name)
        if logger.propagate != propagate:
            logger.propagate = propagate
