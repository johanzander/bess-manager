#!/usr/bin/env bash
#
# Create the Product Owner's kanban board, once. Idempotent: if a project with
# this title already exists, print its number and change nothing.
#
# Run this as the MAINTAINER, not as the PO identity. A GitHub user cannot
# create a Project inside another user's account, and the board deliberately
# lives under the maintainer's account — it is their backlog and where they
# will look for it. `scripts/gh-agent.sh --as po project list --owner
# johanzander` returns "unknown owner type" for exactly this reason.
#
# The PO then gets write access to the board as a project collaborator, which
# is a separate grant from repo collaboration — repo write does NOT imply
# project write. That step is manual (see the end of this script's output):
# the Projects v2 API exposes no collaborator-invite mutation.
#
# Usage:
#   scripts/backlog-board-init.sh            # create or report the board
#
# Output (stdout, last line):
#   PROJECT_NUMBER <n>
set -euo pipefail

owner="${PROJECT_OWNER:-johanzander}"
title="BESS Manager Backlog"

# `gh project` needs the `project` scope. Fail with the fix rather than a raw
# GraphQL error — this is the single most common setup failure here.
if ! gh auth status 2>&1 | grep -q "project"; then
  echo "backlog-board-init.sh: your gh token lacks the 'project' scope." >&2
  echo "  Fix: gh auth refresh -s project" >&2
  exit 1
fi

# `|| true` here would be the difference between "no such board" and "the
# lookup failed", and this script creates a board when it sees the former. A
# rate limit or a transient GraphQL error would therefore produce a SECOND
# "BESS Manager Backlog" project, breaking the idempotence promised above. So
# a failed lookup stops the run instead of being read as an empty result.
if ! existing=$(gh project list --owner "$owner" --format json \
  --jq ".projects[] | select(.title == \"$title\") | .number"); then
  echo "backlog-board-init.sh: could not list projects for '$owner'." >&2
  echo "  Refusing to create a board without knowing whether one exists." >&2
  exit 1
fi

if [ -n "$existing" ]; then
  echo "Board already exists — nothing changed." >&2
  echo "PROJECT_NUMBER $existing"
  exit 0
fi

number=$(gh project create --owner "$owner" --title "$title" \
  --format json --jq '.number')

echo "Created project #$number." >&2

# Custom fields. The built-in Status field carries the columns and is edited
# separately (see the closing instructions) — `gh` cannot rewrite the options
# of a built-in single-select field.
#
# Priority is P1-P4 with no P0: that is what the live board carries, what the
# backlog skill documents, and what the digest ranks on. A P0 here would
# create an option no consumer reads.
gh project field-create "$number" --owner "$owner" \
  --name "Priority" --data-type SINGLE_SELECT \
  --single-select-options "P1,P2,P3,P4" >/dev/null
echo "  + Priority field (P1,P2,P3,P4)" >&2

gh project field-create "$number" --owner "$owner" \
  --name "Source" --data-type SINGLE_SELECT \
  --single-select-options "issue,TODO" >/dev/null
echo "  + Source field (issue,TODO)" >&2

gh project field-create "$number" --owner "$owner" \
  --name "Awaiting" --data-type SINGLE_SELECT \
  --single-select-options "reporter,discussion,upstream,analysis" >/dev/null
echo "  + Awaiting field (reporter,discussion,upstream,analysis)" >&2

cat >&2 <<REMAINING

Two steps remain and neither can be scripted — the Projects v2 API exposes no
mutation for either:

  1. Columns. Open the board, edit the built-in Status field, and set its
     options to exactly:
       Backlog, Analysis, Ready for Dev, In Progress, In Review, Done
     The digest derives these names; a mismatch silently strands cards.

  2. PO access. Project -> ... -> Settings -> Manage access -> invite
     bess-product-owner with write. Repo collaboration does NOT grant project
     access, so without this every board write fails as the PO.

Then export PROJECT_NUMBER=$number (or add it to your shell profile) and run
scripts/backlog-digest.sh to confirm the board is readable.

REMAINING

echo "PROJECT_NUMBER $number"
