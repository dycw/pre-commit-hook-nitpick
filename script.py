#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#   "click",
#   "dycw-utilities",
#   "pytest-xdist",
#   "tomlkit",
#   "typed-settings[attrs, click]",
# ]
# ///
from __future__ import annotations

from contextlib import contextmanager
from logging import getLogger
from pathlib import Path
from typing import TYPE_CHECKING

from click import command
from tomlkit import aot, array, dumps, parse, table
from tomlkit.items import AoT, Array, Table
from typed_settings import click_options, settings
from utilities.click import CONTEXT_SETTINGS_HELP_OPTION_NAMES
from utilities.functions import ensure_class
from utilities.logging import basic_config

if TYPE_CHECKING:
    from collections.abc import Iterator

    from tomlkit.container import Container
    from utilities.types import PathLike

_LOGGER = getLogger(__name__)


@settings()
class Settings:
    pyproject__build_system: bool = False
    pyproject__dependency_groups: bool = False
    pyproject__project__name: str | None = None
    pyproject__tool__uv__indexes: str | None = None
    dry_run: bool = False


@command(**CONTEXT_SETTINGS_HELP_OPTION_NAMES)
@click_options(Settings, "app", show_envvars_in_help=True)
def main(settings: Settings, /) -> None:
    if settings.dry_run:
        _LOGGER.info("Dry run; exiting...")
        return
    _LOGGER.info("Running...")
    if settings.pyproject__build_system:
        _add_pyproject_build_system()
    if settings.pyproject__dependency_groups:
        _add_pyproject_dependency_groups()
    if (name := settings.pyproject__project__name) is not None:
        _add_pyproject_project_name(name)
    if (indexes := settings.pyproject__tool__uv__indexes) is not None:
        for index in indexes.split("|"):
            name, url = index.split(",")
            _add_pyproject_uv_index(name, url)


def _add_pyproject(*, path: PathLike = "pyproject.toml") -> None:
    path = Path(path)
    if not path.is_file():
        _LOGGER.info("Adding `%s`...", path)
        path.touch()


def _add_pyproject_build_system(*, path: PathLike = "pyproject.toml") -> None:
    with _yield_pyproject("[build-system]", path=path) as doc:
        bs = ensure_class(doc.setdefault("build-system", table()), Table)
        bs["build-backend"] = "uv_build"
        bs["requires"] = ["uv_build"]


def _add_pyproject_dependency_groups(*, path: PathLike = "pyproject.toml") -> None:
    with _yield_pyproject("[dependency-groups]", path=path) as doc:
        db = ensure_class(doc.setdefault("dependency-groups", table()), Table)
        dev = ensure_class(db.setdefault("dev", array()), Array)
        if (dycw := "dycw-utilities[test]") not in dev:
            dev.append(dycw)
        if (rich := "rich") not in dev:
            dev.append(rich)


def _add_pyproject_project_name(
    name: str, /, *, path: PathLike = "pyproject.toml"
) -> None:
    with _yield_pyproject("[project.name]", path=path) as doc:
        proj = ensure_class(doc.setdefault("project", table()), Table)
        _ = proj.setdefault("name", name)


def _add_pyproject_uv_index(
    name: str, url: str, /, *, path: PathLike = "pyproject.toml"
) -> None:
    with _yield_pyproject("[tool.uv.index]", path=path) as doc:
        tool = ensure_class(doc.setdefault("tool", table()), Table)
        uv = ensure_class(tool.setdefault("uv", table()), Table)
        indexes = ensure_class(uv.setdefault("index", aot()), AoT)
        index = table()
        index["explicit"] = True
        index["name"] = name
        index["url"] = url
        if index not in indexes:
            indexes.append(index)


@contextmanager
def _yield_pyproject(
    desc: str, /, *, path: PathLike = "pyproject.toml"
) -> Iterator[Container]:
    path = Path(path)
    _add_pyproject(path=path)
    temp = parse(path.read_text())
    yield temp
    current = parse(path.read_text())
    if current != temp:
        _LOGGER.info("Adding `pyproject.toml` %s...", desc)
        _ = path.write_text(dumps(temp))


if __name__ == "__main__":
    basic_config(obj=__name__)
    main()
