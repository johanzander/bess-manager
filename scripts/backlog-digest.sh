#!/usr/bin/env bash
#
# Gather the Product Owner's evidence in one shot: issues, PRs, worktrees,
# background sessions and board state, joined into a single JSON document.
#
# This exists so no model ever reads 37 issue bodies to answer "what's next".
# The PO reads this table and opens an individual issue only when it is
# actually deciding on that issue.
#
# Usage: scripts/backlog-digest.sh
set -euo pipefail

repo="${REPO:-johanzander/bess-manager}"

if [ -z "${PROJECT_NUMBER:-}" ]; then
  echo "backlog-digest.sh: PROJECT_NUMBER is not set — the backlog board has" >&2
  echo "not been created yet. Run scripts/backlog-board-init.sh (deferred) to" >&2
  echo "create it, then set PROJECT_NUMBER." >&2
  exit 1
fi

issues=$(gh issue list --repo "$repo" --state open --limit 200 \
  --json number,title,labels,author,createdAt,updatedAt,comments,body)

prs=$(gh pr list --repo "$repo" --state open --limit 100 \
  --json number,title,headRefName,mergeable,body)

# Emits, per worktree, a JSON object of {path, branch}. `git worktree list`
# always emits the main checkout as its first record, and it is excluded
# here — it is never a task worktree, so it must not appear in the orphan
# scan below.
worktrees=$(git worktree list --porcelain | awk '
  BEGIN { RS=""; FS="\n" }
  NR==1 { next }
  {
    path=""; branch=""
    for (i = 1; i <= NF; i++) {
      if ($i ~ /^worktree /)      { path = substr($i, 10) }
      else if ($i ~ /^branch /)   { branch = substr($i, 8); sub(/^refs\/heads\//, "", branch) }
    }
    if (path != "") print path "\t" branch
  }
' | jq -R 'split("\t") | {path: .[0], branch: (.[1] // "")}' | jq -s .)

sessions=$(claude agents --json)

# No `--field "Priority"` here: verified against the real CLI just now,
# `gh project item-list --field "Priority" --format json` is rejected
# outright with "cannot use --format with --field or --field-id" —
# `--field` only adds extra columns to the human-readable table, it is not
# a JSON-output selector. `--format json` alone was confirmed to reach the
# API (tested against a nonexistent project number: it returns a GraphQL
# "could not resolve" error, not a flag error), so JSON output is assumed to
# already include custom field values without needing `--field` at all.
# --limit matches the 200 used for `gh issue list` above; the item-list
# default is 30, which would silently truncate against this repo's 37+ open
# issues.
#
# Confirmed against the real board (2026-08-16): each custom single-select
# field arrives as a top-level key on the item — `"priority": "P1"` — next to
# `"status"` (the built-in column) and `"content": {"number": 611, ...}`, which
# is the join key used below. No `--field` flag is involved or possible.
board=$(gh project item-list "$PROJECT_NUMBER" --owner "${PROJECT_OWNER:-johanzander}" \
  --limit 200 --format json)

jq -n \
  --argjson issues "$issues" \
  --argjson prs "$prs" \
  --argjson worktrees "$worktrees" \
  --argjson sessions "$sessions" \
  --argjson board "$board" \
  --arg now "$(date -u +%s)" '
  def days_since($ts): (($now | tonumber) - ($ts | fromdateiso8601)) / 86400 | floor;

  def label_names: [.labels[].name];

  # Automation identities whose comments do not count as human discussion.
  # Stage 1 triage (issue-triage.yml) posts a comment on every issue it
  # processes, in every one of its four buckets, and a deferred task turns
  # that workflow into this very agent, as its own intake arm — at which point every
  # issue would carry a bot comment and a raw comment-count heuristic would
  # degenerate to "everything is a discussion". bess-product-owner and
  # bess-developer are the renamed/future identities (see scripts/gh-agent.sh).
  def bot_authors: ["bess-manager-claude-bot", "bess-agent", "bess-product-owner", "bess-developer"];

  def human_comments($comments): [ $comments[] | select((.author.login // "") as $a | (bot_authors | index($a)) | not) ];

  def pr_matches_issue($p; $n):
    ($p.body // "" | test("(?i)(fixes|closes|resolves) #\($n)\\b"))
    or ($p.headRefName | test("issue-\($n)(\\D|$)"));

  def pr_for($n):
    ([ $prs[] | select(pr_matches_issue(.; $n)) ]) as $matches
    | if ($matches | length) == 0 then null else $matches[0] end;

  # Matches a worktree whose path OR branch contains the issue number in a
  # delimited position: preceded by start-of-string, "-" or "/"; followed by
  # end-of-string, "-" or "_". Covers "issue-542", "fix-542-...",
  # "fix/issue-542-...", "design-466-..." without matching an unrelated
  # number that merely contains "542" as a substring (e.g. "15420").
  def issue_boundary($n): "(^|[-/])\($n)([-_]|$)";

  def matches_issue($w; $n):
    ($w.path | test(issue_boundary($n))) or ($w.branch | test(issue_boundary($n)));

  def worktree_for($n):
    ([ $worktrees[] | select(matches_issue(.; $n)) | .path ]) as $matches
    | if ($matches | length) == 0 then null else $matches[0] end;

  def session_for($n):
    ([ $sessions[] | select(.name? == "issue-\($n)") | .name ]) as $matches
    | if ($matches | length) == 0 then null else $matches[0] end;

  def blocked_by:
    [ (.body // "") | scan("(?i)blocked by #(\\d+)") | .[0] | tonumber ];

  def awaiting($labels; $comments):
      if ($labels | index("needs-debug-log")) then "reporter"
      elif ($labels | index("ready-for-analysis")) then "analysis"
      elif ($labels | index("upstream")) then "upstream"
      elif (human_comments($comments) | length) > 0 then "discussion"
      else null end;

  # Five derived columns. `Done` is deliberately absent and unreachable here:
  # only OPEN issues are fetched, so a closed one leaves the digest entirely
  # and cannot be derived into anything. The board fills `Done` itself via its
  # built-in item-closed workflow.
  #
  # These strings must match the Status options on the board EXACTLY — the
  # reconcile step compares them as strings, so a casing difference silently
  # strands every card. Confirmed against project 1 on 2026-08-16:
  #   Backlog, Analysis, Ready for Dev, In Progress, In Review, Done
  # `Ready for Dev` and `In Progress` follow the wording the board itself uses,
  # not the spec wording (`Ready`, `In progress`). The board is authoritative
  # for its own column names.
  #
  # NOTE: no apostrophes in this jq program. It is a single-quoted shell
  # string, so one apostrophe silently truncates the whole program and jq
  # reports only "Top-level program not given".
  #
  # Ready for Dev keys off the `analyzed` label alone, deliberately. The design
  # also requires Priority to be set, but gating on it here would strand every
  # analysed item whose priority the PO has not set yet. Add the priority
  # condition only alongside a rule that guarantees one gets set.
  def column($labels; $pr; $wt; $awaiting):
      if $pr != null then "In Review"
      elif $wt != null then "In Progress"
      elif ($labels | index("analyzed")) then "Ready for Dev"
      elif $awaiting != null then "Analysis"
      else "Backlog" end;

  {
    counts: {
      issues: ($issues | length),
      prs: ($prs | length),
      worktrees: ($worktrees | length),
      sessions: ($sessions | length)
    },
    items: [ $issues[] | . as $i
      | (label_names) as $labels
      | (pr_for(.number)) as $pr
      | (worktree_for(.number)) as $wt
      | (awaiting($labels; .comments)) as $aw
      | (column($labels; $pr; $wt; $aw)) as $col
      | {
          number: .number,
          title: .title,
          labels: $labels,
          author: .author.login,
          age_days: days_since(.createdAt),
          last_activity_days: days_since(.updatedAt),
          # Total comment count (bots included) — an activity signal, not
          # the discussion trigger. `awaiting: discussion` above is driven
          # by human_comments only; this field stays a raw total so the
          # digest still shows how much traffic (bot or human) an issue has.
          comments: (.comments | length),
          column: $col,
          awaiting: (if $col == "Analysis" then $aw else null end),
          priority: (
            [ $board.items[]? | select(.content.number? == $i.number) | .priority? ][0] // null
          ),
          pr: ($pr.number // null),
          pr_state: ($pr.mergeable // null),
          worktree: $wt,
          session: session_for(.number),
          blocked_by: blocked_by
        }
    ],
    orphans: (
      [ $worktrees[] | select(. as $w | ($issues | map(.number) | any(. as $n | matches_issue($w; $n))) | not)
        | {kind: "worktree_no_issue", ref: .path, detail: "no open issue matches this worktree"} ]
      +
      [ $prs[] | select(. as $p | ($issues | map(.number) | any(. as $n | pr_matches_issue($p; $n))) | not)
        | {kind: "pr_no_issue", ref: (.number | tostring), detail: .title} ]
    )
  }
'
