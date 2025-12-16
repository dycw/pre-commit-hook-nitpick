#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#   "click",
#   "dycw-utilities",
#   "pytest-xdist",
#   "pyyaml",
#   "tomlkit",
#   "typed-settings[attrs, click]",
#   "xdg-base-dirs",
# ]
# ///
from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from logging import getLogger
from pathlib import Path
from re import escape, search
from subprocess import CalledProcessError, check_call, check_output
from typing import TYPE_CHECKING, Any, Literal, assert_never

import tomlkit
import yaml
from click import command
from tomlkit import TOMLDocument, aot, array, document, table
from tomlkit.exceptions import NonExistentKey
from tomlkit.items import AoT, Array, Table
from typed_settings import click_options, option, settings
from utilities.atomicwrites import writer
from utilities.click import CONTEXT_SETTINGS_HELP_OPTION_NAMES
from utilities.functions import ensure_class
from utilities.iterables import OneEmptyError, one
from utilities.logging import basic_config
from utilities.pathlib import get_repo_root
from utilities.version import Version, VersionLike, parse_version
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
_LOGGER = getLogger(__name__)
_MODIFIED = ContextVar("modified", default=False)


@settings
class Settings:
    code_version: str = option(default="0.1.0", help="Code version")
    github__push_tag: bool = option(default=False, help="Set up 'push--tag.yaml'")
    github__push_tag__major_minor: bool = option(
        default=False, help="Set up 'push--tag.yaml' with the 'major.minor' tag"
    )
    github__push_tag__major: bool = option(
        default=False, help="Set up 'push--tag.yaml' with the the 'major' tag"
    )
    github__push_tag__latest: bool = option(
        default=False, help="Set up 'push--tag.yaml' with the 'latest' tag"
    )
    python_version: str = option(default="3.14", help="Python version")
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
    pyproject__tool__uv__indexes: list[tuple[str, str]] = option(
        factory=list, help="Set up 'pyproject.toml' [[uv.tool.index]]"
    )
    pyright: bool = option(default=False, help="Set up 'pyrightconfig.json'")
    pyright_include: list[str] = option(
        factory=list, help="Set up 'pyrightconfig.json' [include]"
    )
    pytest: bool = option(default=False, help="Set up 'pytest.toml'")
    pytest_asyncio: bool = option(default=False, help="Set up 'pytest.toml' asyncio_*")
    pytest_ignore_warnings: bool = option(
        default=False, help="Set up 'pytest.toml' filterwarnings"
    )
    pytest_test_paths: list[str] = option(
        factory=list, help="Set up 'pytest.toml' testpaths"
    )
    pytest_timeout: int | None = option(
        default=None, help="Set up 'pytest.toml' timeout"
    )
    ruff: bool = option(default=False, help="Set up 'ruff.toml'")
    dry_run: bool = option(default=False, help="Dry run the CLI")


_SETTINGS = Settings()


@command(**CONTEXT_SETTINGS_HELP_OPTION_NAMES)
@click_options(Settings, "app", show_envvars_in_help=True)
def main(settings: Settings, /) -> None:
    if settings.dry_run:
        _LOGGER.info("Dry run; exiting...")
        return
    _LOGGER.info("Running...")
    _run_bump_my_version(version=settings.code_version)
    _run_pre_commit_update()
    _add_pre_commit()
    if settings.github__push_tag:
        _add_github_push_tag()
    if settings.github__push_tag__major_minor:
        _add_github_push_tag_extra("major-minor")
    if settings.github__push_tag__major:
        _add_github_push_tag_extra("major")
    if settings.github__push_tag__latest:
        _add_github_push_tag_extra("latest")
    if settings.pre_commit__dockerfmt:
        _add_pre_commit_dockerfmt()
    if settings.pre_commit__prettier:
        _add_pre_commit_prettier()
    if settings.pre_commit__ruff:
        _add_pre_commit_ruff()
    if settings.pre_commit__shell:
        _add_pre_commit_shell()
    if settings.pre_commit__taplo:
        _add_pre_commit_taplo()
    if settings.pre_commit__uv:
        _add_pre_commit_uv(script=settings.pre_commit__uv__script)
    if settings.pyproject:
        _add_pyproject(version=settings.python_version)
    if settings.pyproject__dependency_groups__dev:
        _add_pyproject_dependency_groups_dev(version=settings.python_version)
    if (name := settings.pyproject__project__name) is not None:
        _add_pyproject_project_name(name, version=settings.python_version)
    if settings.pyproject__project__optional_dependencies__scripts:
        _add_pyproject_project_optional_dependencies_scripts(
            version=settings.python_version
        )
    if len(indexes := settings.pyproject__tool__uv__indexes) >= 1:
        for name, url in indexes:
            _add_pyproject_uv_index(name, url, version=settings.python_version)
    if settings.pyright:
        _add_pyrightconfig(version=settings.python_version)
    if len(include := settings.pyright_include) >= 1:
        _add_pyrightconfig_include(*include, version=settings.python_version)
    if settings.pytest:
        _add_pytest()
    if settings.pytest_asyncio:
        _add_pytest_asyncio()
    if settings.pytest_ignore_warnings:
        _add_pytest_ignore_warnings()
    if len(test_paths := settings.pytest_test_paths) >= 1:
        _add_pytest_test_paths(*test_paths)
    if (timeout := settings.pytest_timeout) is not None:
        _add_pytest_timeout(timeout)
    if settings.ruff:
        _add_ruff(version=settings.python_version)
    if _MODIFIED.get():
        sys.exit(1)


def _add_github_push_tag() -> None:
    with _yield_github_push_tag():
        ...


def _add_github_push_tag_extra(key: str, /) -> None:
    with _yield_github_push_tag() as push_tag_dict:
        jobs = _get_dict(push_tag_dict, "jobs")
        tag = _get_dict(jobs, "tag")
        steps = _get_list(tag, "steps")
        step_dict = _get_partial_dict(steps, {"name": "Tag latest commit"})
        with_ = _get_dict(step_dict, "with")
        with_[key] = True


def _add_pre_commit() -> None:
    url = "https://github.com/pre-commit/pre-commit-hooks"
    with _yield_pre_commit() as dict_:
        _ensure_pre_commit_repo(
            dict_, "https://github.com/dycw/pre-commit-hook-nitpick", "nitpick"
        )
        _ensure_pre_commit_repo(dict_, url, "check-executables-have-shebangs")
        _ensure_pre_commit_repo(dict_, url, "check-merge-conflict")
        _ensure_pre_commit_repo(dict_, url, "check-symlinks")
        _ensure_pre_commit_repo(dict_, url, "destroyed-symlinks")
        _ensure_pre_commit_repo(dict_, url, "detect-private-key")
        _ensure_pre_commit_repo(dict_, url, "end-of-file-fixer")
        _ensure_pre_commit_repo(
            dict_, url, "mixed-line-ending", args=("add", ["--fix=lf"])
        )
        _ensure_pre_commit_repo(dict_, url, "no-commit-to-branch")
        _ensure_pre_commit_repo(
            dict_, url, "pretty-format-json", args=("add", ["--autofix"])
        )
        _ensure_pre_commit_repo(dict_, url, "no-commit-to-branch")
        _ensure_pre_commit_repo(dict_, url, "trailing-whitespace")


def _add_pre_commit_dockerfmt() -> None:
    with _yield_pre_commit(desc="dockerfmt") as dict_:
        _ensure_pre_commit_repo(
            dict_,
            "https://github.com/reteps/dockerfmt",
            "dockerfmt",
            args=("add", ["--newline", "--write"]),
        )


def _add_pre_commit_prettier() -> None:
    with _yield_pre_commit(desc="prettier") as dict_:
        _ensure_pre_commit_repo(
            dict_,
            "local",
            "prettier",
            name="prettier",
            entry="npx prettier --write",
            language="system",
            types_or=["markdown", "yaml"],
        )


def _add_pre_commit_ruff() -> None:
    url = "https://github.com/astral-sh/ruff-pre-commit"
    with _yield_pre_commit(desc="ruff") as dict_:
        _ensure_pre_commit_repo(dict_, url, "ruff-check", args=("add", ["--fix"]))
        _ensure_pre_commit_repo(dict_, url, "ruff-format")


def _add_pre_commit_shell() -> None:
    with _yield_pre_commit(desc="shell") as dict_:
        _ensure_pre_commit_repo(
            dict_, "https://github.com/scop/pre-commit-shfmt", "shfmt"
        )
        _ensure_pre_commit_repo(
            dict_, "https://github.com/koalaman/shellcheck-precommit", "shellcheck"
        )


def _add_pre_commit_taplo() -> None:
    with _yield_pre_commit(desc="taplo") as dict_:
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


def _add_pre_commit_uv(*, script: str | None = None) -> None:
    with _yield_pre_commit(desc="uv") as dict_:
        _ensure_pre_commit_repo(
            dict_,
            "https://github.com/astral-sh/uv-pre-commit",
            "uv-lock",
            files=None if script is None else rf"^{escape(script)}$",
            args=("add", ["--upgrade"] if script is None else [f"--script={script}"]),
        )


def _add_pyproject(*, version: str = _SETTINGS.python_version) -> None:
    with _yield_pyproject(version=version):
        ...


def _add_pyrightconfig(*, version: str = _SETTINGS.python_version) -> None:
    with _yield_pyrightconfig(version=version):
        ...


def _add_pyrightconfig_include(
    *paths: str, version: str = _SETTINGS.python_version
) -> None:
    with _yield_pyrightconfig(version=version) as dict_:
        include = _get_list(dict_, "include")
        _ensure_contains(include, *paths)


def _add_pytest() -> None:
    with _yield_pytest():
        ...


def _add_pytest_asyncio() -> None:
    with _yield_pytest(desc="filterwarnings") as doc:
        pytest = _get_table(doc, "pytest")
        pytest["asyncio_default_fixture_loop_scope"] = "function"
        pytest["asyncio_mode"] = "auto"


def _add_pytest_ignore_warnings() -> None:
    with _yield_pytest(desc="asyncio_*") as doc:
        pytest = _get_table(doc, "pytest")
        filterwarnings = _get_array(pytest, "filterwarnings")
        _ensure_contains(
            filterwarnings,
            "ignore::DeprecationWarning",
            "ignore::ResourceWarning",
            "ignore::RuntimeWarning",
        )


def _add_pytest_test_paths(*paths: str) -> None:
    with _yield_pytest(desc="testpaths") as doc:
        pytest = _get_table(doc, "pytest")
        testpaths = _get_array(pytest, "testpaths")
        _ensure_contains(testpaths, *paths)


def _add_pytest_timeout(timeout: int, /) -> None:
    with _yield_pytest(desc="timeout") as doc:
        pytest = _get_table(doc, "pytest")
        pytest["timeout"] = str(timeout)


def _add_ruff(*, version: str = _SETTINGS.python_version) -> None:
    with _yield_ruff(version=version):
        ...


def _add_pyproject_dependency_groups_dev(
    *, version: str = _SETTINGS.python_version
) -> None:
    with _yield_pyproject(desc="[dependency-groups.dev]", version=version) as doc:
        dep_grps = _get_table(doc, "dependency-groups")
        dev = _get_array(dep_grps, "dev")
        _ensure_contains(dev, "dycw-utilities[test]")
        _ensure_contains(dev, "rich")


def _add_pyproject_project_name(
    name: str, /, *, version: str = _SETTINGS.python_version
) -> None:
    with _yield_pyproject(desc="project.name", version=version) as doc:
        proj = _get_table(doc, "project")
        proj["name"] = name


def _add_pyproject_project_optional_dependencies_scripts(
    *, version: str = _SETTINGS.python_version
) -> None:
    with _yield_pyproject(
        desc="[project.optional-dependencies.scripts]", version=version
    ) as doc:
        proj = _get_table(doc, "project")
        opt_deps = _get_table(proj, "optional-dependencies")
        scripts = _get_array(opt_deps, "scripts")
        _ensure_contains(scripts, "click >=8.3.1")


def _add_pyproject_uv_index(
    name: str, url: str, /, *, version: str = _SETTINGS.python_version
) -> None:
    with _yield_pyproject(desc="[tool.uv.index]", version=version) as doc:
        tool = _get_table(doc, "tool")
        uv = _get_table(tool, "uv")
        indexes = _get_aot(uv, "index")
        index = table()
        index["explicit"] = True
        index["name"] = name
        index["url"] = url
        _ensure_aot_contains(indexes, index)


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
    array: HasAppend, partial: StrDict, /, *, extra: StrDict | None = None
) -> StrDict:
    try:
        return _get_partial_dict(array, partial)
    except OneEmptyError:
        dict_ = partial | ({} if extra is None else extra)
        array.append(dict_)
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


def _get_list(containe: HasSetDefault, key: str, /) -> list[Any]:
    return ensure_class(containe.setdefault(key, []), list)


def _get_partial_dict(container: Iterable[Any], dict_: StrDict, /) -> StrDict:
    return one(
        d
        for d in container
        if isinstance(d, dict)
        and set(dict_).issubset(d)
        and all(d[k] == v for k, v in dict_.items())
    )


def _get_table(container: HasSetDefault, key: str, /) -> Table:
    return ensure_class(container.setdefault(key, table()), Table)


def _get_version(obj: TOMLDocument | str, /) -> Version:
    match obj:
        case TOMLDocument() as doc:
            tool = _get_table(doc, "tool")
            bumpversion = _get_table(tool, "bumpversion")
            return parse_version(str(bumpversion["current_version"]))
        case str() as text:
            return _get_version(tomlkit.parse(text))
        case never:
            assert_never(never)


def _run_bump_my_version(*, version: VersionLike = _SETTINGS.code_version) -> None:
    if search("template", str(get_repo_root())):
        return

    def run(doc: TOMLDocument, version: Version, /) -> None:
        tool = _get_table(doc, "tool")
        bumpversion = _get_table(tool, "bumpversion")
        bumpversion["current_version"] = str(version)
        _ = _MODIFIED.set(True)

    with _yield_bump_my_version(version=version) as doc:
        current = _get_version(doc)
        try:
            text = check_output(
                ["git", "show", "origin/master:.bumpversion.toml"], text=True
            ).rstrip("\n")
            prev = _get_version(text)
        except (CalledProcessError, NonExistentKey):
            run(doc, Version(0, 1, 1))
        else:
            patch = prev.bump_patch()
            if current not in {patch, prev.bump_minor(), prev.bump_major()}:
                run(doc, patch)


def _run_pre_commit_update() -> None:
    path = xdg_cache_home() / "pre-commit-hook-nitpick" / get_repo_root().name

    def run() -> None:
        _ = check_call(["pre-commit", "autoupdate"])
        with writer(path, overwrite=True) as temp:
            _ = temp.write_text(get_now().format_iso())
        _ = _MODIFIED.set(True)

    try:
        text = path.read_text()
    except FileNotFoundError:
        run()
    else:
        prev = ZonedDateTime.parse_iso(text.rstrip("\n"))
        if prev < (get_now() - 4 * HOUR):
            run()


@contextmanager
def _yield_bump_my_version(
    *, version: VersionLike = _SETTINGS.code_version
) -> Iterator[TOMLDocument]:
    with _yield_toml_doc(".bumpversion.toml") as doc:
        tool = _get_table(doc, "tool")
        bumpversion = _get_table(tool, "bumpversion")
        bumpversion["allow_dirty"] = True
        bumpversion.setdefault("current_version", str(version))
        yield doc


@contextmanager
def _yield_github_push_tag(*, desc: str | None = None) -> Iterator[StrDict]:
    with _yield_yaml_dict(
        ".github/workflows/push--tag.yaml", desc=desc
    ) as push_tag_dict:
        push_tag_dict["name"] = "push"
        on = _get_dict(push_tag_dict, "on")
        push = _get_dict(on, "push")
        branches = _get_list(push, "branches")
        _ensure_contains(branches, "master")
        jobs = _get_dict(push_tag_dict, "jobs")
        tag = _get_dict(jobs, "tag")
        tag["runs-on"] = "ubuntu-latest"
        steps = _get_list(tag, "steps")
        _ = _ensure_contains_partial(
            steps,
            {
                "name": "Tag latest commit",
                "uses": "dycw/action-tag-commit@latest",
                "with": {"token": "${{ secrets.GITHUB_TOKEN }}"},
            },
        )
        yield push_tag_dict


@contextmanager
def _yield_json_dict(
    path: PathLike, /, *, desc: str | None = None
) -> Iterator[StrDict]:
    with _yield_write_context(path, json.loads, dict, json.dumps, desc=desc) as dict_:
        yield dict_


@contextmanager
def _yield_pre_commit(*, desc: str | None = None) -> Iterator[StrDict]:
    with _yield_yaml_dict(".pre-commit-config.yaml", desc=desc) as dict_:
        yield dict_


@contextmanager
def _yield_pyproject(
    *, desc: str | None = None, version: str = _SETTINGS.python_version
) -> Iterator[TOMLDocument]:
    with _yield_toml_doc("pyproject.toml", desc=desc) as doc:
        bld_sys = _get_table(doc, "build-system")
        bld_sys["build-backend"] = "uv_build"
        bld_sys["requires"] = ["uv_build"]
        project = _get_table(doc, "project")
        project["requires-python"] = f">= {version}"
        yield doc


@contextmanager
def _yield_pyrightconfig(
    *, desc: str | None = None, version: str = _SETTINGS.python_version
) -> Iterator[StrDict]:
    with _yield_json_dict("pyrightconfig.json", desc=desc) as dict_:
        dict_["deprecateTypingAliases"] = True
        dict_["enableReachabilityAnalysis"] = False
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
        yield dict_


@contextmanager
def _yield_pytest(*, desc: str | None = None) -> Iterator[TOMLDocument]:
    with _yield_toml_doc("pytest.toml", desc=desc) as doc:
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
        pytest["collect_imported_tests"] = False
        pytest["empty_parameter_set_mark"] = "fail_at_collect"
        filterwarnings = _get_array(pytest, "filterwarnings")
        _ensure_contains(filterwarnings, "error")
        pytest["minversion"] = "9.0"
        pytest["strict"] = True
        pytest["xfail_strict"] = True
        yield doc


@contextmanager
def _yield_ruff(
    *, desc: str | None = None, version: str = _SETTINGS.python_version
) -> Iterator[TOMLDocument]:
    with _yield_toml_doc("ruff.toml", desc=desc) as doc:
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
        yield doc


@contextmanager
def _yield_write_context[T](
    path: PathLike,
    loads: Callable[[str], T],
    get_default: Callable[[], T],
    dumps: Callable[[T], str],
    /,
    *,
    desc: str | None = None,
) -> Iterator[T]:
    path = Path(path)

    def run(verb: str, data: T, /) -> None:
        _LOGGER.info("%s '%s'%s...", verb, path, "" if desc is None else f" {desc}")
        with writer(path, overwrite=True) as temp:
            _ = temp.write_text(dumps(data))
        _ = _MODIFIED.set(True)

    try:
        data = loads(path.read_text())
    except FileNotFoundError:
        yield (default := get_default())
        run("Writing", default)
    else:
        yield data
        current = loads(path.read_text())
        if data != current:
            run("Modifying", data)


@contextmanager
def _yield_yaml_dict(
    path: PathLike, /, *, desc: str | None = None
) -> Iterator[StrDict]:
    with _yield_write_context(
        path, yaml.safe_load, dict, yaml.safe_dump, desc=desc
    ) as dict_:
        yield dict_


@contextmanager
def _yield_toml_doc(
    path: PathLike, /, *, desc: str | None = None
) -> Iterator[TOMLDocument]:
    with _yield_write_context(
        path, tomlkit.parse, document, tomlkit.dumps, desc=desc
    ) as doc:
        yield doc


if __name__ == "__main__":
    basic_config(obj=__name__)
    main()
