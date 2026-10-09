import shutil

import pytest


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if shutil.which("7zz"):
        return
    skip = pytest.mark.skip(reason="7zz is not installed (brew install sevenzip)")
    for item in items:
        if "sevenzip" in item.keywords:
            item.add_marker(skip)
