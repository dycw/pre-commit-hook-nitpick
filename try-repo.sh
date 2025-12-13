#!/usr/bin/env bash

# add hook to `project.scripts` and `.pre-commit-hooks.yaml`
# edit `HOOK_NAME` below
# in your project, run:
#     ~/personal/pre-commit-hooks-nitpick/try-repo.sh

PATH_DIR="$(
	cd -- "$(dirname "$0")" >/dev/null 2>&1 || exit
	pwd -P
)"

pre-commit try-repo --verbose --all-files "${PATH_DIR}" nitpick "$@"
