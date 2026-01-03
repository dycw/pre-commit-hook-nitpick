from __future__ import annotations

import json
from contextlib import contextmanager, suppress
from io import StringIO
from itertools import product
from pathlib import Path
from re import MULTILINE, escape, sub
from shlex import join
from string import Template
from subprocess import CalledProcessError
from typing import TYPE_CHECKING, Any, Literal, assert_never

import tomlkit
from rich.pretty import pretty_repr
from ruamel.yaml.scalarstring import LiteralScalarString
from tomlkit import TOMLDocument, aot, array, document, table
from tomlkit.exceptions import NonExistentKey
from tomlkit.items import AoT, Array, Table
from utilities.atomicwrites import writer
from utilities.functions import ensure_class
from utilities.iterables import OneEmptyError, OneNonUniqueError, one
from utilities.pathlib import get_repo_root
from utilities.subprocess import append_text, ripgrep, run
from utilities.tempfile import TemporaryFile
from utilities.text import strip_and_dedent
from utilities.version import ParseVersionError, Version, parse_version
from utilities.whenever import HOUR, get_now
from whenever import ZonedDateTime
from xdg_base_dirs import xdg_cache_home

from conformalize.constants import (
    BUMPVERSION_TOML,
    COVERAGERC_TOML,
    ENVRC,
    GITHUB_PULL_REQUEST_YAML,
    GITHUB_PUSH_YAML,
    PRE_COMMIT_CONFIG_YAML,
    PYPROJECT_TOML,
    PYRIGHTCONFIG_JSON,
    PYTEST_TOML,
    README_MD,
    RUFF_TOML,
    YAML_INSTANCE,
)
from conformalize.logging import LOGGER
from conformalize.settings import SETTINGS

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator, MutableSet

    from utilities.types import PathLike

    from conformalize.types import HasAppend, HasSetDefault, StrDict


def add_bumpversion_toml(
    *,
    modifications: MutableSet[Path] | None = None,
    pyproject: bool = SETTINGS.pyproject,
    python_package_name_use: str | None = SETTINGS.python_package_name_use,
) -> None:
    with yield_bumpversion_toml(modifications=modifications) as doc:
        tool = get_table(doc, "tool")
        bumpversion = get_table(tool, "bumpversion")
        if pyproject:
            files = get_aot(bumpversion, "files")
            ensure_aot_contains(
                files,
                _add_bumpversion_toml_file(PYPROJECT_TOML, 'version = "${version}"'),
            )
        if python_package_name_use is not None:
            files = get_aot(bumpversion, "files")
            ensure_aot_contains(
                files,
                _add_bumpversion_toml_file(
                    f"src/{python_package_name_use}/__init__.py",
                    '__version__ = "${version}"',
                ),
            )


def _add_bumpversion_toml_file(path: PathLike, template: str, /) -> Table:
    tab = table()
    tab["filename"] = str(path)
    tab["search"] = Template(template).substitute(version="{current_version}")
    tab["replace"] = Template(template).substitute(version="{new_version}")
    return tab


##


def add_coveragerc_toml(*, modifications: MutableSet[Path] | None = None) -> None:
    with yield_toml_doc(COVERAGERC_TOML, modifications=modifications) as doc:
        html = get_table(doc, "html")
        html["directory"] = ".coverage/html"
        report = get_table(doc, "report")
        exclude_also = get_array(report, "exclude_also")
        ensure_contains(exclude_also, "@overload", "if TYPE_CHECKING:")
        report["fail_under"] = 100.0
        report["skip_covered"] = True
        report["skip_empty"] = True
        run = get_table(doc, "run")
        run["branch"] = True
        run["data_file"] = ".coverage/data"
        run["parallel"] = True


##


def add_envrc(
    *,
    modifications: MutableSet[Path] | None = None,
    uv: bool = False,
    version: str = SETTINGS.python_version,
    script: str | None = SETTINGS.script,
) -> None:
    with yield_text_file(ENVRC, modifications=modifications) as temp:
        shebang = strip_and_dedent("""
            #!/usr/bin/env sh
            # shellcheck source=/dev/null
        """)
        append_text(temp, shebang, skip_if_present=True, flags=MULTILINE, blank_lines=2)

        echo = strip_and_dedent("""
            # echo
            echo_date() { echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*" >&2; }
        """)
        append_text(temp, echo, skip_if_present=True, flags=MULTILINE, blank_lines=2)

        if uv:
            uv_sync_args: list[str] = ["uv", "sync"]
            if script is None:
                uv_sync_args.extend(["--all-extras", "--all-groups"])
            uv_sync_args.extend(["--active", "--locked"])
            if script is not None:
                uv_sync_args.extend(["--script", script])
            uv_sync = join(uv_sync_args)
            uv_text = strip_and_dedent(f"""
                # uv
                export UV_MANAGED_PYTHON='true'
                export UV_PRERELEASE='disallow'
                export UV_PYTHON='{version}'
                if ! command -v uv >/dev/null 2>&1; then
                    echo_date "ERROR: 'uv' not found" && exit 1
                fi
                activate='.venv/bin/activate'
                if [ -f $activate ]; then
                    . $activate
                else
                    uv venv
                fi
                {uv_sync}
            """)
            append_text(
                temp, uv_text, skip_if_present=True, flags=MULTILINE, blank_lines=2
            )


##


def add_github_pull_request_yaml(
    *,
    modifications: MutableSet[Path] | None = None,
    pre_commit: bool = SETTINGS.github__pull_request__pre_commit,
    pyright: bool = SETTINGS.github__pull_request__pyright,
    pytest__os__windows: bool = SETTINGS.github__pull_request__pytest__os__windows,
    pytest__os__macos: bool = SETTINGS.github__pull_request__pytest__os__macos,
    pytest__os__ubuntu: bool = SETTINGS.github__pull_request__pytest__os__ubuntu,
    pytest__python_version__default: bool = SETTINGS.github__pull_request__pytest__python_version__default,
    pytest__python_version__3_12: bool = SETTINGS.github__pull_request__pytest__python_version__3_12,
    pytest__python_version__3_13: bool = SETTINGS.github__pull_request__pytest__python_version__3_13,
    pytest__python_version__3_14: bool = SETTINGS.github__pull_request__pytest__python_version__3_14,
    pytest__resolution__highest: bool = SETTINGS.github__pull_request__pytest__resolution__highest,
    pytest__resolution__lowest_direct: bool = SETTINGS.github__pull_request__pytest__resolution__lowest_direct,
    pytest__timeout: int | None = SETTINGS.pytest__timeout,
    python_version: str = SETTINGS.python_version,
    ruff: bool = SETTINGS.github__pull_request__ruff,
    script: str | None = SETTINGS.script,
) -> None:
    with yield_yaml_dict(
        GITHUB_PULL_REQUEST_YAML, modifications=modifications
    ) as dict_:
        dict_["name"] = "pull-request"
        on = get_dict(dict_, "on")
        pull_request = get_dict(on, "pull_request")
        branches = get_list(pull_request, "branches")
        ensure_contains(branches, "master")
        schedule = get_list(on, "schedule")
        ensure_contains(schedule, {"cron": "0 0 * * *"})
        jobs = get_dict(dict_, "jobs")
        if pre_commit:
            pre_commit_dict = get_dict(jobs, "pre-commit")
            pre_commit_dict["runs-on"] = "ubuntu-latest"
            steps = get_list(pre_commit_dict, "steps")
            ensure_contains(
                steps, run_action_pre_commit_dict(token_checkout=True, token_uv=True)
            )
        if pyright:
            pyright_dict = get_dict(jobs, "pyright")
            pyright_dict["runs-on"] = "ubuntu-latest"
            steps = get_list(pyright_dict, "steps")
            steps_dict = ensure_contains_partial(
                steps,
                run_action_pyright_dict(
                    python_version=python_version, token_checkout=True, token_uv=True
                ),
            )
            if script is not None:
                with_ = get_dict(steps_dict, "with")
                with_["with-requirements"] = script
        if (
            pytest__os__windows
            or pytest__os__macos
            or pytest__os__ubuntu
            or pytest__python_version__default
            or pytest__python_version__3_12
            or pytest__python_version__3_13
            or pytest__python_version__3_14
            or pytest__resolution__highest
            or pytest__resolution__lowest_direct
        ):
            pytest_dict = get_dict(jobs, "pytest")
            env = get_dict(pytest_dict, "env")
            env["CI"] = "1"
            pytest_dict["name"] = (
                "pytest (${{matrix.os}}, ${{matrix.python-version}}, ${{matrix.resolution}})"
            )
            pytest_dict["runs-on"] = "${{matrix.os}}"
            steps = get_list(pytest_dict, "steps")
            steps_dict = ensure_contains_partial(
                steps, run_action_pytest_dict(token_checkout=True, token_uv=True)
            )
            if script is not None:
                with_ = get_dict(steps_dict, "with")
                with_["with-requirements"] = script
            strategy_dict = get_dict(pytest_dict, "strategy")
            strategy_dict["fail-fast"] = False
            matrix = get_dict(strategy_dict, "matrix")
            os = get_list(matrix, "os")
            if pytest__os__windows:
                ensure_contains(os, "windows-latest")
            if pytest__os__macos:
                ensure_contains(os, "macos-latest")
            if pytest__os__ubuntu:
                ensure_contains(os, "ubuntu-latest")
            python_version_dict = get_list(matrix, "python-version")
            if pytest__python_version__default:
                ensure_contains(python_version_dict, python_version)
            if pytest__python_version__3_12:
                ensure_contains(python_version_dict, "3.12")
            if pytest__python_version__3_13:
                ensure_contains(python_version_dict, "3.13")
            if pytest__python_version__3_14:
                ensure_contains(python_version_dict, "3.14")
            resolution = get_list(matrix, "resolution")
            if pytest__resolution__highest:
                ensure_contains(resolution, "highest")
            if pytest__resolution__lowest_direct:
                ensure_contains(resolution, "lowest-direct")
            if pytest__timeout is not None:
                pytest_dict["timeout-minutes"] = max(round(pytest__timeout / 60), 1)
        if ruff:
            ruff_dict = get_dict(jobs, "ruff")
            ruff_dict["runs-on"] = "ubuntu-latest"
            steps = get_list(ruff_dict, "steps")
            ensure_contains(
                steps, run_action_ruff_dict(token_checkout=True, token_ruff=True)
            )


##


def add_github_push_yaml(
    *,
    modifications: MutableSet[Path] | None = None,
    publish: bool = SETTINGS.github__push__publish,
    publish__trusted_publishing: bool = SETTINGS.github__push__publish__trusted_publishing,
    tag: bool = SETTINGS.github__push__tag,
    tag__major_minor: bool = SETTINGS.github__push__tag__major_minor,
    tag__major: bool = SETTINGS.github__push__tag__major,
    tag__latest: bool = SETTINGS.github__push__tag__latest,
) -> None:
    with yield_yaml_dict(GITHUB_PUSH_YAML, modifications=modifications) as dict_:
        dict_["name"] = "push"
        on = get_dict(dict_, "on")
        push = get_dict(on, "push")
        branches = get_list(push, "branches")
        ensure_contains(branches, "master")
        jobs = get_dict(dict_, "jobs")
        if publish or publish__trusted_publishing:
            publish_dict = get_dict(jobs, "publish")
            environment = get_dict(publish_dict, "environment")
            environment["name"] = "pypi"
            permissions = get_dict(publish_dict, "permissions")
            permissions["id-token"] = "write"
            publish_dict["runs-on"] = "ubuntu-latest"
            steps = get_list(publish_dict, "steps")
            steps_dict = ensure_contains_partial(
                steps, run_action_publish_dict(token_checkout=True, token_uv=True)
            )
            if publish__trusted_publishing:
                with_ = get_dict(steps_dict, "with")
                with_["trusted-publishing"] = True
        if tag or tag__major_minor or tag__major or tag__latest:
            tag_dict = get_dict(jobs, "tag")
            tag_dict["runs-on"] = "ubuntu-latest"
            steps = get_list(tag_dict, "steps")
            steps_dict = ensure_contains_partial(
                steps, run_action_tag_dict(token_checkout=True, token_uv=True)
            )
            if tag__major_minor:
                with_ = get_dict(steps_dict, "with")
                with_["major-minor"] = True
            if tag__major:
                with_ = get_dict(steps_dict, "with")
                with_["major"] = True
            if tag__latest:
                with_ = get_dict(steps_dict, "with")
                with_["latest"] = True


##


def add_pre_commit_config_yaml(
    *,
    modifications: MutableSet[Path] | None = None,
    dockerfmt: bool = SETTINGS.pre_commit__dockerfmt,
    dycw: bool = SETTINGS.pre_commit__dycw,
    prettier: bool = SETTINGS.pre_commit__prettier,
    ruff: bool = SETTINGS.pre_commit__ruff,
    shell: bool = SETTINGS.pre_commit__shell,
    taplo: bool = SETTINGS.pre_commit__taplo,
    uv: bool = SETTINGS.pre_commit__uv,
    script: str | None = SETTINGS.script,
) -> None:
    with yield_yaml_dict(PRE_COMMIT_CONFIG_YAML, modifications=modifications) as dict_:
        _add_pre_commit_config_repo(
            dict_, "https://github.com/dycw/conformalize", "conformalize"
        )
        pre_com_url = "https://github.com/pre-commit/pre-commit-hooks"
        _add_pre_commit_config_repo(
            dict_, pre_com_url, "check-executables-have-shebangs"
        )
        _add_pre_commit_config_repo(dict_, pre_com_url, "check-merge-conflict")
        _add_pre_commit_config_repo(dict_, pre_com_url, "check-symlinks")
        _add_pre_commit_config_repo(dict_, pre_com_url, "destroyed-symlinks")
        _add_pre_commit_config_repo(dict_, pre_com_url, "detect-private-key")
        _add_pre_commit_config_repo(dict_, pre_com_url, "end-of-file-fixer")
        _add_pre_commit_config_repo(
            dict_, pre_com_url, "mixed-line-ending", args=("add", ["--fix=lf"])
        )
        _add_pre_commit_config_repo(dict_, pre_com_url, "no-commit-to-branch")
        _add_pre_commit_config_repo(
            dict_, pre_com_url, "pretty-format-json", args=("add", ["--autofix"])
        )
        _add_pre_commit_config_repo(dict_, pre_com_url, "no-commit-to-branch")
        _add_pre_commit_config_repo(dict_, pre_com_url, "trailing-whitespace")
        if dockerfmt:
            _add_pre_commit_config_repo(
                dict_,
                "https://github.com/reteps/dockerfmt",
                "dockerfmt",
                args=("add", ["--newline", "--write"]),
            )
        if dycw:
            dycw_url = "https://github.com/dycw/actions"
            _add_pre_commit_config_repo(dict_, dycw_url, "format-requirements")
            _add_pre_commit_config_repo(dict_, dycw_url, "replace-sequence-strs")
        if prettier:
            _add_pre_commit_config_repo(
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
            _add_pre_commit_config_repo(
                dict_, ruff_url, "ruff-check", args=("add", ["--fix"])
            )
            _add_pre_commit_config_repo(dict_, ruff_url, "ruff-format")
        if shell:
            _add_pre_commit_config_repo(
                dict_, "https://github.com/scop/pre-commit-shfmt", "shfmt"
            )
            _add_pre_commit_config_repo(
                dict_, "https://github.com/koalaman/shellcheck-precommit", "shellcheck"
            )
        if taplo:
            _add_pre_commit_config_repo(
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
            _add_pre_commit_config_repo(
                dict_,
                "https://github.com/astral-sh/uv-pre-commit",
                "uv-lock",
                files=None if script is None else rf"^{escape(script)}$",
                args=(
                    "add",
                    ["--upgrade", "--resolution", "highest", "--prerelease", "disallow"]
                    + ([] if script is None else [f"--script={script}"]),
                ),
            )


def _add_pre_commit_config_repo(
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
    repos_list = get_list(pre_commit_dict, "repos")
    repo_dict = ensure_contains_partial(
        repos_list, {"repo": url}, extra={} if url == "local" else {"rev": "master"}
    )
    hooks_list = get_list(repo_dict, "hooks")
    hook_dict = ensure_contains_partial(hooks_list, {"id": id_})
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
                hook_args = get_list(hook_dict, "args")
                ensure_contains(hook_args, *args_i)
            case "exact", list() as args_i:
                hook_dict["args"] = args_i
            case never:
                assert_never(never)


##


def add_pyproject_toml(
    *,
    modifications: MutableSet[Path] | None = None,
    version: str = SETTINGS.python_version,
    description: str | None = SETTINGS.description,
    package_name: str | None = SETTINGS.package_name,
    readme: bool = SETTINGS.readme,
    optional_dependencies__scripts: bool = SETTINGS.pyproject__project__optional_dependencies__scripts,
    python_package_name: str | None = SETTINGS.python_package_name,
    python_package_name_use: str | None = SETTINGS.python_package_name_use,
    tool__uv__indexes: list[tuple[str, str]] = SETTINGS.pyproject__tool__uv__indexes,
) -> None:
    with yield_toml_doc(PYPROJECT_TOML, modifications=modifications) as doc:
        build_system = get_table(doc, "build-system")
        build_system["build-backend"] = "uv_build"
        build_system["requires"] = ["uv_build"]
        project = get_table(doc, "project")
        project["requires-python"] = f">= {version}"
        if description is not None:
            project["description"] = description
        if package_name is not None:
            project["name"] = package_name
        if readme:
            project["readme"] = "README.md"
        project.setdefault("version", "0.1.0")
        dependency_groups = get_table(doc, "dependency-groups")
        dev = get_array(dependency_groups, "dev")
        ensure_contains(dev, "dycw-utilities[test]")
        ensure_contains(dev, "rich")
        if optional_dependencies__scripts:
            optional_dependencies = get_table(project, "optional-dependencies")
            scripts = get_array(optional_dependencies, "scripts")
            ensure_contains(scripts, "click >=8.3.1")
        if python_package_name is not None:
            tool = get_table(doc, "tool")
            uv = get_table(tool, "uv")
            build_backend = get_table(uv, "build-backend")
            build_backend["module-name"] = python_package_name_use
            build_backend["module-root"] = "src"
        if len(tool__uv__indexes) >= 1:
            tool = get_table(doc, "tool")
            uv = get_table(tool, "uv")
            indexes = get_aot(uv, "index")
            for name, url in tool__uv__indexes:
                index = table()
                index["explicit"] = True
                index["name"] = name
                index["url"] = url
                ensure_aot_contains(indexes, index)


##


def add_pyrightconfig_json(
    *,
    modifications: MutableSet[Path] | None = None,
    version: str = SETTINGS.python_version,
    script: str | None = SETTINGS.script,
) -> None:
    with yield_json_dict(PYRIGHTCONFIG_JSON, modifications=modifications) as dict_:
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


##


def add_pytest_toml(
    *,
    modifications: MutableSet[Path] | None = None,
    asyncio: bool = SETTINGS.pytest__asyncio,
    ignore_warnings: bool = SETTINGS.pytest__ignore_warnings,
    timeout: int | None = SETTINGS.pytest__timeout,
    coverage: bool = SETTINGS.coverage,
    python_package_name: str | None = SETTINGS.python_package_name_use,
    script: str | None = SETTINGS.script,
) -> None:
    with yield_toml_doc(PYTEST_TOML, modifications=modifications) as doc:
        pytest = get_table(doc, "pytest")
        addopts = get_array(pytest, "addopts")
        ensure_contains(
            addopts,
            "-ra",
            "-vv",
            "--color=auto",
            "--durations=10",
            "--durations-min=10",
        )
        if coverage and (python_package_name is not None):
            ensure_contains(
                addopts,
                f"--cov={python_package_name}",
                f"--cov-config={COVERAGERC_TOML}",
                "--cov-report=html",
            )
        pytest["collect_imported_tests"] = False
        pytest["empty_parameter_set_mark"] = "fail_at_collect"
        filterwarnings = get_array(pytest, "filterwarnings")
        ensure_contains(filterwarnings, "error")
        pytest["minversion"] = "9.0"
        pytest["strict"] = True
        testpaths = get_array(pytest, "testpaths")
        ensure_contains(testpaths, "src/tests" if script is None else "tests")
        pytest["xfail_strict"] = True
        if asyncio:
            pytest["asyncio_default_fixture_loop_scope"] = "function"
            pytest["asyncio_mode"] = "auto"
        if ignore_warnings:
            filterwarnings = get_array(pytest, "filterwarnings")
            ensure_contains(
                filterwarnings,
                "ignore::DeprecationWarning",
                "ignore::ResourceWarning",
                "ignore::RuntimeWarning",
            )
        if timeout is not None:
            pytest["timeout"] = str(timeout)


##


def add_readme_md(
    *,
    modifications: MutableSet[Path] | None = None,
    name: str | None = SETTINGS.package_name,
    description: str | None = SETTINGS.description,
) -> None:
    with yield_text_file(README_MD, modifications=modifications) as temp:
        lines: list[str] = []
        if name is not None:
            lines.append(f"# `{name}`")
        if description is not None:
            lines.append(description)
        _ = temp.write_text("\n\n".join(lines))


##


def add_ruff_toml(
    *,
    modifications: MutableSet[Path] | None = None,
    version: str = SETTINGS.python_version,
) -> None:
    with yield_toml_doc(RUFF_TOML, modifications=modifications) as doc:
        doc["target-version"] = f"py{version.replace('.', '')}"
        doc["unsafe-fixes"] = True
        fmt = get_table(doc, "format")
        fmt["preview"] = True
        fmt["skip-magic-trailing-comma"] = True
        lint = get_table(doc, "lint")
        lint["explicit-preview-rules"] = True
        fixable = get_array(lint, "fixable")
        ensure_contains(fixable, "ALL")
        ignore = get_array(lint, "ignore")
        ensure_contains(
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
        select = get_array(lint, "select")
        selected_rules = [
            "RUF022",  # unsorted-dunder-all
            "RUF029",  # unused-async
        ]
        ensure_contains(select, "ALL", *selected_rules)
        extend_per_file_ignores = get_table(lint, "extend-per-file-ignores")
        test_py = get_array(extend_per_file_ignores, "test_*.py")
        test_py_rules = [
            "S101",  # assert
            "SLF001",  # private-member-access
        ]
        ensure_contains(test_py, *test_py_rules)
        ensure_not_contains(ignore, *selected_rules, *test_py_rules)
        bugbear = get_table(lint, "flake8-bugbear")
        extend_immutable_calls = get_array(bugbear, "extend-immutable-calls")
        ensure_contains(extend_immutable_calls, "typing.cast")
        tidy_imports = get_table(lint, "flake8-tidy-imports")
        tidy_imports["ban-relative-imports"] = "all"
        isort = get_table(lint, "isort")
        req_imps = get_array(isort, "required-imports")
        ensure_contains(req_imps, "from __future__ import annotations")
        isort["split-on-trailing-comma"] = False


##


def add_token_to_with_dict(
    dict_: StrDict, key: str, /, *, token: bool | str = False
) -> None:
    match token:
        case True:
            dict_[key] = "${{secrets.GITHUB_TOKEN}}"
        case False:
            ...
        case str():
            dict_[key] = token
        case never:
            assert_never(never)


##


def check_versions() -> None:
    version = get_version_from_bumpversion_toml()
    try:
        set_version(version)
    except CalledProcessError:
        msg = f"Inconsistent versions; should be {version}"
        raise ValueError(msg) from None


##


def ensure_aot_contains(array: AoT, /, *tables: Table) -> None:
    for table_ in tables:
        if table_ not in array:
            array.append(table_)


def ensure_contains(array: HasAppend, /, *objs: Any) -> None:
    if isinstance(array, AoT):
        msg = f"Use {ensure_aot_contains.__name__!r} instead of {ensure_contains.__name__!r}"
        raise TypeError(msg)
    for obj in objs:
        if obj not in array:
            array.append(obj)


def ensure_contains_partial(
    container: HasAppend, partial: StrDict, /, *, extra: StrDict | None = None
) -> StrDict:
    try:
        return get_partial_dict(container, partial, skip_log=True)
    except OneEmptyError:
        dict_ = partial | ({} if extra is None else extra)
        container.append(dict_)
        return dict_


def ensure_not_contains(array: Array, /, *objs: Any) -> None:
    for obj in objs:
        try:
            index = next(i for i, o in enumerate(array) if o == obj)
        except StopIteration:
            pass
        else:
            del array[index]


##


def get_aot(container: HasSetDefault, key: str, /) -> AoT:
    return ensure_class(container.setdefault(key, aot()), AoT)


def get_array(container: HasSetDefault, key: str, /) -> Array:
    return ensure_class(container.setdefault(key, array()), Array)


def get_dict(container: HasSetDefault, key: str, /) -> StrDict:
    return ensure_class(container.setdefault(key, {}), dict)


def get_list(container: HasSetDefault, key: str, /) -> list[Any]:
    return ensure_class(container.setdefault(key, []), list)


def get_table(container: HasSetDefault, key: str, /) -> Table:
    return ensure_class(container.setdefault(key, table()), Table)


##


def get_partial_dict(
    iterable: Iterable[Any], dict_: StrDict, /, *, skip_log: bool = False
) -> StrDict:
    try:
        return one(i for i in iterable if is_partial_dict(dict_, i))
    except OneEmptyError:
        if not skip_log:
            LOGGER.exception(
                "Expected %s to contain %s (as a partial)",
                pretty_repr(iterable),
                pretty_repr(dict_),
            )
        raise
    except OneNonUniqueError as error:
        LOGGER.exception(
            "Expected %s to contain %s uniquely (as a partial); got %s, %s and perhaps more",
            pretty_repr(iterable),
            pretty_repr(dict_),
            pretty_repr(error.first),
            pretty_repr(error.second),
        )
        raise


def is_partial_dict(obj: Any, dict_: StrDict, /) -> bool:
    if not isinstance(obj, dict):
        return False
    results: dict[str, bool] = {}
    for key, obj_value in obj.items():
        try:
            dict_value = dict_[key]
        except KeyError:
            results[key] = False
        else:
            if isinstance(obj_value, dict) and isinstance(dict_value, dict):
                results[key] = is_partial_dict(obj_value, dict_value)
            else:
                results[key] = obj_value == dict_value
    return all(results.values())


##


def get_version_from_bumpversion_toml(
    *, obj: TOMLDocument | str | None = None
) -> Version:
    match obj:
        case TOMLDocument() as doc:
            tool = get_table(doc, "tool")
            bumpversion = get_table(tool, "bumpversion")
            return parse_version(str(bumpversion["current_version"]))
        case str() as text:
            return get_version_from_bumpversion_toml(obj=tomlkit.parse(text))
        case None:
            with yield_bumpversion_toml() as doc:
                return get_version_from_bumpversion_toml(obj=doc)
        case never:
            assert_never(never)


def get_version_from_git_show() -> Version:
    text = run("git", "show", f"origin/master:{BUMPVERSION_TOML}", return_=True)
    return get_version_from_bumpversion_toml(obj=text.rstrip("\n"))


def get_version_from_git_tag() -> Version:
    text = run("git", "tag", "--points-at", "origin/master", return_=True)
    for line in text.splitlines():
        with suppress(ParseVersionError):
            return parse_version(line)
    msg = "No valid version from 'git tag'"
    raise ValueError(msg)


##


def run_action_pre_commit_dict(
    *, token_checkout: bool | str = False, token_uv: bool | str = False
) -> StrDict:
    with_: StrDict = {
        "repos": LiteralScalarString(
            strip_and_dedent("""
                dycw/conformalize
                pre-commit/pre-commit-hooks
            """)
        )
    }
    add_token_to_with_dict(with_, "token-checkout", token=token_checkout)
    add_token_to_with_dict(with_, "token-uv", token=token_uv)
    return {
        "name": "Run 'pre-commit'",
        "uses": "dycw/action-pre-commit@latest",
        "with": with_,
    }


def run_action_publish_dict(
    *,
    token_checkout: bool | str = False,
    token_uv: bool | str = False,
    username: str | None = None,
    password: str | None = None,
    publish_url: str | None = None,
    trusted_publishing: bool = False,
    native_tls: bool = False,
) -> StrDict:
    out: StrDict = {
        "name": "Build and publish package",
        "uses": "dycw/action-publish@latest",
    }
    with_: StrDict = {}
    add_token_to_with_dict(with_, "token-checkout", token=token_checkout)
    add_token_to_with_dict(with_, "token-uv", token=token_uv)
    if username is not None:
        with_["username"] = username
    if password is not None:
        with_["password"] = password
    if publish_url is not None:
        with_["publish-url"] = publish_url
    if trusted_publishing:
        with_["trusted-publishing"] = True
    if native_tls:
        with_["native-tls"] = True
    if len(with_) >= 1:
        out["with"] = with_
    return out


def run_action_pyright_dict(
    *,
    python_version: str = SETTINGS.python_version,
    token_checkout: bool | str = False,
    token_uv: bool | str = False,
) -> StrDict:
    with_: StrDict = {"python-version": python_version}
    if token_checkout:
        add_token_to_with_dict(with_, "token-checkout", token=token_checkout)
        add_token_to_with_dict(with_, "token-uv", token=token_uv)
    return {
        "name": "Run 'pyright'",
        "uses": "dycw/action-pyright@latest",
        "with": with_,
    }


def run_action_pytest_dict(
    *, token_checkout: bool | str = False, token_uv: bool | str = False
) -> StrDict:
    with_: StrDict = {
        "python-version": "${{matrix.python-version}}",
        "resolution": "${{matrix.resolution}}",
    }
    add_token_to_with_dict(with_, "token-checkout", token=token_checkout)
    add_token_to_with_dict(with_, "token-uv", token=token_uv)
    return {"name": "Run 'pytest'", "uses": "dycw/action-pytest@latest", "with": with_}


def run_action_ruff_dict(
    *, token_checkout: bool | str = False, token_ruff: bool | str = False
) -> StrDict:
    out: StrDict = {"name": "Run 'ruff'", "uses": "dycw/action-ruff@latest"}
    with_: StrDict = {}
    add_token_to_with_dict(with_, "token-checkout", token=token_checkout)
    add_token_to_with_dict(with_, "token-ruff", token=token_ruff)
    if len(with_) >= 1:
        out["with"] = with_
    return out


def run_action_tag_dict(
    *, token_checkout: bool | str = False, token_uv: bool | str = False
) -> StrDict:
    out: StrDict = {"name": "Tag latest commit", "uses": "dycw/action-tag@latest"}
    with_: StrDict = {}
    add_token_to_with_dict(with_, "token-checkout", token=token_checkout)
    add_token_to_with_dict(with_, "token-uv", token=token_uv)
    if len(with_) >= 1:
        out["with"] = with_
    return out


##


def run_bump_my_version(*, modifications: MutableSet[Path] | None = None) -> None:
    def run_set_version(version: Version, /) -> None:
        LOGGER.info("Setting version to %s...", version)
        set_version(version)
        if modifications is not None:
            modifications.add(BUMPVERSION_TOML)

    try:
        prev = get_version_from_git_tag()
    except (CalledProcessError, ValueError):
        try:
            prev = get_version_from_git_show()
        except (CalledProcessError, ParseVersionError, NonExistentKey):
            run_set_version(Version(0, 1, 0))
            return
    current = get_version_from_bumpversion_toml()
    patched = prev.bump_patch()
    if current not in {patched, prev.bump_minor(), prev.bump_major()}:
        run_set_version(patched)


##


def run_pre_commit_update(*, modifications: MutableSet[Path] | None = None) -> None:
    cache = xdg_cache_home() / "conformalize" / get_repo_root().name

    def run_autoupdate() -> None:
        current = PRE_COMMIT_CONFIG_YAML.read_text()
        run("pre-commit", "autoupdate", print=True)
        with writer(cache, overwrite=True) as temp:
            _ = temp.write_text(get_now().format_iso())
        if (modifications is not None) and (
            PRE_COMMIT_CONFIG_YAML.read_text() != current
        ):
            modifications.add(PRE_COMMIT_CONFIG_YAML)

    try:
        text = cache.read_text()
    except FileNotFoundError:
        run_autoupdate()
    else:
        prev = ZonedDateTime.parse_iso(text.rstrip("\n"))
        if prev < (get_now() - 12 * HOUR):
            run_autoupdate()


##


def run_ripgrep_and_replace(
    *,
    version: str = SETTINGS.python_version,
    modifications: MutableSet[Path] | None = None,
) -> None:
    result = ripgrep(
        "--files-with-matches",
        "--pcre2",
        "--type=py",
        rf'# requires-python = ">=(?!{version})\d+\.\d+"',
    )
    if result is None:
        return
    for path in map(Path, result.splitlines()):
        with yield_text_file(path, modifications=modifications) as temp:
            text = sub(
                r'# requires-python = ">=\d+\.\d+"',
                rf'# requires-python = ">={version}"',
                path.read_text(),
                flags=MULTILINE,
            )
            _ = temp.write_text(text)


##


def set_version(version: Version, /) -> None:
    run(
        "bump-my-version",
        "replace",
        "--new-version",
        str(version),
        str(BUMPVERSION_TOML),
    )


##


def update_action_file_extensions(
    *, modifications: MutableSet[Path] | None = None
) -> None:
    try:
        paths = list(Path(".github").rglob("**/*.yml"))
    except FileNotFoundError:
        return
    for path in paths:
        new = path.with_suffix(".yaml")
        LOGGER.info("Renaming '%s' -> '%s'...", path, new)
        _ = path.rename(new)
        if modifications is not None:
            modifications.add(path)


##


def update_action_versions(*, modifications: MutableSet[Path] | None = None) -> None:
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
        with yield_yaml_dict(path, modifications=modifications) as dict_:
            dict_.clear()
            dict_.update(YAML_INSTANCE.load(text))


##


def write_text(
    verb: str,
    src: PathLike,
    dest: PathLike,
    /,
    *,
    modifications: MutableSet[Path] | None = None,
) -> None:
    src, dest = map(Path, [src, dest])
    LOGGER.info("%s '%s'...", verb, dest)
    text = src.read_text().rstrip("\n") + "\n"
    with writer(dest, overwrite=True) as temp:
        _ = temp.write_text(text)
    if modifications is not None:
        modifications.add(dest)


##


def yaml_dump(obj: Any, /) -> str:
    stream = StringIO()
    YAML_INSTANCE.dump(obj, stream)
    return stream.getvalue()


##


@contextmanager
def yield_bumpversion_toml(
    *, modifications: MutableSet[Path] | None = None
) -> Iterator[TOMLDocument]:
    with yield_toml_doc(BUMPVERSION_TOML, modifications=modifications) as doc:
        tool = get_table(doc, "tool")
        bumpversion = get_table(tool, "bumpversion")
        bumpversion["allow_dirty"] = True
        bumpversion.setdefault("current_version", str(Version(0, 1, 0)))
        yield doc


##


@contextmanager
def yield_json_dict(
    path: PathLike, /, *, modifications: MutableSet[Path] | None = None
) -> Iterator[StrDict]:
    with yield_write_context(
        path, json.loads, dict, json.dumps, modifications=modifications
    ) as dict_:
        yield dict_


##


@contextmanager
def yield_text_file(
    path: PathLike, /, *, modifications: MutableSet[Path] | None = None
) -> Iterator[Path]:
    path = Path(path)
    try:
        current = path.read_text()
    except FileNotFoundError:
        with TemporaryFile() as temp:
            yield temp
            write_text("Writing", temp, path, modifications=modifications)
    else:
        with TemporaryFile(text=current) as temp:
            yield temp
            if temp.read_text().rstrip("\n") != current.rstrip("\n"):
                write_text("Writing", temp, path, modifications=modifications)


##


@contextmanager
def yield_toml_doc(
    path: PathLike, /, *, modifications: MutableSet[Path] | None = None
) -> Iterator[TOMLDocument]:
    with yield_write_context(
        path, tomlkit.parse, document, tomlkit.dumps, modifications=modifications
    ) as doc:
        yield doc


##


@contextmanager
def yield_write_context[T](
    path: PathLike,
    loads: Callable[[str], T],
    get_default: Callable[[], T],
    dumps: Callable[[T], str],
    /,
    *,
    modifications: MutableSet[Path] | None = None,
) -> Iterator[T]:
    path = Path(path)

    def run_write(verb: str, data: T, /) -> None:
        with writer(path, overwrite=True) as temp:
            _ = temp.write_text(dumps(data))
            write_text(verb, temp, path, modifications=modifications)

    try:
        current = path.read_text()
    except FileNotFoundError:
        yield (default := get_default())
        run_write("Writing", default)
    else:
        data = loads(current)
        yield data
        is_equal = data == loads(current)  # tomlkit cannot handle !=
        if not is_equal:
            run_write("Modifying", data)


##


@contextmanager
def yield_yaml_dict(
    path: PathLike, /, *, modifications: MutableSet[Path] | None = None
) -> Iterator[StrDict]:
    with yield_write_context(
        path, YAML_INSTANCE.load, dict, yaml_dump, modifications=modifications
    ) as dict_:
        yield dict_


__all__ = [
    "add_bumpversion_toml",
    "add_coveragerc_toml",
    "add_envrc",
    "add_github_pull_request_yaml",
    "add_github_push_yaml",
    "add_pre_commit_config_yaml",
    "add_pyproject_toml",
    "add_pyrightconfig_json",
    "add_pytest_toml",
    "add_readme_md",
    "add_ruff_toml",
    "add_token_to_with_dict",
    "check_versions",
    "ensure_aot_contains",
    "ensure_contains",
    "ensure_contains_partial",
    "ensure_not_contains",
    "get_aot",
    "get_array",
    "get_dict",
    "get_list",
    "get_partial_dict",
    "get_table",
    "get_version_from_bumpversion_toml",
    "get_version_from_git_show",
    "get_version_from_git_tag",
    "is_partial_dict",
    "run_action_pre_commit_dict",
    "run_action_publish_dict",
    "run_action_pyright_dict",
    "run_action_pytest_dict",
    "run_action_ruff_dict",
    "run_action_tag_dict",
    "run_bump_my_version",
    "run_pre_commit_update",
    "run_ripgrep_and_replace",
    "set_version",
    "update_action_file_extensions",
    "update_action_versions",
    "write_text",
    "yaml_dump",
    "yield_bumpversion_toml",
    "yield_json_dict",
    "yield_text_file",
    "yield_toml_doc",
    "yield_write_context",
    "yield_yaml_dict",
]
