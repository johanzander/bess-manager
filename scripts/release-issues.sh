#!/usr/bin/env bash
#
# List the open issues a stable release shipped, for the release skill's
# "close the issues this release ships" step (#827).
#
# Usage: scripts/release-issues.sh <previous-tag> <new-tag-or-ref>
#
# The release skill asks for approval BEFORE the new tag exists, so the end of
# the range may be `origin/main` there and the real tag afterwards.
#
# Which issue a PR belongs to is decided in ONE place, scripts/backlog-digest.sh
# (a work-verb scan of the PR body plus the `issue-<n>` branch convention).
# That rule has been duplicated before and the copies drifted (#684), so this
# script does not scan PR text: it reads the digest's per-issue `merged_prs` and
# adds only the tag range. An issue is listed when one of its merged PRs is in
# <previous-tag>..<new-tag>; it is PARTIAL when another PR for it is still open,
# RESOLVED otherwise. The digest's `column` is deliberately ignored -- an issue
# that was never put on the board reads as `Analysis` however finished it is.
#
# Resolved is the script's reading, not a verdict: `Refs` only says "related",
# so the release skill has the user confirm each issue before closing it.
#
# DIGEST_JSON=<file> reads a saved digest instead of running it (tests).
set -euo pipefail

prev="${1:?usage: $0 <previous-tag> <new-tag>}"
new="${2:?usage: $0 <previous-tag> <new-tag>}"

for ref in "$prev" "$new"; do
  git rev-parse -q --verify "$ref^{commit}" >/dev/null \
    || { echo "error: no such tag or ref: $ref" >&2; exit 1; }
done

# PR number -> subject for every commit in the range. The PR is the trailing
# `(#N)` of a squash-merge subject; an earlier `(#N)` in the same subject is the
# issue the author named, which is the digest's job to know, not ours.
subjects=$(git log "$prev..$new" --format='%s' | sed -nE 's/^(.*) \(#([0-9]+)\)$/\2\t\1/p')

if [ -n "${DIGEST_JSON:-}" ]; then
  digest=$(cat "$DIGEST_JSON")
else
  digest=$("$(dirname "$0")/backlog-digest.sh")
fi

listing=$(printf '%s' "$digest" | jq -r --arg subjects "$subjects" '
  ($subjects | split("\n") | map(select(length > 0) | split("\t") | {key: .[0], value: .[1]}) | from_entries) as $subj
  | .items[]
  | . as $i
  | [ $i.merged_prs[] | tostring | select($subj[.] != null) ] as $in_range
  | select(($in_range | length) > 0)
  | [ $i.prs[].number | "#\(.)" ] as $open
  | "#\($i.number)\t\(if ($open | length) > 0 then "partial (open PR \($open | join(", ")))" else "resolved" end)\t\($i.title)\tshipped via \($in_range | map("#" + .) | join(", ")): \($subj[$in_range[0]])"
' | sort -t'#' -k2 -n)

if [ -z "$listing" ]; then
  echo "No open issues are linked to the PRs in $prev..$new."
else
  printf '%s\n' "$listing"
fi
