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
from typing import TYPE_CHECKING, Any

from click import command
from tomlkit import TOMLDocument, aot, array, document, dumps, parse, table
from tomlkit.items import AoT, Array, Table
from typed_settings import click_options, option, settings
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
    version: str = option(default="3.14", help="Python version")
    pyproject: bool = option(default=False, help="Set up 'pyproject.toml'")
    pyproject__dependency_groups__dev: bool = option(
        default=False, help="Set up 'pyproject.toml' [dependency-groups.dev]"
    )
    pyproject__project__name: str | None = option(
        default=None, help="Set up 'pyproject.toml' [project.name]"
    )
    pyproject__project__optional_dependencies__scripts: bool = option(
        default=False,
        help="Set up 'pyproject.toml' [project.optional-dependencies.scripts]",
    )
    pyproject__tool__uv__indexes: str | None = option(
        default=None, help="Set up 'pyproject.toml' [[uv.tool.index]]"
    )
    ruff: bool = option(default=False, help="Set up 'ruff.toml'")
    dry_run: bool = option(default=False, help="Dry run the CLI")


_PYPROJECT_TOML = Path("pyproject.toml")
_RUFF_TOML = Path("ruff.toml")
_SETTINGS = Settings()


@command(**CONTEXT_SETTINGS_HELP_OPTION_NAMES)
@click_options(Settings, "app", show_envvars_in_help=True)
def main(settings: Settings, /) -> None:
    if settings.dry_run:
        _LOGGER.info("Dry run; exiting...")
        return
    _LOGGER.info("Running...")
    if settings.pyproject:
        _add_pyproject(version=settings.version)
    if settings.pyproject__dependency_groups__dev:
        _add_pyproject_dependency_groups_dev(version=settings.version)
    if (name := settings.pyproject__project__name) is not None:
        _add_pyproject_project_name(name, version=settings.version)
    if settings.pyproject__project__optional_dependencies__scripts:
        _add_pyproject_project_optional_dependencies_scripts(version=settings.version)
    if (indexes := settings.pyproject__tool__uv__indexes) is not None:
        for index in indexes.split("|"):
            name, url = index.split(",")
            _add_pyproject_uv_index(name, url, version=settings.version)
    if settings.ruff:
        _add_ruff(version=settings.version)


def _add_pyproject(*, version: str = _SETTINGS.version) -> None:
    with _yield_pyproject("[]", version=version):
        ...


def _add_ruff(*, version: str = _SETTINGS.version) -> None:
    with _yield_ruff("[]", version=version):
        ...


def _add_pyproject_dependency_groups_dev(*, version: str = _SETTINGS.version) -> None:
    with _yield_pyproject("[dependency-groups.dev]", version=version) as doc:
        dep_grps = _get_table(doc, "dependency-groups")
        dev = _get_array(dep_grps, "dev")
        _ensure_in_array(dev, "dycw-utilities[test]")
        _ensure_in_array(dev, "rich")


def _add_pyproject_project_name(
    name: str, /, *, version: str = _SETTINGS.version
) -> None:
    with _yield_pyproject("[project.name]", version=version) as doc:
        proj = _get_table(doc, "project")
        proj["name"] = name


def _add_pyproject_project_optional_dependencies_scripts(
    *, version: str = _SETTINGS.version
) -> None:
    with _yield_pyproject(
        "[project.optional-dependencies.scripts]", version=version
    ) as doc:
        proj = _get_table(doc, "project")
        opt_deps = _get_table(proj, "optional-dependencies")
        scripts = _get_array(opt_deps, "scripts")
        _ensure_in_array(scripts, "click >=8.3.1")


def _add_pyproject_uv_index(
    name: str, url: str, /, *, version: str = _SETTINGS.version
) -> None:
    with _yield_pyproject("[tool.uv.index]", version=version) as doc:
        tool = _get_table(doc, "tool")
        uv = _get_table(tool, "uv")
        indexes = _get_aot(uv, "index")
        index = table()
        index["explicit"] = True
        index["name"] = name
        index["url"] = url
        _ensure_in_aot(indexes, index)


def _ensure_in_aot(array: AoT, /, *tables: Table) -> None:
    for table_ in tables:
        if table_ not in array:
            array.append(table_)


def _ensure_in_array(array: Array, /, *objs: Any) -> None:
    for obj in objs:
        if obj not in array:
            array.append(obj)


def _ensure_not_in_array(array: Array, /, *objs: Any) -> None:
    for obj in objs:
        try:
            index = next(i for i, o in enumerate(array) if o == obj)
        except StopIteration:
            pass
        else:
            del array[index]


def _get_aot(obj: Container | Table, key: str, /) -> AoT:
    return ensure_class(obj.setdefault(key, aot()), AoT)


def _get_array(obj: Container | Table, key: str, /) -> Array:
    return ensure_class(obj.setdefault(key, array()), Array)


def _get_doc(path: PathLike, /) -> TOMLDocument:
    try:
        return parse(Path(path).read_text())
    except FileNotFoundError:
        return document()


def _get_table(obj: Container | Table, key: str, /) -> Table:
    return ensure_class(obj.setdefault(key, table()), Table)


@contextmanager
def _yield_toml_doc(path: PathLike, desc: str, /) -> Iterator[TOMLDocument]:
    path = Path(path)
    doc = _get_doc(path)
    yield doc
    if doc != _get_doc(path):
        _LOGGER.info("Adding '%s' %s...", path, desc)
        _ = path.write_text(dumps(doc))


@contextmanager
def _yield_pyproject(
    desc: str, /, *, version: str = _SETTINGS.version
) -> Iterator[TOMLDocument]:
    with _yield_toml_doc(_PYPROJECT_TOML, desc) as doc:
        bld_sys = _get_table(doc, "build-system")
        bld_sys["build-backend"] = "uv_build"
        bld_sys["requires"] = ["uv_build"]
        project = _get_table(doc, "project")
        project["requires-python"] = f">= {version}"
        yield doc


@contextmanager
def _yield_ruff(
    desc: str, /, *, version: str = _SETTINGS.version
) -> Iterator[TOMLDocument]:
    with _yield_toml_doc(_RUFF_TOML, desc) as doc:
        doc["target-version"] = f"py{version.replace('.', '')}"
        doc["unsafe-fixes"] = True
        fmt = _get_table(doc, "format")
        fmt["preview"] = True
        fmt["skip-magic-trailing-comma"] = True
        lint = _get_table(doc, "lint")
        lint["explicit-preview-rules"] = True
        fixable = _get_array(lint, "fixable")
        _ensure_in_array(fixable, "ALL")
        ignore = _get_array(lint, "ignore")
        _ensure_in_array(
            ignore,
            "ANN401",  # any-type
            "ASYNC109",  # async-function-with-timeout
            "C901",  # complex-structure
            "CPY",  # flake8-copyright
            "D",  # pydocstyle
            "E501",  # line-too-long
            "PD",  # pandas-vet
            "PERF203",  # try-except-in-loop
            "PLC0415",  # import-outside-top-level
            "PLE1205",  # logging-too-many-args
            "PLR0904",  # too-many-public-methods
            "PLR0911",  # too-many-return-statements
            "PLR0912",  # too-many-branches
            "PLR0913",  # too-many-arguments
            "PLR0915",  # too-many-statements
            "PLR2004",  # magic-value-comparison
            "PT012",  # pytest-raises-with-multiple-statements
            "PT013",  # pytest-incorrect-pytest-import
            "PYI041",  # redundant-numeric-union
            "S202",  # tarfile-unsafe-members
            "S310",  # suspicious-url-open-usage
            "S311",  # suspicious-non-cryptographic-random-usage
            "S602",  # subprocess-popen-with-shell-equals-true
            "S603",  # subprocess-without-shell-equals-true
            "S607",  # start-process-with-partial-path
            # preview
            "S101",  # assert
            # formatter
            "W191",  # tab-indentation
            "E111",  # indentation-with-invalid-multiple
            "E114",  # indentation-with-invalid-multiple-comment
            "E117",  # over-indented
            "COM812",  # missing-trailing-comma
            "COM819",  # prohibited-trailing-comma
            "ISC001",  # single-line-implicit-string-concatenation
            "ISC002",  # multi-line-implicit-string-concatenation
        )
        _ensure_not_in_array(
            ignore,
            "RUF022",  # unsorted-dunder-all
            "RUF029",  # unused-async
            "S101",  # assert
            "SLF001",  # private-member-access
        )
        lint["preview"] = True
        select = _get_array(lint, "select")
        _ensure_in_array(
            select,
            "ALL",
            "RUF022",  # unsorted-dunder-all
            "RUF029",  # unused-async
        )
        extend_ignores = _get_table(lint, "extend-per-file-ignores")
        test_py = _get_array(extend_ignores, "test_*.py")
        _ensure_in_array(
            test_py,
            "S101",  # assert
            "SLF001",  # private-member-access
        )
        bugbear = _get_table(lint, "flake8-bugbear")
        bugbear["ban-relative-imports"] = "all"
        isort = _get_table(lint, "isort")
        req_imps = _get_array(isort, "required-imports")
        _ensure_in_array(req_imps, "from __future__ import annotations")
        isort["split-on-trailing-comma"] = False
        yield doc


if __name__ == "__main__":
    basic_config(obj=__name__)
    main()
