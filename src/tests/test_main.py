from __future__ import annotations

from utilities.pathlib import get_repo_root
from utilities.subprocess import run


class TestCLI:
    def test_main(self) -> None:
        run("nitpick", cwd=get_repo_root())
