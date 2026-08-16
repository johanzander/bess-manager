#!/usr/bin/env bash
#
# Gather the Product Owner's evidence in one shot: issues, PRs, worktrees,
# background sessions and board state, joined into a single JSON document.
#
# This exists so no model ever reads 37 issue bodies to answer "what's next".
# The PO reads this table and opens an individual issue only when it is
# actually deciding on that issue.
#
# Usage: scripts/backlog-digest.sh [--repo owner/name]
set -euo pipefail

repo="${REPO:-johanzander/bess-manager}"

issues=$(gh issue list --repo "$repo" --state open --limit 200 \
  --json number,title,labels,author,createdAt,updatedAt,comments,body)

prs=$(gh pr list --repo "$repo" --state open --limit 100 \
  --json number,title,headRefName,mergeable,body)

worktrees=$(git worktree list --porcelain 2>/dev/null \
  | awk '/^worktree /{print $2}' | jq -R . | jq -s .)

sessions=$(claude agents --json 2>/dev/null || echo '[]')

board=$(gh project item-list "${PROJECT_NUMBER:-1}" --owner "${PROJECT_OWNER:-johanzander}" \
  --format json 2>/dev/null || echo '{"items":[]}')

jq -n \
  --argjson issues "$issues" \
  --argjson prs "$prs" \
  --argjson worktrees "$worktrees" \
  --argjson sessions "$sessions" \
  --argjson board "$board" \
  --arg now "$(date -u +%s)" '
  def days_since($ts): (($now | tonumber) - ($ts | fromdateiso8601)) / 86400 | floor;

  def label_names: [.labels[].name];

  def pr_for($n):
    ([ $prs[] | select(
          (.body // "" | test("(?i)(fixes|closes|resolves) #\($n)\\b"))
       or (.headRefName | test("issue-\($n)(\\D|$)"))
    ) ]) as $matches
    | if ($matches | length) == 0 then null else $matches[0] end;

  def worktree_for($n):
    ([ $worktrees[] | select(test("issue-\($n)(\\D|$)")) ]) as $matches
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
      elif ($comments | length) > 0 then "discussion"
      else null end;

  def column($labels; $pr; $wt; $awaiting):
      if $pr != null then "In review"
      elif $wt != null then "In progress"
      elif ($labels | index("analyzed")) then "Ready"
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
      [ $worktrees[] | select(. as $w | ($issues | map("issue-\(.number)") | any(. as $s | $w | test($s))) | not)
        | {kind: "worktree_no_pr", ref: ., detail: "no open issue matches this worktree"} ]
      +
      [ $prs[] | select((.body // "") | test("(?i)(fixes|closes|resolves) #\\d+") | not)
        | {kind: "pr_no_issue", ref: (.number | tostring), detail: .title} ]
    )
  }
'
