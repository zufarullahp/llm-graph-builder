import os
import sys
from pathlib import Path
import pytest

# expose FakeGraph as a fixture
from test_utils.fake_graph import FakeGraph


def pytest_configure(config):
    """Ensure the project `backend` package root is on sys.path so tests can import `src.*` modules.

    This makes running pytest in CI or locally simpler without setting PYTHONPATH externally.
    """
    # tests/ is located in backend/tests; project root for imports is backend/
    here = Path(__file__).resolve().parent
    project_root = here.parent
    project_root_str = str(project_root)
    if project_root_str not in sys.path:
        sys.path.insert(0, project_root_str)


@pytest.fixture
def fake_graph():
    """Provide a fresh FakeGraph instance for tests."""
    return FakeGraph()
