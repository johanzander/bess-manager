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

# Merged PRs are needed to tell a LIVE worktree from a DEAD one. Without this,
# any worktree left on disk pins its issue to In Progress forever: #602, #593
# and #542 all reported In Progress while their PRs (#610, #618, #591) had
# already merged, because the worktree was never pruned. `--state merged` is
# the only authoritative signal here — this repo squash-merges, so a merged
# branch is never an ancestor of main and `git branch --merged` reports
# nothing as merged.
#
# The bodies are REDUCED to the issue numbers they reference before being passed
# to jq. Passing 200 merged PR bodies through `--argjson` overflows the argument
# list ("/usr/bin/jq: Argument list too long") — this repo's PR bodies run to
# several KB each. Only the closing references and the branch name are needed to
# decide whether a merged PR belongs to an issue, so extract those here and hand
# jq a few hundred bytes instead of a megabyte.
merged_prs=$(gh pr list --repo "$repo" --state merged --limit 200 \
  --json number,headRefName,body \
  | jq -c '[ .[] | {
      number,
      headRefName,
      refs: [ (.body // "") | scan("(?i)(?:fixes|closes|resolves) #([0-9]+)") | .[0] | tonumber ]
    } ]')

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
# NOTE: the board does not exist yet (created by a deferred task), so the
# exact JSON key the Priority field lands under is still unverified. The jq
# below assumes it arrives as a top-level `.priority` on each item (matching
# the existing `$board.items[]?.priority?` lookup). Confirm this against a
# real board the first time one exists, and fix the jq path below if the
# assumption is wrong — do not add a fallback that tries multiple shapes.
board=$(gh project item-list "$PROJECT_NUMBER" --owner "${PROJECT_OWNER:-johanzander}" \
  --limit 200 --format json)

jq -n \
  --argjson issues "$issues" \
  --argjson prs "$prs" \
  --argjson merged_prs "$merged_prs" \
  --argjson worktrees "$worktrees" \
  --argjson sessions "$sessions" \
  --argjson board "$board" \
  --arg now "$(date -u +%s)" '
  def days_since($ts): (($now | tonumber) - ($ts | fromdateiso8601)) / 86400 | floor;

  def label_names: [.labels[].name];

  # Automation identities, so `last_comment.is_bot` can mark a comment that
  # carries no human signal. Stage 1 triage (issue-triage.yml) comments on every
  # issue it processes, so without this every issue looks like it has been
  # spoken on. bess-product-owner and bess-developer are the renamed/future
  # identities (see scripts/gh-agent.sh).
  def bot_authors: ["bess-manager-claude-bot", "bess-agent", "bess-product-owner", "bess-developer"];

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

  # Returns the whole worktree record, not just its path: the branch is needed
  # to decide whether that worktree is still live (see stale_worktree below).
  def worktree_for($n):
    ([ $worktrees[] | select(matches_issue(.; $n)) ]) as $matches
    | if ($matches | length) == 0 then null else $matches[0] end;

  # A worktree is STALE when its own branch has already been merged. This is an
  # exact branch-name comparison against the merged-PR list, deliberately not
  # the fuzzy issue-number match used to associate a worktree with an issue:
  #
  #   - fuzzy matching is right for "which issue does this worktree belong to",
  #     since branch names embed the issue number in several shapes
  #   - it is WRONG for "has this work landed", because a merged PR whose branch
  #     merely mentions the issue number proves nothing about THIS branch
  #
  # Getting that distinction wrong reclassified 7 open issues as Done, including
  # #118, #120 and #403 whose fixes had not shipped. It also contradicts this
  # project`s rule that a beta PR never carries `Closes #N` — an open issue with
  # a merged PR is the NORMAL state during beta graduation, not a finished one.
  def worktree_is_stale($wt):
    $wt != null
    and ($wt.branch // "") != ""
    and ([ $merged_prs[] | select(.headRefName == $wt.branch) ] | length) > 0;

  def session_for($n):
    ([ $sessions[] | select(.name? == "issue-\($n)") | .name ]) as $matches
    | if ($matches | length) == 0 then null else $matches[0] end;

  # Matched per LINE and anchored to its start, because `Blocked by #N` is a
  # convention -- a line in the body, optionally bulleted -- not a phrase to be
  # found anywhere in prose.
  #
  # A free `scan` over the whole body matched the substring regardless of what
  # preceded it, so "not blocked by #50 anymore" and "no longer blocked by #12"
  # both registered as live blockers. Those are the natural way to update an
  # issue once a blocker resolves, so the false positive fires exactly when the
  # blocker is gone. Anchoring rejects them without a negation blacklist, which
  # would only ever cover the phrasings someone thought of.
  #
  # This matters more than it looks: on main `blocked_by` was extracted and
  # never used, so the bad parse was inert. Gating `column()` on it is what
  # gives it teeth.
  def blocked_by:
    [ (.body // "") | split("\n")[]
      | select(test("^[[:space:]]*(?:[-*][[:space:]]*)?blocked by #[0-9]+"; "i"))
      | capture("blocked by #(?<n>[0-9]+)"; "i") | .n | tonumber ];

  # Only blockers that are STILL OPEN count. `$issues` is the open-issue list,
  # so membership decides it — no extra API call.
  #
  # A raw text scan cannot tell a live blocker from a settled one, and a
  # `Blocked by #N` line is never edited out once N merges. Treating the raw
  # scan as "unresolved" pins an item out of Ready for Dev permanently, which
  # is the same failure this script exists to fix, pointing the other way:
  # an item reading wrong relative to its real state. `blocked_by` stays the
  # raw parse so the reference remains visible.
  def blocked_by_open($refs):
    [ $refs[] | select(. as $n | ($issues | any(.number == $n))) ];

  # WHO SPOKE LAST. Without this the digest could not represent the single
  # transition that matters most to grooming: the reporter answering the
  # question we asked them. A comment COUNT and a last-activity DATE cannot
  # distinguish "the reporter supplied the debug log" from "we posted a nudge"
  # from "the reporter asked something new" — all three just increment a
  # number. #621 crossed the Definition of Ready line when @valexi7 attached
  # his bundle, and nothing in the digest could see it.
  def last_comment($comments; $author):
    ($comments | sort_by(.createdAt) | last) as $c
    | if $c == null then null
      else {
        author: ($c.author.login // "unknown"),
        days: days_since($c.createdAt),
        # "Reporter replied" is the actionable case: they are answering us, so
        # a wait on them may now be satisfied.
        is_reporter: (($c.author.login // "") == $author),
        is_bot: ((bot_authors | index($c.author.login // "")) != null)
      }
      end;

  # BLOCKING waits, derived from labels. Each of these means development
  # genuinely cannot start, so each one holds an item in Analysis.
  #
  # `discussion` is deliberately NOT in here any more. It used to be returned
  # whenever any human comment existed, which is not a blocker — a Ready item
  # picks up reporter thanks and follow-up questions all the time, and treating
  # those as a wait would strand it. "A human commented" is reported separately
  # below (last_comment_*) so the PO can judge; it no longer moves a column by
  # itself.
  def awaiting_from_labels($labels):
      if ($labels | index("needs-debug-log")) then "reporter"
      elif ($labels | index("ready-for-analysis")) then "analysis"
      elif ($labels | index("upstream")) then "upstream"
      else null end;

  # The board `Awaiting` field is AUTHORITATIVE when set, because it carries the
  # one wait no label can express: "blocked on a maintainer decision". #96 is
  # the case that forced this — it was labelled `analyzed`, carried no blocking
  # label, and still could not be implemented because its approach was
  # undecided. An implementation session was dispatched against it and
  # deadlocked immediately on three design questions.
  #
  # This is not a fallback chain over one fact. The two inputs answer different
  # questions: the label says "the pipeline is waiting on an external party",
  # the field says "the PO recorded a wait". `awaiting_suggested` below reports
  # what the label implies so a triage pass can reconcile an unset field,
  # rather than the digest silently inventing a value.
  def awaiting_from_board($n):
      [ $board.items[]? | select(.content.number? == $n) | .awaiting? | select(. != null) ][0] // null;

  # A worktree only means work-in-progress while nothing has superseded it.
  # A merged PR for the same issue means the branch already landed and the
  # worktree is just un-pruned rot.
  # Merged PRs that explicitly CLOSE this issue. Matches only on the extracted
  # closing references, never on a branch name — see worktree_is_stale for why
  # branch-name matching is unsafe here. Reported for information; it does not
  # move a column, because an open issue with a merged fix is the expected state
  # until the fix graduates to a stable release.
  def merged_pr_for($n):
    ([ $merged_prs[] | select((.refs | index($n)) != null) ]) as $matches
    | if ($matches | length) == 0 then null else $matches[0].number end;

  # Column names match the board`s Status options exactly (Backlog, Analysis,
  # Ready for Dev, In Progress, In Review, Done) so reconciling a card against
  # this value is a string comparison and not a translation table.
  #
  # PRECEDENCE IS THE FIX. `analyzed` used to be tested BEFORE any wait, so an
  # analysed-but-blocked item reported "Ready" and looked dispatchable. Waits
  # now win: an item whose scope is unsettled goes back to Analysis no matter
  # how far it got.
  #
  # `Ready for Dev` also now requires a Priority. The design always said so;
  # the condition was left out because no board existed and it would have made
  # Ready unreachable. The board exists, and every item carries P1-P4.
  def column($labels; $pr; $wt_live; $awaiting; $priority; $blocked):
      if $pr != null then "In Review"
      elif $blocked then "Analysis"
      elif $awaiting != null then "Analysis"
      elif $wt_live then "In Progress"
      elif ($labels | index("analyzed")) and $priority != null then "Ready for Dev"
      elif ($labels | index("analyzed")) then "Analysis"
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
      | (merged_pr_for(.number)) as $merged_pr
      | (worktree_for(.number)) as $wt
      | (worktree_is_stale($wt)) as $wt_stale
      | (($wt != null) and ($wt_stale | not)) as $wt_live
      | ([ $board.items[]? | select(.content.number? == $i.number) | .priority? ][0] // null) as $prio
      | (awaiting_from_labels($labels)) as $aw_label
      | (awaiting_from_board(.number)) as $aw_board
      | (($aw_board // $aw_label)) as $aw
      # Definition of Ready criterion 5: no unresolved blocker. The `blocked`
      # label and a still-open `Blocked by #N` both fail it, so neither item can
      # be Ready however far its analysis got. #571 was reporting `Ready for Dev`
      # while labelled `blocked`.
      | (blocked_by) as $bb
      | (blocked_by_open($bb)) as $bb_open
      | (($labels | index("blocked")) != null or (($bb_open | length) > 0)) as $blocked
      | (column($labels; $pr; $wt_live; $aw; $prio; $blocked)) as $col
      | {
          number: .number,
          title: .title,
          labels: $labels,
          author: .author.login,
          age_days: days_since(.createdAt),
          last_activity_days: days_since(.updatedAt),
          # Total comment count, bots included — a volume signal only. Nothing
          # derives a column from it: `awaiting` no longer comes from comment
          # activity at all, and `last_comment` below is what carries the
          # actionable detail (who spoke, when, whether it was the reporter).
          comments: (.comments | length),
          column: $col,
          # Reported for EVERY column, not just Analysis. Suppressing it
          # elsewhere hid the most common case there is: a Backlog item waiting
          # on a reporter reported `awaiting: null`, so the 14-day chase had
          # nothing to select on and never ran.
          awaiting: $aw,
          # Where that value came from, and what triage should set when the
          # board field is empty. Kept explicit rather than collapsed so a
          # reconciliation pass can see a divergence instead of guessing.
          awaiting_source: (if $aw == null then null
                            elif $aw_board != null then "board"
                            else "label" end),
          awaiting_suggested: $aw_label,
          last_comment: last_comment(.comments; .author.login),
          priority: $prio,
          pr: ($pr.number // null),
          pr_state: ($pr.mergeable // null),
          merged_pr: $merged_pr,
          worktree: ($wt.path // null),
          worktree_branch: ($wt.branch // null),
          # A worktree whose own branch has already merged is rot, and
          # `sweep-prs` is what removes it. Flagged so a board pass reports it
          # instead of reading it as active work: #593, #571, #542 and #466 all
          # showed "In progress" for exactly this reason while their PRs (#618,
          # #579, #591, #517) had already merged.
          stale_worktree: $wt_stale,
          session: session_for(.number),
          blocked_by: $bb,
          # The subset still open, and the only one that fails Ready.
          blocked_by_open: $bb_open,
          blocked: $blocked
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
