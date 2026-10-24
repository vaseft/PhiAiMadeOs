#!/usr/bin/env bash
set -euo pipefail
# Read-only check for the existing PAMOs repository, including Git worktrees.
if [ ! -e AGENTS.md ] || [ ! -e docs/32_VERSION_CONTROL_POLICY.md ]; then
  echo 'ERROR: run from the PAMOs project root' >&2; exit 2
fi
git rev-parse --is-inside-work-tree >/dev/null
expected='https://github.com/vaseft/PhiAiMadeOs.git'
if [ "$(git remote get-url origin)" != "$expected" ]; then
  echo 'ERROR: origin does not match the authorized PAMOs repository' >&2; exit 2
fi
git status --short
echo 'Read AGENTS.md and docs/32_VERSION_CONTROL_POLICY.md.'
echo 'Fetch origin, start a new feature branch from origin/develop, review explicit paths, test, commit, and open a PR to develop.'
echo 'This helper does not initialize, stage, commit, push, or change branches.'
