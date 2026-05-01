"""Auto-mark all integration tests as slow (they run the full DP optimizer)."""

import pytest


def pytest_collection_modifyitems(items):
    for item in items:
        if "/integration/" in str(item.fspath):
            item.add_marker(pytest.mark.slow)
