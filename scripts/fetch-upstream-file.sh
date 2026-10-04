#!/usr/bin/env bash
#
# Download one file from a GitHub repo at a given ref (tag, branch or SHA) to a
# local path. Read-only: a single GET of the contents API.
#
# It exists as a script for the same reason as scripts/pr-status.sh: reading
# upstream source (e.g. wills106/homeassistant-solax-modbus) otherwise needs an
# inline `gh api` call, which stays an ask rule because `gh api` can also write.
# Every argument is validated against a strict character set, so nothing the
# caller passes can turn this into a mutating call or escape the contents URL.
# Taking the output path as an argument also keeps loops and `> file`
# redirections out of the command line, which prompt on their own.
#
# Usage:
#   scripts/fetch-upstream-file.sh <owner/repo> <ref> <path-in-repo> <output-file>
#
# Example:
#   scripts/fetch-upstream-file.sh wills106/homeassistant-solax-modbus 2026.09.4 \
#     custom_components/solax_modbus/__init__.py "$TMPDIR/init-2026.09.4.py"
#
set -euo pipefail

if [ "$#" -ne 4 ]; then
  echo "usage: scripts/fetch-upstream-file.sh <owner/repo> <ref> <path-in-repo> <output-file>" >&2
  exit 2
fi
repo="$1" ref="$2" path="$3" out="$4"

if ! [[ "$repo" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]; then
  echo "invalid repo: $repo (expected owner/repo)" >&2
  exit 2
fi
if ! [[ "$ref" =~ ^[A-Za-z0-9_./-]+$ ]] || [[ "$ref" == *..* ]]; then
  echo "invalid ref: $ref" >&2
  exit 2
fi
if ! [[ "$path" =~ ^[A-Za-z0-9_./-]+$ ]] || [[ "$path" == *..* ]]; then
  echo "invalid path: $path" >&2
  exit 2
fi

gh api -H "Accept: application/vnd.github.raw" \
  "repos/$repo/contents/$path?ref=$ref" > "$out"
echo "$out: $(wc -l < "$out") lines"
