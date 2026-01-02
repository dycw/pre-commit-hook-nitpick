from __future__ import annotations

from subprocess import check_call

from utilities.pathlib import get_repo_root


class TestScript:
    def test_main(self) -> None:
        _ = check_call(["nitpick"], cwd=get_repo_root())
