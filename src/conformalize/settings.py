from __future__ import annotations

from typed_settings import EnvLoader, load_settings, option, settings

from conformalize.constants import RUN_VERSION_BUMP


@settings
class Settings:
    coverage: bool = option(default=False, help="Set up '.coveragerc.toml'")
    description: str | None = option(default=None, help="Repo description")
    envrc: bool = option(default=False, help="Set up '.envrc'")
    envrc__uv: bool = option(default=False, help="Set up '.envrc' with uv")
    envrc__uv__native_tls: bool = option(
        default=False, help="Set up '.envrc' with uv native TLS"
    )
    github__pull_request__pre_commit: bool = option(
        default=False, help="Set up 'pull-request.yaml' pre-commit"
    )
    github__pull_request__pyright: bool = option(
        default=False, help="Set up 'pull-request.yaml' pyright"
    )
    github__pull_request__pytest__all_versions: bool = option(
        default=False, help="Set up 'pull-request.yaml' pytest with all versions"
    )
    github__pull_request__pytest__os__macos: bool = option(
        default=False, help="Set up 'pull-request.yaml' pytest with MacOS"
    )
    github__pull_request__pytest__os__ubuntu: bool = option(
        default=False, help="Set up 'pull-request.yaml' pytest with Ubuntu"
    )
    github__pull_request__pytest__os__windows: bool = option(
        default=False, help="Set up 'pull-request.yaml' pytest with Windows"
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
    github__push__publish: bool = option(
        default=False, help="Set up 'push.yaml' publishing"
    )
    github__push__publish__trusted_publishing: bool = option(
        default=False, help="Set up 'push.yaml' with trusted publishing"
    )
    github__push__tag: bool = option(default=False, help="Set up 'push.yaml' tagging")
    github__push__tag__major: bool = option(
        default=False, help="Set up 'push.yaml' with the 'major' tag"
    )
    github__push__tag__major_minor: bool = option(
        default=False, help="Set up 'push.yaml' with the 'major.minor' tag"
    )
    github__push__tag__latest: bool = option(
        default=False, help="Set up 'push.yaml' tagging"
    )
    package_name: str | None = option(default=None, help="Package name")
    pre_commit__dockerfmt: bool = option(
        default=False, help="Set up '.pre-commit-config.yaml' dockerfmt"
    )
    pre_commit__dycw: bool = option(
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
    run_version_bump: bool = option(default=RUN_VERSION_BUMP, help="Run version bump")
    script: str | None = option(
        default=None, help="Set up a script instead of a package"
    )

    @property
    def python_package_name_use(self) -> str | None:
        if self.python_package_name is not None:
            return self.python_package_name
        if self.package_name is not None:
            return self.package_name.replace("-", "_")
        return None


LOADER = EnvLoader("")
SETTINGS = load_settings(Settings, [LOADER])


__all__ = ["LOADER", "SETTINGS", "Settings"]
