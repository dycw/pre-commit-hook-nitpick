#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "click >= 8.3.1, < 8.4",
#   "dycw-utilities >= 0.172.7, < 0.173",
#   "rich >= 14.2.0, < 14.3",
#   "ruamel-yaml >=0.18.17, <0.19",
#   "tomlkit >= 0.13.3, < 0.14",
#   "typed-settings[attrs, click] >= 25.3.0, < 25.4",
#   "xdg-base-dirs >= 6.0.2, < 6.1",
#   "pyright",
#   "pytest-xdist",
# ]
# ///
from __future__ import annotations

import json
import sys
from contextlib import contextmanager, suppress
from io import StringIO
from itertools import product
from logging import getLogger
from pathlib import Path
from re import MULTILINE, escape, search, sub
from string import Template
from subprocess import CalledProcessError
from typing import TYPE_CHECKING, Any, Literal, assert_never

import tomlkit
from click import command
from rich.pretty import pretty_repr
from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import LiteralScalarString
from tomlkit import TOMLDocument, aot, array, document, table
from tomlkit.exceptions import NonExistentKey
from tomlkit.items import AoT, Array, Table
from typed_settings import EnvLoader, click_options, load_settings, option, settings
from utilities.atomicwrites import writer
from utilities.click import CONTEXT_SETTINGS
from utilities.functions import ensure_class
from utilities.iterables import OneEmptyError, OneNonUniqueError, one
from utilities.logging import basic_config
from utilities.os import is_pytest
from utilities.pathlib import get_repo_root
from utilities.subprocess import run
from utilities.tempfile import TemporaryFile
from utilities.text import strip_and_dedent
from utilities.version import ParseVersionError, Version, parse_version
from utilities.whenever import HOUR, get_now
from whenever import ZonedDateTime
from xdg_base_dirs import xdg_cache_home

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator

    from tomlkit.container import Container
    from utilities.types import PathLike


type HasAppend = Array | list[Any]
type HasSetDefault = Container | StrDict | Table
type StrDict = dict[str, Any]
__version__ = "0.7.0"
_LOADER = EnvLoader("")
_LOGGER = getLogger(__name__)
_MODIFICATIONS: set[str] = set()
_YAML = YAML()


@settings
class Settings:
    coverage: bool = option(default=False, help="Set up '.coveragerc.toml'")
    description: str | None = option(default=None, help="Repo description")
    github__pull_request__pre_commit: bool = option(
        default=True, help="Set up 'pull-request.yaml' pre-commit"
    )
    github__pull_request__pyright: bool = option(
        default=False, help="Set up 'pull-request.yaml' pyright"
    )
    github__pull_request__pytest__os__windows: bool = option(
        default=False, help="Set up 'pull-request.yaml' pytest with Windows"
    )
    github__pull_request__pytest__os__macos: bool = option(
        default=False, help="Set up 'pull-request.yaml' pytest with MacOS"
    )
    github__pull_request__pytest__os__ubuntu: bool = option(
        default=False, help="Set up 'pull-request.yaml' pytest with Ubuntu"
    )
    github__pull_request__pytest__python_version__default: bool = option(
        default=False, help="Set up 'pull-request.yaml' pytest with default Python"
    )
    github__pull_request__pytest__python_version__3_13: bool = option(
        default=False, help="Set up 'pull-request.yaml' pytest with Python 3.13"
    )
    github__pull_request__pytest__python_version__3_14: bool = option(
        default=False, help="Set up 'pull-request.yaml' pytest with Python 3.14"
    )
    github__pull_request__pytest__resolution__highest: bool = option(
        default=False,
        help="Set up 'pull-request.yaml' pytest with the highest resolution",
    )
    github__pull_request__pytest__resolution__lowest_direct: bool = option(
        default=False,
        help="Set up 'pull-request.yaml' pytest with the lowest-direct resolution",
    )
    github__pull_request__ruff: bool = option(
        default=False, help="Set up 'pull-request.yaml' ruff"
    )
    github__push__tag__latest: bool = option(
        default=False, help="Set up 'push.yaml' tagging"
    )
    github__push__publish: bool = option(
        default=False, help="Set up 'push.yaml' publishing"
    )
    github__push__publish__trusted_publishing: bool = option(
        default=False, help="Set up 'push.yaml' with trusted publishing"
    )
    github__push__tag: bool = option(default=False, help="Set up 'push.yaml' tagging")
    github__push__tag__major_minor: bool = option(
        default=False, help="Set up 'push.yaml' with the 'major.minor' tag"
    )
    github__push__tag__major: bool = option(
        default=False, help="Set up 'push.yaml' with the 'major' tag"
    )
    package_name: str | None = option(default=None, help="Package name")
    pre_commit__dockerfmt: bool = option(
        default=False, help="Set up '.pre-commit-config.yaml' dockerfmt"
    )
    pre_commit__prettier: bool = option(
        default=False, help="Set up '.pre-commit-config.yaml' prettier"
    )
    pre_commit__ruff: bool = option(
        default=False, help="Set up '.pre-commit-config.yaml' ruff"
    )
    pre_commit__shell: bool = option(
        default=False, help="Set up '.pre-commit-config.yaml' shell"
    )
    pre_commit__taplo: bool = option(
        default=False, help="Set up '.pre-commit-config.yaml' taplo"
    )
    pre_commit__uv: bool = option(
        default=False, help="Set up '.pre-commit-config.yaml' uv"
    )
    pre_commit__uv__script: str | None = option(
        default=None, help="Set up '.pre-commit-config.yaml' uv lock script"
    )
    pyproject: bool = option(default=False, help="Set up 'pyproject.toml'")
    pyproject__project__optional_dependencies__scripts: bool = option(
        default=False,
        help="Set up 'pyproject.toml' [project.optional-dependencies.scripts]",
    )
    pyproject__tool__uv__indexes: list[tuple[str, str]] = option(
        factory=list, help="Set up 'pyproject.toml' [[uv.tool.index]]"
    )
    pyright: bool = option(default=False, help="Set up 'pyrightconfig.json'")
    pytest: bool = option(default=False, help="Set up 'pytest.toml'")
    pytest__asyncio: bool = option(default=False, help="Set up 'pytest.toml' asyncio_*")
    pytest__ignore_warnings: bool = option(
        default=False, help="Set up 'pytest.toml' filterwarnings"
    )
    pytest__timeout: int | None = option(
        default=None, help="Set up 'pytest.toml' timeout"
    )
    python_package_name: str | None = option(
        default=None, help="Python package name override"
    )
    python_version: str = option(default="3.14", help="Python version")
    readme: bool = option(default=False, help="Set up 'README.md'")
    repo_name: str | None = option(default=None, help="Repo name")
    ruff: bool = option(default=False, help="Set up 'ruff.toml'")
    script: str | None = option(
        default=None, help="Set up a script instead of a package"
    )
    skip_version_bump: bool = option(default=False, help="Skip bump version")

    @property
    def python_package_name_use(self) -> str | None:
        if self.python_package_name is not None:
            return self.python_package_name
        if self.package_name is not None:
            return self.package_name.replace("-", "_")
        return None


_SETTINGS = load_settings(Settings, [_LOADER])


@command(**CONTEXT_SETTINGS)
@click_options(Settings, [_LOADER], show_envvars_in_help=True)
def _main(settings: Settings, /) -> None:
    if is_pytest():
        return
    basic_config(obj=_LOGGER)
    _LOGGER.info(
        strip_and_dedent("""
            Running 'pre-commit-hook-nitpick' (version %s) with settings:
            %s
        """),
        __version__,
        pretty_repr(settings),
    )
    _add_bumpversion_toml(
        pyproject=settings.pyproject,
        python_package_name_use=settings.python_package_name_use,
    )
    _check_versions()
    _run_pre_commit_update()
    _run_ripgrep_and_sd(version=settings.python_version)
    _update_action_file_extensions()
    _update_action_versions()
    _add_pre_commit(
        dockerfmt=settings.pre_commit__dockerfmt,
        prettier=settings.pre_commit__prettier,
        ruff=settings.pre_commit__ruff,
        shell=settings.pre_commit__shell,
        taplo=settings.pre_commit__taplo,
        uv=settings.pre_commit__uv,
        script=settings.script,
    )
    if settings.coverage:
        _add_coveragerc_toml()
    if (
        settings.github__pull_request__pre_commit
        or settings.github__pull_request__pyright
        or settings.github__pull_request__pytest__os__windows
        or settings.github__pull_request__pytest__os__macos
        or settings.github__pull_request__pytest__os__ubuntu
        or settings.github__pull_request__pytest__python_version__default
        or settings.github__pull_request__pytest__python_version__3_13
        or settings.github__pull_request__pytest__python_version__3_14
        or settings.github__pull_request__pytest__resolution__highest
        or settings.github__pull_request__pytest__resolution__lowest_direct
        or settings.github__pull_request__ruff
    ):
        _add_github_pull_request_yaml(
            pre_commit=settings.github__pull_request__pre_commit,
            pyright=settings.github__pull_request__pyright,
            pytest__os__windows=settings.github__pull_request__pytest__os__windows,
            pytest__os__macos=settings.github__pull_request__pytest__os__macos,
            pytest__os__ubuntu=settings.github__pull_request__pytest__os__ubuntu,
            pytest__python_version__default=settings.github__pull_request__pytest__python_version__default,
            pytest__python_version__3_13=settings.github__pull_request__pytest__python_version__3_13,
            pytest__python_version__3_14=settings.github__pull_request__pytest__python_version__3_14,
            pytest__resolution__highest=settings.github__pull_request__pytest__resolution__highest,
            pytest__resolution__lowest_direct=settings.github__pull_request__pytest__resolution__lowest_direct,
            pytest__timeout=settings.pytest__timeout,
            python_version=settings.python_version,
            ruff=settings.ruff,
            script=settings.script,
        )
    if (
        settings.github__push__publish
        or settings.github__push__publish__trusted_publishing
        or settings.github__push__tag
        or settings.github__push__tag__major_minor
        or settings.github__push__tag__major
        or settings.github__push__tag__latest
    ):
        _add_github_push_yaml(
            publish=settings.github__push__publish,
            publish__trusted_publishing=settings.github__push__publish__trusted_publishing,
            tag=settings.github__push__tag,
            tag__major_minor=settings.github__push__tag__major_minor,
            tag__major=settings.github__push__tag__major,
            tag__latest=settings.github__push__tag__latest,
        )
    if (
        settings.pyproject
        or settings.pyproject__project__optional_dependencies__scripts
        or (len(settings.pyproject__tool__uv__indexes) >= 1)
    ):
        _add_pyproject_toml(
            version=settings.python_version,
            description=settings.description,
            package_name=settings.package_name,
            readme=settings.readme,
            optional_dependencies__scripts=settings.pyproject__project__optional_dependencies__scripts,
            python_package_name=settings.python_package_name,
            python_package_name_use=settings.python_package_name_use,
            tool__uv__indexes=settings.pyproject__tool__uv__indexes,
        )
    if settings.pyright:
        _add_pyrightconfig_json(version=settings.python_version, script=settings.script)
    if (
        settings.pytest
        or settings.pytest__asyncio
        or settings.pytest__ignore_warnings
        or (settings.pytest__timeout is not None)
    ):
        _add_pytest_toml(
            asyncio=settings.pytest__asyncio,
            ignore_warnings=settings.pytest__ignore_warnings,
            timeout=settings.pytest__timeout,
            coverage=settings.coverage,
            python_package_name=settings.python_package_name_use,
            script=settings.script,
        )
    if settings.readme:
        _add_readme_md(name=settings.repo_name, description=settings.description)
    if settings.ruff:
        _add_ruff_toml(version=settings.python_version)
    if not settings.skip_version_bump:
        _run_bump_my_version()
    if len(_MODIFICATIONS) >= 1:
        _LOGGER.info(
            "Exiting due to modiciations: %s",
            ", ".join(map(repr, sorted(_MODIFICATIONS))),
        )
        sys.exit(1)


def _add_bumpversion_toml(
    *,
    pyproject: bool = _SETTINGS.pyproject,
    python_package_name_use: str | None = _SETTINGS.python_package_name_use,
) -> None:
    with _yield_bumpversion_toml() as doc:
        tool = _get_table(doc, "tool")
        bumpversion = _get_table(tool, "bumpversion")
        if pyproject:
            files = _get_aot(bumpversion, "files")
            _ensure_aot_contains(
                files,
                _bumpversion_toml_file("pyproject.toml", 'version = "${version}"'),
            )
        if python_package_name_use is not None:
            files = _get_aot(bumpversion, "files")
            _ensure_aot_contains(
                files,
                _bumpversion_toml_file(
                    f"src/{python_package_name_use}/__init__.py",
                    '__version__ = "${version}"',
                ),
            )


def _add_coveragerc_toml() -> None:
    with _yield_toml_doc(".coveragerc.toml") as doc:
        html = _get_table(doc, "html")
        html["directory"] = ".coverage/html"
        report = _get_table(doc, "report")
        exclude_also = _get_array(report, "exclude_also")
        _ensure_contains(exclude_also, "@overload", "if TYPE_CHECKING:")
        report["fail_under"] = 100.0
        report["skip_covered"] = True
        report["skip_empty"] = True
        run = _get_table(doc, "run")
        run["branch"] = True
        run["data_file"] = ".coverage/data"
        run["parallel"] = True


def _add_github_pull_request_yaml(
    *,
    pre_commit: bool = _SETTINGS.github__pull_request__pre_commit,
    pyright: bool = _SETTINGS.github__pull_request__pyright,
    pytest__os__windows: bool = _SETTINGS.github__pull_request__pytest__os__windows,
    pytest__os__macos: bool = _SETTINGS.github__pull_request__pytest__os__macos,
    pytest__os__ubuntu: bool = _SETTINGS.github__pull_request__pytest__os__ubuntu,
    pytest__python_version__default: bool = _SETTINGS.github__pull_request__pytest__python_version__default,
    pytest__python_version__3_13: bool = _SETTINGS.github__pull_request__pytest__python_version__3_13,
    pytest__python_version__3_14: bool = _SETTINGS.github__pull_request__pytest__python_version__3_14,
    pytest__resolution__highest: bool = _SETTINGS.github__pull_request__pytest__resolution__highest,
    pytest__resolution__lowest_direct: bool = _SETTINGS.github__pull_request__pytest__resolution__lowest_direct,
    pytest__timeout: int | None = _SETTINGS.pytest__timeout,
    python_version: str = _SETTINGS.python_version,
    ruff: bool = _SETTINGS.github__pull_request__ruff,
    script: str | None = _SETTINGS.script,
) -> None:
    with _yield_yaml_dict(".github/workflows/pull-request.yaml") as dict_:
        dict_["name"] = "pull-request"
        on = _get_dict(dict_, "on")
        pull_request = _get_dict(on, "pull_request")
        branches = _get_list(pull_request, "branches")
        _ensure_contains(branches, "master")
        schedule = _get_list(on, "schedule")
        _ensure_contains(schedule, {"cron": "0 0 * * *"})
        jobs = _get_dict(dict_, "jobs")
        if pre_commit:
            pre_commit_dict = _get_dict(jobs, "pre-commit")
            pre_commit_dict["runs-on"] = "ubuntu-latest"
            steps = _get_list(pre_commit_dict, "steps")
            steps_dict = _ensure_contains_partial(
                steps,
                {"name": "Run 'pre-commit'", "uses": "dycw/action-pre-commit@latest"},
                extra={
                    "with": {
                        "token": "${{ secrets.GITHUB_TOKEN }}",
                        "repos": LiteralScalarString(
                            strip_and_dedent("""
                                dycw/pre-commit-hook-nitpick
                                pre-commit/pre-commit-hooks
                            """)
                        ),
                    }
                },
            )
        if pyright:
            pyright_dict = _get_dict(jobs, "pyright")
            pyright_dict["runs-on"] = "ubuntu-latest"
            steps = _get_list(pyright_dict, "steps")
            steps_dict = _ensure_contains_partial(
                steps,
                {"name": "Run 'pyright'", "uses": "dycw/action-pyright@latest"},
                extra={
                    "with": {
                        "token": "${{ secrets.GITHUB_TOKEN }}",
                        "python-version": python_version,
                    }
                },
            )
            if script is not None:
                with_ = _get_dict(steps_dict, "with")
                with_["with-requirements"] = script
        if (
            pytest__os__windows
            or pytest__os__macos
            or pytest__os__ubuntu
            or pytest__python_version__default
            or pytest__python_version__3_13
            or pytest__python_version__3_14
            or pytest__resolution__highest
            or pytest__resolution__lowest_direct
        ):
            pytest_dict = _get_dict(jobs, "pytest")
            env = _get_dict(pytest_dict, "env")
            env["CI"] = "1"
            pytest_dict["name"] = (
                "pytest (${{ matrix.os }}, ${{ matrix.python-version }}, ${{ matrix.resolution }})"
            )
            pytest_dict["runs-on"] = "${{ matrix.os }}"
            steps = _get_list(pytest_dict, "steps")
            steps_dict = _ensure_contains_partial(
                steps,
                {"name": "Run 'pytest'", "uses": "dycw/action-pytest@latest"},
                extra={
                    "with": {
                        "token": "${{ secrets.GITHUB_TOKEN }}",
                        "python-version": "${{ matrix.python-version }}",
                        "resolution": "${{ matrix.resolution }}",
                    }
                },
            )
            if script is not None:
                with_ = _get_dict(steps_dict, "with")
                with_["with-requirements"] = script
            strategy_dict = _get_dict(pytest_dict, "strategy")
            strategy_dict["fail-fast"] = False
            matrix = _get_dict(strategy_dict, "matrix")
            os = _get_list(matrix, "os")
            if pytest__os__windows:
                _ensure_contains(os, "windows-latest")
            if pytest__os__macos:
                _ensure_contains(os, "macos-latest")
            if pytest__os__ubuntu:
                _ensure_contains(os, "ubuntu-latest")
            python_version_dict = _get_list(matrix, "python-version")
            if pytest__python_version__default:
                _ensure_contains(python_version_dict, python_version)
            if pytest__python_version__3_13:
                _ensure_contains(python_version_dict, "3.13")
            if pytest__python_version__3_14:
                _ensure_contains(python_version_dict, "3.14")
            resolution = _get_list(matrix, "resolution")
            if pytest__resolution__highest:
                _ensure_contains(resolution, "highest")
            if pytest__resolution__lowest_direct:
                _ensure_contains(resolution, "lowest-direct")
            if pytest__timeout is not None:
                pytest_dict["timeout-minutes"] = max(round(pytest__timeout / 60), 1)
        if ruff:
            ruff_dict = _get_dict(jobs, "ruff")
            ruff_dict["runs-on"] = "ubuntu-latest"
            steps = _get_list(ruff_dict, "steps")
            _ensure_contains(
                steps,
                {
                    "name": "Run 'ruff'",
                    "uses": "dycw/action-ruff@latest",
                    "with": {"token": "${{ secrets.GITHUB_TOKEN }}"},
                },
            )


def _add_github_push_yaml(
    *,
    publish: bool = _SETTINGS.github__push__publish,
    publish__trusted_publishing: bool = _SETTINGS.github__push__publish__trusted_publishing,
    tag: bool = _SETTINGS.github__push__tag,
    tag__major_minor: bool = _SETTINGS.github__push__tag__major_minor,
    tag__major: bool = _SETTINGS.github__push__tag__major,
    tag__latest: bool = _SETTINGS.github__push__tag__latest,
) -> None:
    with _yield_yaml_dict(".github/workflows/push.yaml") as dict_:
        dict_["name"] = "push"
        on = _get_dict(dict_, "on")
        push = _get_dict(on, "push")
        branches = _get_list(push, "branches")
        _ensure_contains(branches, "master")
        jobs = _get_dict(dict_, "jobs")
        if publish or publish__trusted_publishing:
            publish_dict = _get_dict(jobs, "publish")
            environment = _get_dict(publish_dict, "environment")
            environment["name"] = "pypi"
            permissions = _get_dict(publish_dict, "permissions")
            permissions["id-token"] = "write"
            publish_dict["runs-on"] = "ubuntu-latest"
            steps = _get_list(publish_dict, "steps")
            steps_dict = _ensure_contains_partial(
                steps,
                {
                    "name": "Build and publish package",
                    "uses": "dycw/action-publish@latest",
                },
                extra={"with": {"token": "${{ secrets.GITHUB_TOKEN }}"}},
            )
            if publish__trusted_publishing:
                with_ = _get_dict(steps_dict, "with")
                with_["trusted-publishing"] = True
        if tag or tag__major_minor or tag__major or tag__latest:
            tag_dict = _get_dict(jobs, "tag")
            tag_dict["runs-on"] = "ubuntu-latest"
            steps = _get_list(tag_dict, "steps")
            steps_dict = _ensure_contains_partial(
                steps,
                {"name": "Tag latest commit", "uses": "dycw/action-tag@latest"},
                extra={"with": {"token": "${{ secrets.GITHUB_TOKEN }}"}},
            )
            if tag__major_minor:
                with_ = _get_dict(steps_dict, "with")
                with_["major-minor"] = True
            if tag__major:
                with_ = _get_dict(steps_dict, "with")
                with_["major"] = True
            if tag__latest:
                with_ = _get_dict(steps_dict, "with")
                with_["latest"] = True


def _add_pre_commit(
    *,
    dockerfmt: bool = _SETTINGS.pre_commit__dockerfmt,
    prettier: bool = _SETTINGS.pre_commit__prettier,
    ruff: bool = _SETTINGS.pre_commit__ruff,
    shell: bool = _SETTINGS.pre_commit__shell,
    taplo: bool = _SETTINGS.pre_commit__taplo,
    uv: bool = _SETTINGS.pre_commit__uv,
    script: str | None = _SETTINGS.script,
) -> None:
    with _yield_yaml_dict(".pre-commit-config.yaml") as dict_:
        _ensure_pre_commit_repo(
            dict_, "https://github.com/dycw/pre-commit-hook-nitpick", "nitpick"
        )
        pre_com_url = "https://github.com/pre-commit/pre-commit-hooks"
        _ensure_pre_commit_repo(dict_, pre_com_url, "check-executables-have-shebangs")
        _ensure_pre_commit_repo(dict_, pre_com_url, "check-merge-conflict")
        _ensure_pre_commit_repo(dict_, pre_com_url, "check-symlinks")
        _ensure_pre_commit_repo(dict_, pre_com_url, "destroyed-symlinks")
        _ensure_pre_commit_repo(dict_, pre_com_url, "detect-private-key")
        _ensure_pre_commit_repo(dict_, pre_com_url, "end-of-file-fixer")
        _ensure_pre_commit_repo(
            dict_, pre_com_url, "mixed-line-ending", args=("add", ["--fix=lf"])
        )
        _ensure_pre_commit_repo(dict_, pre_com_url, "no-commit-to-branch")
        _ensure_pre_commit_repo(
            dict_, pre_com_url, "pretty-format-json", args=("add", ["--autofix"])
        )
        _ensure_pre_commit_repo(dict_, pre_com_url, "no-commit-to-branch")
        _ensure_pre_commit_repo(dict_, pre_com_url, "trailing-whitespace")
        if dockerfmt:
            _ensure_pre_commit_repo(
                dict_,
                "https://github.com/reteps/dockerfmt",
                "dockerfmt",
                args=("add", ["--newline", "--write"]),
            )
        if prettier:
            _ensure_pre_commit_repo(
                dict_,
                "local",
                "prettier",
                name="prettier",
                entry="npx prettier --write",
                language="system",
                types_or=["markdown", "yaml"],
            )
        if ruff:
            ruff_url = "https://github.com/astral-sh/ruff-pre-commit"
            _ensure_pre_commit_repo(
                dict_, ruff_url, "ruff-check", args=("add", ["--fix"])
            )
            _ensure_pre_commit_repo(dict_, ruff_url, "ruff-format")
        if shell:
            _ensure_pre_commit_repo(
                dict_, "https://github.com/scop/pre-commit-shfmt", "shfmt"
            )
            _ensure_pre_commit_repo(
                dict_, "https://github.com/koalaman/shellcheck-precommit", "shellcheck"
            )
        if taplo:
            _ensure_pre_commit_repo(
                dict_,
                "https://github.com/compwa/taplo-pre-commit",
                "taplo-format",
                args=(
                    "exact",
                    [
                        "--option",
                        "indent_tables=true",
                        "--option",
                        "indent_entries=true",
                        "--option",
                        "reorder_keys=true",
                    ],
                ),
            )
        if uv:
            _ensure_pre_commit_repo(
                dict_,
                "https://github.com/astral-sh/uv-pre-commit",
                "uv-lock",
                files=None if script is None else rf"^{escape(script)}$",
                args=(
                    "add",
                    ["--upgrade"] + ([] if script is None else [f"--script={script}"]),
                ),
            )


def _add_pyproject_toml(
    *,
    version: str = _SETTINGS.python_version,
    description: str | None = _SETTINGS.description,
    package_name: str | None = _SETTINGS.package_name,
    readme: bool = _SETTINGS.readme,
    optional_dependencies__scripts: bool = _SETTINGS.pyproject__project__optional_dependencies__scripts,
    python_package_name: str | None = _SETTINGS.python_package_name,
    python_package_name_use: str | None = _SETTINGS.python_package_name_use,
    tool__uv__indexes: list[tuple[str, str]] = _SETTINGS.pyproject__tool__uv__indexes,
) -> None:
    with _yield_toml_doc("pyproject.toml") as doc:
        build_system = _get_table(doc, "build-system")
        build_system["build-backend"] = "uv_build"
        build_system["requires"] = ["uv_build"]
        project = _get_table(doc, "project")
        project["requires-python"] = f">= {version}"
        if description is not None:
            project["description"] = description
        if package_name is not None:
            project["name"] = package_name
        if readme:
            project["readme"] = "README.md"
        project.setdefault("version", "0.1.0")
        dependency_groups = _get_table(doc, "dependency-groups")
        dev = _get_array(dependency_groups, "dev")
        _ensure_contains(dev, "dycw-utilities[test]")
        _ensure_contains(dev, "rich")
        if optional_dependencies__scripts:
            optional_dependencies = _get_table(project, "optional-dependencies")
            scripts = _get_array(optional_dependencies, "scripts")
            _ensure_contains(scripts, "click >=8.3.1")
        if python_package_name is not None:
            tool = _get_table(doc, "tool")
            uv = _get_table(tool, "uv")
            build_backend = _get_table(uv, "build-backend")
            build_backend["module-name"] = python_package_name_use
            build_backend["module-root"] = "src"
        if len(tool__uv__indexes) >= 1:
            tool = _get_table(doc, "tool")
            uv = _get_table(tool, "uv")
            indexes = _get_aot(uv, "index")
            for name, url in tool__uv__indexes:
                index = table()
                index["explicit"] = True
                index["name"] = name
                index["url"] = url
                _ensure_aot_contains(indexes, index)


def _add_pyrightconfig_json(
    *, version: str = _SETTINGS.python_version, script: str | None = _SETTINGS.script
) -> None:
    with _yield_json_dict("pyrightconfig.json") as dict_:
        dict_["deprecateTypingAliases"] = True
        dict_["enableReachabilityAnalysis"] = False
        dict_["include"] = ["src" if script is None else script]
        dict_["pythonVersion"] = version
        dict_["reportCallInDefaultInitializer"] = True
        dict_["reportImplicitOverride"] = True
        dict_["reportImplicitStringConcatenation"] = True
        dict_["reportImportCycles"] = True
        dict_["reportMissingSuperCall"] = True
        dict_["reportMissingTypeArgument"] = False
        dict_["reportMissingTypeStubs"] = False
        dict_["reportPrivateImportUsage"] = False
        dict_["reportPrivateUsage"] = False
        dict_["reportPropertyTypeMismatch"] = True
        dict_["reportUninitializedInstanceVariable"] = True
        dict_["reportUnknownArgumentType"] = False
        dict_["reportUnknownMemberType"] = False
        dict_["reportUnknownParameterType"] = False
        dict_["reportUnknownVariableType"] = False
        dict_["reportUnnecessaryComparison"] = False
        dict_["reportUnnecessaryTypeIgnoreComment"] = True
        dict_["reportUnusedCallResult"] = True
        dict_["reportUnusedImport"] = False
        dict_["reportUnusedVariable"] = False
        dict_["typeCheckingMode"] = "strict"


def _add_pytest_toml(
    *,
    asyncio: bool = _SETTINGS.pytest__asyncio,
    ignore_warnings: bool = _SETTINGS.pytest__ignore_warnings,
    timeout: int | None = _SETTINGS.pytest__timeout,
    coverage: bool = _SETTINGS.coverage,
    python_package_name: str | None = _SETTINGS.python_package_name_use,
    script: str | None = _SETTINGS.script,
) -> None:
    with _yield_toml_doc("pytest.toml") as doc:
        pytest = _get_table(doc, "pytest")
        addopts = _get_array(pytest, "addopts")
        _ensure_contains(
            addopts,
            "-ra",
            "-vv",
            "--color=auto",
            "--durations=10",
            "--durations-min=10",
        )
        if coverage and (python_package_name is not None):
            _ensure_contains(
                addopts,
                f"--cov={python_package_name}",
                "--cov-config=.coveragerc.toml",
                "--cov-report=html",
            )
        pytest["collect_imported_tests"] = False
        pytest["empty_parameter_set_mark"] = "fail_at_collect"
        filterwarnings = _get_array(pytest, "filterwarnings")
        _ensure_contains(filterwarnings, "error")
        pytest["minversion"] = "9.0"
        pytest["strict"] = True
        testpaths = _get_array(pytest, "testpaths")
        _ensure_contains(testpaths, "src/tests" if script is None else "tests")
        pytest["xfail_strict"] = True
        if asyncio:
            pytest["asyncio_default_fixture_loop_scope"] = "function"
            pytest["asyncio_mode"] = "auto"
        if ignore_warnings:
            filterwarnings = _get_array(pytest, "filterwarnings")
            _ensure_contains(
                filterwarnings,
                "ignore::DeprecationWarning",
                "ignore::ResourceWarning",
                "ignore::RuntimeWarning",
            )
        if timeout is not None:
            pytest["timeout"] = str(timeout)


def _add_readme_md(
    *,
    name: str | None = _SETTINGS.package_name,
    description: str | None = _SETTINGS.description,
) -> None:
    with _yield_text_file("README.md") as temp:
        lines: list[str] = []
        if name is not None:
            lines.append(f"# `{name}`")
        if description is not None:
            lines.append(description)
        _ = temp.write_text("\n\n".join(lines))


def _add_ruff_toml(*, version: str = _SETTINGS.python_version) -> None:
    with _yield_toml_doc("ruff.toml") as doc:
        doc["target-version"] = f"py{version.replace('.', '')}"
        doc["unsafe-fixes"] = True
        fmt = _get_table(doc, "format")
        fmt["preview"] = True
        fmt["skip-magic-trailing-comma"] = True
        lint = _get_table(doc, "lint")
        lint["explicit-preview-rules"] = True
        fixable = _get_array(lint, "fixable")
        _ensure_contains(fixable, "ALL")
        ignore = _get_array(lint, "ignore")
        _ensure_contains(
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
        lint["preview"] = True
        select = _get_array(lint, "select")
        selected_rules = [
            "RUF022",  # unsorted-dunder-all
            "RUF029",  # unused-async
        ]
        _ensure_contains(select, "ALL", *selected_rules)
        extend_per_file_ignores = _get_table(lint, "extend-per-file-ignores")
        test_py = _get_array(extend_per_file_ignores, "test_*.py")
        test_py_rules = [
            "S101",  # assert
            "SLF001",  # private-member-access
        ]
        _ensure_contains(test_py, *test_py_rules)
        _ensure_not_contains(ignore, *selected_rules, *test_py_rules)
        bugbear = _get_table(lint, "flake8-bugbear")
        extend_immutable_calls = _get_array(bugbear, "extend-immutable-calls")
        _ensure_contains(extend_immutable_calls, "typing.cast")
        tidy_imports = _get_table(lint, "flake8-tidy-imports")
        tidy_imports["ban-relative-imports"] = "all"
        isort = _get_table(lint, "isort")
        req_imps = _get_array(isort, "required-imports")
        _ensure_contains(req_imps, "from __future__ import annotations")
        isort["split-on-trailing-comma"] = False


def _bumpversion_toml_file(path: PathLike, template: str, /) -> Table:
    tab = table()
    tab["filename"] = str(path)
    tab["search"] = Template(template).substitute(version="{current_version}")
    tab["replace"] = Template(template).substitute(version="{new_version}")
    return tab


def _check_versions() -> None:
    version = _get_version_from_bump_toml()
    try:
        _set_version(version)
    except CalledProcessError:
        msg = f"Inconsistent versions; got be {version}"
        raise ValueError(msg) from None


def _ensure_aot_contains(array: AoT, /, *tables: Table) -> None:
    for table_ in tables:
        if table_ not in array:
            array.append(table_)


def _ensure_contains(array: HasAppend, /, *objs: Any) -> None:
    if isinstance(array, AoT):
        msg = f"Use {_ensure_aot_contains.__name__!r} instead of {_ensure_contains.__name__!r}"
        raise TypeError(msg)
    for obj in objs:
        if obj not in array:
            array.append(obj)


def _ensure_contains_partial(
    container: HasAppend, partial: StrDict, /, *, extra: StrDict | None = None
) -> StrDict:
    try:
        return _get_partial_dict(container, partial, skip_log=True)
    except OneEmptyError:
        dict_ = partial | ({} if extra is None else extra)
        container.append(dict_)
        return dict_


def _ensure_not_contains(array: Array, /, *objs: Any) -> None:
    for obj in objs:
        try:
            index = next(i for i, o in enumerate(array) if o == obj)
        except StopIteration:
            pass
        else:
            del array[index]


def _ensure_pre_commit_repo(
    pre_commit_dict: StrDict,
    url: str,
    id_: str,
    /,
    *,
    name: str | None = None,
    entry: str | None = None,
    language: str | None = None,
    files: str | None = None,
    types_or: list[str] | None = None,
    args: tuple[Literal["add", "exact"], list[str]] | None = None,
) -> None:
    repos_list = _get_list(pre_commit_dict, "repos")
    repo_dict = _ensure_contains_partial(
        repos_list, {"repo": url}, extra={} if url == "local" else {"rev": "master"}
    )
    hooks_list = _get_list(repo_dict, "hooks")
    hook_dict = _ensure_contains_partial(hooks_list, {"id": id_})
    if name is not None:
        hook_dict["name"] = name
    if entry is not None:
        hook_dict["entry"] = entry
    if language is not None:
        hook_dict["language"] = language
    if files is not None:
        hook_dict["files"] = files
    if types_or is not None:
        hook_dict["types_or"] = types_or
    if args is not None:
        match args:
            case "add", list() as args_i:
                hook_args = _get_list(hook_dict, "args")
                _ensure_contains(hook_args, *args_i)
            case "exact", list() as args_i:
                hook_dict["args"] = args_i
            case never:
                assert_never(never)


def _get_aot(container: HasSetDefault, key: str, /) -> AoT:
    return ensure_class(container.setdefault(key, aot()), AoT)


def _get_array(container: HasSetDefault, key: str, /) -> Array:
    return ensure_class(container.setdefault(key, array()), Array)


def _get_dict(container: HasSetDefault, key: str, /) -> StrDict:
    return ensure_class(container.setdefault(key, {}), dict)


def _get_list(container: HasSetDefault, key: str, /) -> list[Any]:
    return ensure_class(container.setdefault(key, []), list)


def _get_partial_dict(
    iterable: Iterable[Any], dict_: StrDict, /, *, skip_log: bool = False
) -> StrDict:
    try:
        return one(
            d
            for d in iterable
            if isinstance(d, dict)
            and set(dict_).issubset(d)
            and all(d[k] == v for k, v in dict_.items())
        )
    except OneEmptyError:
        if not skip_log:
            _LOGGER.exception(
                "Expected %s to contain %s (as a partial)",
                pretty_repr(iterable),
                pretty_repr(dict_),
            )
        raise
    except OneNonUniqueError as error:
        _LOGGER.exception(
            "Expected %s to contain %s uniquely (as a partial); got %s, %s and perhaps more",
            pretty_repr(iterable),
            pretty_repr(dict_),
            pretty_repr(error.first),
            pretty_repr(error.second),
        )
        raise


def _get_table(container: HasSetDefault, key: str, /) -> Table:
    return ensure_class(container.setdefault(key, table()), Table)


def _get_version_from_bump_toml(*, obj: TOMLDocument | str | None = None) -> Version:
    match obj:
        case TOMLDocument() as obj:
            tool = _get_table(obj, "tool")
            bumpversion = _get_table(tool, "bumpversion")
            return parse_version(str(bumpversion["current_version"]))
        case str() as obj:
            return _get_version_from_bump_toml(obj=tomlkit.parse(obj))
        case None:
            with _yield_bumpversion_toml() as obj:
                return _get_version_from_bump_toml(obj=obj)
        case never:
            assert_never(never)


def _get_version_from_git_show() -> Version:
    text = run("git", "show", "origin/master:.bumpversion.toml", return_=True)
    return _get_version_from_bump_toml(obj=text.rstrip("\n"))


def _get_version_from_git_tag() -> Version:
    text = run("git", "tag", "--points-at", "origin/master", return_=True)
    for line in text.splitlines():
        with suppress(ParseVersionError):
            return parse_version(line)
    msg = "No valid version from 'git tag'"
    raise ValueError(msg)


def _run_bump_my_version() -> None:
    if search("template", str(get_repo_root())):
        return

    def run_set_version(version: Version, /) -> None:
        _LOGGER.info("Setting version to %s...", version)
        _set_version(version)
        _MODIFICATIONS.add(".bumpversion.toml")

    try:
        prev = _get_version_from_git_tag()
    except (CalledProcessError, ValueError):
        try:
            prev = _get_version_from_git_show()
        except (CalledProcessError, ParseVersionError, NonExistentKey):
            run_set_version(Version(0, 1, 0))
            return
    current = _get_version_from_bump_toml()
    if current not in {prev.bump_patch(), prev.bump_minor(), prev.bump_major()}:
        run_set_version(prev.bump_patch())


def _run_pre_commit_update() -> None:
    pre_commit_config = Path(".pre-commit-config.yaml")
    cache = xdg_cache_home() / "pre-commit-hook-nitpick" / get_repo_root().name

    def run_autoupdate() -> None:
        current = pre_commit_config.read_text()
        run("pre-commit", "autoupdate", print=True)
        with writer(cache, overwrite=True) as temp:
            _ = temp.write_text(get_now().format_iso())
        if pre_commit_config.read_text() != current:
            _MODIFICATIONS.add(str(pre_commit_config))

    try:
        text = cache.read_text()
    except FileNotFoundError:
        run_autoupdate()
    else:
        prev = ZonedDateTime.parse_iso(text.rstrip("\n"))
        if prev < (get_now() - 12 * HOUR):
            run_autoupdate()


def _run_ripgrep_and_sd(*, version: str = _SETTINGS.python_version) -> None:
    try:
        files = run(
            "rg",
            "--files-with-matches",
            "--pcre2",
            rf'# requires-python = ">=(?!{version})\d+\.\d+"',
            return_=True,
        ).splitlines()
    except CalledProcessError as error:
        if error.returncode == 1:
            return
        raise
    paths = list(map(Path, files))
    for path in paths:
        with _yield_text_file(path) as temp:
            text = sub(
                r'# requires-python = ">=\d+\.\d+"',
                rf'# requires-python = ">={version}"',
                path.read_text(),
                flags=MULTILINE,
            )
            _ = temp.write_text(text)


def _set_version(version: Version, /) -> None:
    run(
        "bump-my-version", "replace", "--new-version", str(version), ".bumpversion.toml"
    )


def _update_action_file_extensions() -> None:
    try:
        paths = list(Path(".github").rglob("**/*.yml"))
    except FileNotFoundError:
        return
    for path in paths:
        new = path.with_suffix(".yaml")
        _LOGGER.info("Renaming '%s' -> '%s'...", path, new)
        _ = path.rename(new)


def _update_action_versions() -> None:
    try:
        paths = list(Path(".github").rglob("**/*.yaml"))
    except FileNotFoundError:
        return
    versions = {
        "actions/checkout": "v6",
        "actions/setup-python": "v6",
        "astral-sh/ruff-action": "v3",
        "astral-sh/setup-uv": "v7",
    }
    for path, (action, version) in product(paths, versions.items()):
        text = sub(
            rf"^(\s*- uses: {action})@.+$",
            rf"\1@{version}",
            path.read_text(),
            flags=MULTILINE,
        )
        with _yield_yaml_dict(path) as dict_:
            dict_.clear()
            dict_.update(_YAML.load(text))


def _write_path_and_modified(verb: str, src: PathLike, dest: PathLike, /) -> None:
    src, dest = map(Path, [src, dest])
    _LOGGER.info("%s '%s'...", verb, dest)
    text = src.read_text().rstrip("\n") + "\n"
    with writer(dest, overwrite=True) as temp:
        _ = temp.write_text(text)
    _MODIFICATIONS.add(str(dest))


def _yaml_dump(obj: Any, /) -> str:
    stream = StringIO()
    _YAML.dump(obj, stream)
    return stream.getvalue()


@contextmanager
def _yield_bumpversion_toml() -> Iterator[TOMLDocument]:
    with _yield_toml_doc(".bumpversion.toml") as doc:
        tool = _get_table(doc, "tool")
        bumpversion = _get_table(tool, "bumpversion")
        bumpversion["allow_dirty"] = True
        bumpversion.setdefault("current_version", str(Version(0, 1, 0)))
        yield doc


@contextmanager
def _yield_json_dict(path: PathLike, /) -> Iterator[StrDict]:
    with _yield_write_context(path, json.loads, dict, json.dumps) as dict_:
        yield dict_


@contextmanager
def _yield_write_context[T](
    path: PathLike,
    loads: Callable[[str], T],
    get_default: Callable[[], T],
    dumps: Callable[[T], str],
    /,
) -> Iterator[T]:
    path = Path(path)

    def run_write(verb: str, data: T, /) -> None:
        with writer(path, overwrite=True) as temp:
            _ = temp.write_text(dumps(data))
            _write_path_and_modified(verb, temp, path)

    try:
        data = loads(path.read_text())
    except FileNotFoundError:
        yield (default := get_default())
        run_write("Writing", default)
    else:
        yield data
        current = loads(path.read_text())
        if data != current:
            run_write("Modifying", data)


@contextmanager
def _yield_yaml_dict(path: PathLike, /) -> Iterator[StrDict]:
    with _yield_write_context(path, _YAML.load, dict, _yaml_dump) as dict_:
        yield dict_


@contextmanager
def _yield_text_file(path: PathLike, /) -> Iterator[Path]:
    path = Path(path)

    try:
        current = path.read_text()
    except FileNotFoundError:
        with TemporaryFile() as temp:
            yield temp
            _write_path_and_modified("Writing", temp, path)
    else:
        with TemporaryFile() as temp:
            yield temp
            if temp.read_text().rstrip("\n") != current.rstrip("\n"):
                _write_path_and_modified("Writing", temp, path)


@contextmanager
def _yield_toml_doc(path: PathLike, /) -> Iterator[TOMLDocument]:
    with _yield_write_context(path, tomlkit.parse, document, tomlkit.dumps) as doc:
        yield doc


if __name__ == "__main__":
    _main()
