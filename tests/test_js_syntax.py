"""Every script the pages load parses: one stray quote in a string stops a whole file (and every page using it)."""
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / "app" / "static"


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
@pytest.mark.parametrize("js", sorted(p.name for p in STATIC.glob("*.js")) + ["../offline_worker.js"])
def test_script_parses(js):
    r = subprocess.run(["node", "--check", str(STATIC / js)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-800:]
