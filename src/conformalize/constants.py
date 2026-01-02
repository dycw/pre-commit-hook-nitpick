from __future__ import annotations

from pathlib import Path

from ruamel.yaml import YAML
from utilities.pathlib import get_repo_root

BUMPVERSION_TOML = Path(".bumpversion.toml")
COVERAGERC_TOML = Path(".coveragerc.toml")
GITHUB_WORKFLOWS = Path(".github/workflows")
GITHUB_PULL_REQUEST_YAML = GITHUB_WORKFLOWS / "pull-request.yaml"
GITHUB_PUSH_YAML = GITHUB_WORKFLOWS / "push.yaml"
PRE_COMMIT_CONFIG_YAML = Path(".pre-commit-config.yaml")
PYPROJECT_TOML = Path("pyproject.toml")
PYRIGHTCONFIG_JSON = Path("pyrightconfig.json")
PYTEST_TOML = Path("pytest.toml")
README_MD = Path("README.md")
REPO_ROOT = get_repo_root()
RUFF_TOML = Path("ruff.toml")
YAML_INSTANCE = YAML()


__all__ = [
    "BUMPVERSION_TOML",
    "COVERAGERC_TOML",
    "GITHUB_PULL_REQUEST_YAML",
    "GITHUB_PUSH_YAML",
    "GITHUB_WORKFLOWS",
    "PRE_COMMIT_CONFIG_YAML",
    "PYPROJECT_TOML",
    "PYRIGHTCONFIG_JSON",
    "PYTEST_TOML",
    "README_MD",
    "REPO_ROOT",
    "RUFF_TOML",
    "YAML_INSTANCE",
]
