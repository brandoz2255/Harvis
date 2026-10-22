"""Shared test hooks."""
import sys

import pytest


@pytest.fixture(autouse=True)
def _empty_docs_rate_table():
    """The docs rate limiter is process-wide; without this the docs suites, run in one process, spend each other's
    allowance (same fake user ids) and start failing as tests are added."""
    limits = sys.modules.get("plugins.hermes_ui.docs_limits")
    if limits is not None:
        limits.reset()
    yield
