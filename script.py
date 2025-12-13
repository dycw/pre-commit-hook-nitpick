#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#   "click",
#   "dycw-utilities",
#   "pytest-xdist",
# ]
# ///
from __future__ import annotations

from logging import getLogger
from pathlib import Path

import click
from click import command, option
from utilities.click import CONTEXT_SETTINGS_HELP_OPTION_NAMES
from utilities.logging import basic_config

_LOGGER = getLogger(__name__)


@command(**CONTEXT_SETTINGS_HELP_OPTION_NAMES)
@option(
    "--file",
    type=click.Path(path_type=Path),
    default=None,
    show_default=True,
    help="File to create",
)
@option("--dry-run/--no-dry-run", default=False, show_default=True, help="Dry run")
def main(*, file: Path | None = None, dry_run: bool = False) -> None:
    if dry_run:
        _LOGGER.info("Dry run; exiting...")
        return
    _LOGGER.info("Running...")
    if file is not None:
        file.touch()


if __name__ == "__main__":
    basic_config(obj=__name__)
    main()
