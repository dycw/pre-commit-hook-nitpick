#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#   "click",
#   "dycw-utilities",
#   "pytest-xdist",
#   "tomlkit",
# ]
# ///
from __future__ import annotations

from logging import getLogger
from pathlib import Path

from click import command, option
from utilities.click import CONTEXT_SETTINGS_HELP_OPTION_NAMES
from utilities.logging import basic_config

_LOGGER = getLogger(__name__)


@command(**CONTEXT_SETTINGS_HELP_OPTION_NAMES)
@option(
    "--pyproject-build-system/--no-pyproject-build-system",
    default=False,
    show_default=True,
    help="Add `pyproject.toml` [build-system]",
)
@option("--dry-run/--no-dry-run", default=False, show_default=True, help="Dry run")
def main(*, pyproject_build_system: bool = False, dry_run: bool = False) -> None:
    if dry_run:
        _LOGGER.info("Dry run; exiting...")
        return
    _LOGGER.info("Running...")
    if pyproject_build_system:
        _add_pyproject_build_system()


def _add_pyproject_build_system() -> None:
    _add_pyproject()
    _LOGGER.info("Adding `pyproject.toml` [build-system]")


def _add_pyproject() -> None:
    if not (path := Path("pyproject.toml")).is_file():
        _LOGGER.info("Adding `pyproject.toml`...")
        path.touch()


if __name__ == "__main__":
    basic_config(obj=__name__)
    main()
