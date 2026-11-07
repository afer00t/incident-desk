#!/usr/bin/env bash
# Push the incident-desk history to a public GitHub repository.
# Usage: GITHUB_TOKEN=ghp_xxx ./push.sh owner/repo
# The token is used only for this push; the remote is left token-free afterwards.
set -euo pipefail

repo="${1:?usage: GITHUB_TOKEN=... ./push.sh owner/repo}"
token="${GITHUB_TOKEN:?GITHUB_TOKEN not set}"

[[ "$repo" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || { echo "bad repo: $repo" >&2; exit 2; }
git rev-parse --git-dir >/dev/null || { echo "not a git repo" >&2; exit 2; }

git remote remove origin 2>/dev/null || true
git remote add origin "https://x-access-token:${token}@github.com/${repo}.git"
trap 'git remote set-url origin "https://github.com/${repo}.git"' EXIT

git push -u origin master

git remote set-url origin "https://github.com/${repo}.git"
trap - EXIT
echo "pushed to https://github.com/${repo}"