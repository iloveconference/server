#!/usr/bin/env bash
# Build the search function into .aws-sam/build: export requirements.txt from poetry.lock, then
# run sam build. Extra arguments go to sam build.
#
# On a Linux arm64 host (such as the ubuntu-24.04-arm CI runner) the build runs natively.
# Anywhere else it runs in SAM's arm64 Python 3.12 build image (--use-container), which needs
# Docker, so the installed packages match the Lambda runtime.
#
# Environment:
#   POETRY  command that runs Poetry with poetry-plugin-export. The default runs the versions of
#           both that CI pins in .github/workflows/constraints.txt, through uvx.
#   SAM     command that runs the SAM CLI (default: sam). Without it installed, for example:
#             SAM="uvx --from aws-sam-cli sam" scripts/build.sh
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

# Prints the version of package $1 that CI pins.
pinned() {
	sed -n "s/^$1==//p" .github/workflows/constraints.txt
}

default_poetry="uvx --python 3.12 --with poetry-plugin-export==$(pinned poetry-plugin-export) poetry@$(pinned poetry)"
read -r -a poetry <<<"${POETRY:-$default_poetry}"
read -r -a sam <<<"${SAM:-sam}"

# Runtime dependencies only, for the Lambda package. requirements.txt is generated (gitignored).
"${poetry[@]}" export --without-hashes --format requirements.txt --output requirements.txt

os="$(uname -s)"
arch="$(uname -m)"
if [[ "$os" == Linux && "$arch" == aarch64 ]]; then
	"${sam[@]}" build "$@"
else
	"${sam[@]}" build --use-container "$@"
fi
