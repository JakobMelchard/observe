"""Runs the node tests for the browser shim and the service worker.

They live in ``tests/shim`` and use only node built-ins (``node:test`` and
fakes), so there is nothing to install.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

SHIM_TESTS = sorted((Path(__file__).parent.parent / "shim").glob("*.test.mjs"))


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
@pytest.mark.parametrize("path", SHIM_TESTS, ids=lambda p: p.name)
def test_shim(path):
    result = subprocess.run(
        ["node", "--test", str(path)], capture_output=True, text=True, timeout=60, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
