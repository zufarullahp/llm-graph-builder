"""Package marker for src so tests can import modules as `src.*`.

Adding this empty initializer ensures the `src` directory is a proper
Python package when pytest runs from the `backend` directory.
"""

__all__ = []
