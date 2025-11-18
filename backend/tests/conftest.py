import os
import sys
from pathlib import Path
import pytest

# Ensure backend/ (project root for tests) is on sys.path at import time.
# PyTest imports conftest.py as a module before running hooks like pytest_configure,
# so we must add the project root here before importing test utilities.
here = Path(__file__).resolve().parent
project_root = here.parent
project_root_str = str(project_root)
if project_root_str not in sys.path:
    sys.path.insert(0, project_root_str)


def pytest_configure(config):
    """No-op hook retained for compatibility; sys.path is already adjusted at import-time."""
    return


# expose FakeGraph as a fixture
from test_utils.fake_graph import FakeGraph


@pytest.fixture
def fake_graph():
    """Provide a fresh FakeGraph instance for tests."""
    return FakeGraph()
