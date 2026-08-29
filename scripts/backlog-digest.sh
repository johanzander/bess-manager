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

# PROJECT_NUMBER and BESS_PO_TOKEN live in the repo's `.env`. Reading it here
# is the difference between the script working and the script never running:
# `.env` is gitignored, so nothing exports it, and every fresh shell — every
# `/loop /backlog` tick, every new session — hit the "board has not been
# created yet" exit on line one. That message was the worst kind of wrong:
# the board exists, is populated, and nothing about it needs fixing. The
# documented workaround (`set -a; . ./.env; set +a; ./scripts/backlog-digest.sh`)
# cannot survive an unattended pass, because the thing invoking the script is
# a skill, not a shell the maintainer typed into.
#
# `--git-common-dir` is what makes this ONE rule instead of a search over
# candidate paths. `.env` is gitignored, so it exists only in the main
# checkout and never in a worktree — and the common dir resolves to the main
# checkout's `.git` from either location, so its parent is the single
# directory where `.env` can be. `--path-format=absolute` is required:
# without it git may answer the relative `.git`, whose dirname is `.`, which
# silently resolves against the caller's cwd instead of the repo.
env_file="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")/.env"
if [ -f "$env_file" ]; then
  # The ENVIRONMENT WINS over the file. `set -a` sourcing would otherwise let
  # `.env` overwrite an explicit `PROJECT_NUMBER=2 scripts/backlog-digest.sh`,
  # which makes the variable un-overridable and makes any test that pins a
  # value silently read the maintainer's real board instead.
  env_project_number="${PROJECT_NUMBER:-}"
  env_po_token="${BESS_PO_TOKEN:-}"
  set -a
  # shellcheck disable=SC1090  # runtime path, by construction
  . "$env_file"
  set +a
  if [ -n "$env_project_number" ]; then PROJECT_NUMBER="$env_project_number"; fi
  if [ -n "$env_po_token" ]; then BESS_PO_TOKEN="$env_po_token"; fi
fi

if [ -z "${PROJECT_NUMBER:-}" ]; then
  echo "backlog-digest.sh: PROJECT_NUMBER is not set, and no PROJECT_NUMBER was" >&2
  echo "found in $env_file. The board is Project #1 (\"BESS Manager Backlog\");" >&2
  echo "add PROJECT_NUMBER=1 to that .env, or export it for this shell." >&2
  exit 1
fi

issues=$(gh issue list --repo "$repo" --state open --limit 200 \
  --json number,title,labels,author,createdAt,updatedAt,comments,body)

# GitHub computes `mergeable` LAZILY: the first query on a cold PR returns
# UNKNOWN and triggers the computation, so a single pass would report UNKNOWN
# as if it were a verdict. Re-query until no open PR is still UNKNOWN -- the
# budget covers the #490 measurement, which stayed UNKNOWN for six consecutive
# passes -- because the digest must never hang on a cold PR. A PR left UNKNOWN
# after the budget is emitted as null in `prs_for` below, so it never
# masquerades as a definite state.
MERGE_RETRY_LIMIT="${MERGE_RETRY_LIMIT:-6}"
MERGE_RETRY_SLEEP="${MERGE_RETRY_SLEEP:-2}"
prs=$(gh pr list --repo "$repo" --state open --limit 100 \
  --json number,title,headRefName,mergeable,body,isDraft)
merge_attempts=0
while printf '%s' "$prs" | jq -e 'any(.[]; .mergeable == "UNKNOWN")' >/dev/null 2>&1 \
      && [ "$merge_attempts" -lt "$MERGE_RETRY_LIMIT" ]; do
  merge_attempts=$((merge_attempts + 1))
  sleep "$MERGE_RETRY_SLEEP"
  prs=$(gh pr list --repo "$repo" --state open --limit 100 \
    --json number,title,headRefName,mergeable,body,isDraft)
done

# The EXACT half of the collision gate: what every open PR already touches.
# One gh pr diff per open PR, bounded by the WIP limit in practice. The
# alternative -- predicting a PRs touch-set from issue text alone -- is what
# let several PRs race to rewrite the same files; this reads the real diff
# instead of guessing.
#
# No `2>/dev/null || true` here: a PR whose diff cannot be read is NOT the
# same as a PR that touches no files. Swallowing the error would silently
# report that PR as touching nothing, which the collision gate would read as
# safe to dispatch against -- exactly the failure this key exists to prevent.
#
# It is ALSO not left to abort the whole digest any more. This script (and
# backlog-rhythm.sh downstream of it) runs under `set -euo pipefail`, so one
# undiffable PR -- a deleted fork head, a rate limit, a transient network
# error -- used to take down the entire rhythm pass, blocking all issue
# triage and dispatch over a single stale PR. Neither extreme is acceptable:
# the failure is recorded as DATA in `undiffable_prs` instead, and the loop
# continues over the remaining PRs. The collision gate (backlog-rhythm.sh)
# reads a non-empty `undiffable_prs` and suppresses dispatch entirely, since
# collision cannot be evaluated without a complete in-flight set.
in_flight_files='{}'
undiffable_prs='[]'
for n in $(printf '%s' "$prs" | jq -r '.[].number'); do
  if ! files=$(gh pr diff "$n" --repo "$repo" --name-only); then
    undiffable_prs=$(printf '%s' "$undiffable_prs" | jq --argjson n "$n" '. + [$n]')
    continue
  fi
  in_flight_files=$(printf '%s' "$in_flight_files" | jq \
    --argjson n "$n" \
    --argjson f "$(printf '%s' "$files" | jq -R -s 'split("\n") | map(select(length > 0))')" \
    'reduce $f[] as $p (.; .[$p] = ((.[$p] // []) + [$n] | unique))')
done

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
# Inline-code spans carry EXAMPLES, never linkage declarations, so a `#N`
# inside backticks must not associate a PR with an issue. Defined once, here,
# because BOTH linkage scans need it and they are separate jq programs -- the
# merged-PR scan immediately below, and `linkage_body` in the digest program
# further down. Fixing only one of them is how PR #684 shipped: it stripped
# code spans in the merged scan while its own body, quoting
# `- Blocked by #100 -- part of #409` as the worked example, went on linking
# itself to issue #409 through the open-PR scan it had not touched.
jq_strip_code_spans='def strip_code_spans: gsub("`[^`]*`"; "");'

merged_prs=$(gh pr list --repo "$repo" --state merged --limit 200 \
  --json number,headRefName,body \
  | jq -c "$jq_strip_code_spans"'[ .[] | {
      number,
      headRefName,
      # WORK references only -- the closing verbs plus the no-auto-close
      # spellings (`Part of`, `tracking`, `Refs`). Deliberately NOT bare `#N`:
      # a merged PR body can name other issues without working on them
      # ("until #456 and #457 are also resolved"), and a merged PR must not
      # flip an unrelated issue to In Verification. Drives both `merged_pr`
      # (the column) and `merged_prs` (the visibility list).
      #
      # Inline-code spans are stripped BEFORE scanning, so `#N` inside a
      # backticked worked example cannot flip an issue: PR #679 explained its
      # own fix with the literal line `- Blocked by #100 -- part of #409` and
      # that example bounced issue #409 to In Verification. A real linkage
      # declaration is never in code markup.
      refs: [ (.body // "") | strip_code_spans | scan("(?i)(?:fixes|closes|resolves|refs|part of|tracking|tracks) #([0-9]+)") | .[0] | tonumber ],
      # Any `#N` LEFT in the body once code spans and the cross-reference
      # phrases ("Related to", "See also", "Blocked by", ...) are stripped --
      # the same phrase list `linkage_body` uses in the digest program. Used
      # ONLY to corroborate a branch-convention match in `merged_pr_for`: the
      # branch name alone is not trusted to flip a column (a merged PR on
      # `fix/issue-403-logging` whose body says "Related to #403. Not closing
      # it" must not), but branch convention PLUS a non-cross-ref body mention
      # of the same number is the #428/#705 case -- a merged PR that genuinely
      # implemented the issue but, under the no-auto-close rule, carries no
      # closing verb.
      mentions: [ (.body // "")
                  | strip_code_spans
                  | gsub("(?i)(blocked by|depends on|unblocks?(?:ing)?|related to|relationship to|follow[- ]?up to|see also|see|not part of) #[0-9]+"; "")
                  | scan("#([0-9]+)") | .[0] | tonumber ]
    } ]')

# Closed-but-UNMERGED PRs, by branch. A worktree whose own branch is the exact
# head of a PR the maintainer closed without merging is an ABANDONED attempt,
# not resumable work: #428 shipped via merged PR #705 while its earlier branch
# `feat/issue-428-consumption-forecast-series` -- the head of closed PR #437 --
# still sat on disk, so `worktree_is_stale` (merged-only) read it as live and
# the rhythm pass proposed `/implement-issue 428` against the dead branch on
# every tick. Exact `headRefName` comparison only, the same discipline
# `worktree_is_stale` applies to the merged list and for the same reason -- a
# fuzzy issue-number match would strand a live follow-up branch the moment any
# same-issue PR closed.
#
# `--state closed` returns BOTH closed-unmerged and merged PRs, so the
# `mergedAt == null` filter is load-bearing: without it every merged branch
# would also land here and `stale_worktree_reason` would misreport why a
# worktree is dead.
closed_prs=$(gh pr list --repo "$repo" --state closed --limit 200 \
  --json number,headRefName,mergedAt \
  | jq -c '[ .[] | select(.mergedAt == null) | {number, headRefName} ]')

# Emits, per worktree, a JSON object of {path, branch, locked}. `git worktree
# list` always emits the main checkout as its first record, and it is excluded
# here — it is never a task worktree, so it must not appear in the orphan
# scan below.
#
# `locked` is the LIVENESS signal, and it is the only one that works. See the
# session note below.
worktrees=$(git worktree list --porcelain | awk '
  BEGIN { RS=""; FS="\n" }
  NR==1 { next }
  {
    path=""; branch=""; locked="false"
    for (i = 1; i <= NF; i++) {
      if ($i ~ /^worktree /)      { path = substr($i, 10) }
      else if ($i ~ /^branch /)   { branch = substr($i, 8); sub(/^refs\/heads\//, "", branch) }
      else if ($i ~ /^locked/)    { locked = "true" }
    }
    if (path != "") print path "\t" branch "\t" locked
  }
' | jq -R 'split("\t") | {path: .[0], branch: (.[1] // ""), locked: (.[2] == "true")}' | jq -s .)

# `claude agents` lists BACKGROUND agents only, and this is the trap that made
# the rhythm pass tell the maintainer to restart work that was actively
# running. Two independent reasons it cannot answer "is someone on this":
#
#   1. A session started in the terminal — `claude` in a CLI, then
#      `/implement-issue <n>` — is a foreground session and never appears here
#      at all. That is how #624 was dispatched.
#   2. Even a background agent carries a generated descriptive name ("Review PR
#      and create branch for bess-manager"), not the `issue-<n>` the dispatch
#      convention promises, so the exact-name match below misses it too.
#
# Measured: 41 worktrees on disk, `claude agents --json` returning ONE entry.
# So `session` was null for essentially every item, every worktree read as
# abandoned, and `resume_implementation` fired on live sessions — against work
# whose branch commits the skill itself calls the only copy.
#
# The worktree LOCK is the signal that actually tracks a live session: 4 of
# those 41 were locked, and they were exactly the four live sessions. It is
# local, needs no process list, and covers foreground and background alike.
# `session` is kept because a name match is strictly more informative when it
# does happen; it is no longer what liveness rests on.
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
  --argjson closed_prs "$closed_prs" \
  --argjson worktrees "$worktrees" \
  --argjson sessions "$sessions" \
  --argjson board "$board" \
  --argjson in_flight "$in_flight_files" \
  --argjson undiffable_prs "$undiffable_prs" \
  --arg now "$(date -u +%s)" "$jq_strip_code_spans"'
  def days_since($ts): (($now | tonumber) - ($ts | fromdateiso8601)) / 86400 | floor;

  def label_names: [.labels[].name];

  # Automation identities, so `last_comment.is_bot` can mark a comment that
  # carries no human signal. Stage 1 triage (issue-triage.yml) comments on every
  # issue it processes, so without this every issue looks like it has been
  # spoken on. bess-product-owner and bess-developer are the renamed/future
  # identities (see scripts/gh-agent.sh).
  def bot_authors: ["bess-manager-claude-bot", "bess-agent", "bess-product-owner", "bess-developer"];

  # How many times an implementation session has been handed back on this
  # issue. The marker is an HTML comment, so the handoff reads as ordinary
  # prose on GitHub while staying exactly countable here -- no local file, and
  # no guessing from prose.
  def resume_count($comments):
    [ $comments[]? | select((.body // "") | contains("<!-- resume-handoff -->")) ] | length;

  # LINKAGE is any `#N` reference in the body, not just the closing verbs. The
  # no-auto-close rule forbids `Closes #N` on an intermediate PR -- it says
  # `Part of #N`, `tracking #N`, `Refs #N`, or a bare `#N` -- so a digest that
  # links by closing keyword only makes that PR invisible (the #409/#490
  # defect). Whether the work has LANDED is the merged-PR scan above, which is
  # deliberately narrower (work verbs only) so a merged PR that merely names
  # another issue cannot flip it to In Verification; linkage here is the broad
  # any-`#N` net for OPEN PRs. The number is bounded on both sides so `#2409`
  # does not match issue 409 and `#4095` does not match 409.
  #
  # Cross-references that name an issue WITHOUT claiming to work on it are
  # stripped before matching, so they neither link nor orphan-claim: the
  # documented `Blocked by #N` convention, `Depends on`, `Unblocks`,
  # `Related to` (and `unrelated to`), `Relationship to`, `Follow-up to`,
  # `See also`. Real bodies use these -- "Related to #403. Not closing it",
  # "unblocks #485", "unrelated to #402" -- and linking on them would flip an
  # unrelated issue to In Review. Stripping the PHRASE, not the whole
  # line, keeps a combined reference like "- Blocked by #100 -- part of #409"
  # working: only the blocker phrase disappears and #409 still links. The
  # remaining test is still any `#N`, so the no-auto-close spellings
  # (`Part of #N`, `tracking #N`, `Refs #N`, bare `#N`) all link.
  #
  # Inline-code spans go first, for the same reason the merged scan strips
  # them: a backticked worked example is not a declaration. The phrase list
  # below cannot cover this on its own -- `part of #N` is REAL linkage and so
  # is deliberately absent from it, which means a quoted example carrying that
  # phrase links unless the markup is removed before matching.
  def linkage_body($body):
    ($body // "")
    | strip_code_spans
    | gsub("(?i)(blocked by|depends on|unblocks?(?:ing)?|related to|relationship to|follow[- ]?up to|see also|see|not part of) #[0-9]+"; "");

  def pr_matches_issue($p; $n):
    (linkage_body($p.body) | test("(?i)(^|[^0-9])#\($n)\\b"))
    or ($p.headRefName | test("issue-\($n)(\\D|$)"));

  # Returns EVERY matching PR, ascending. Taking `[0]` discarded the rest, and
  # with one issue routinely carrying several PRs that meant the column was
  # derived from whichever happened to sort first.
  def prs_for($n):
    [ $prs[] | select(pr_matches_issue(.; $n))
             | {number: .number,
                # A mergeable still UNKNOWN after the retry loop is not a
                # verdict -- report null so no consumer reads it as definite.
                mergeable: (if .mergeable == "UNKNOWN" then null else .mergeable end),
                isDraft: .isDraft} ]
    | sort_by(.number);

  # Matches a worktree whose path OR branch contains the issue number in a
  # delimited position: preceded by start-of-string, "-" or "/"; followed by
  # end-of-string, "-" or "_". Covers "issue-542", "fix-542-...",
  # "fix/issue-542-..." without matching an unrelated number that merely
  # contains "542" as a substring (e.g. "15420").
  def issue_boundary($n): "(^|[-/])\($n)([-_]|$)";

  # Scratch worktrees -- `pin-<n>-...` (scenario pinning), `design-<n>-...`
  # (design docs) and `bench-...` (benchmarking), optionally under the
  # `worktree-` prefix EnterWorktree adds -- carry an issue number but are not
  # implementation branches. Joining them to an issue made a leftover pin
  # worktree pin the issue to In Progress for good (#602, #707). The number is
  # matched anywhere after the prefix so `worktree-pin-602-evening-carry` is
  # caught by its branch as well as its path basename.
  def is_scratch($s): ($s // "") | test("(^|/)(worktree-)?(pin|design|bench)-");

  def matches_issue($w; $n):
    (is_scratch($w.path) or is_scratch($w.branch) | not)
    and (($w.path | test(issue_boundary($n))) or ($w.branch | test(issue_boundary($n))));

  # Returns the whole worktree record, not just its path: the branch is needed
  # to decide whether that worktree is still live (see stale_worktree below).
  def worktree_for($n):
    ([ $worktrees[] | select(matches_issue(.; $n)) ]) as $matches
    | if ($matches | length) == 0 then null else $matches[0] end;

  # A worktree is STALE when the PR for its own branch is GONE -- merged, or
  # closed without merging. Either way the branch will never produce a merge from
  # here, so the worktree is rot for `sweep-prs` to prune and never resumable
  # work. Both are an exact branch-name comparison against a PR list,
  # deliberately not the fuzzy issue-number match used to associate a worktree
  # with an issue:
  #
  #   - fuzzy matching is right for "which issue does this worktree belong to",
  #     since branch names embed the issue number in several shapes
  #   - it is WRONG for "has the work on THIS branch ended", because another PR whose
  #     branch merely mentions the issue number proves nothing about THIS branch
  #
  # Getting that distinction wrong reclassified 7 open issues as Done, including
  # #118, #120 and #403 whose fixes had not shipped. It also contradicts this
  # project`s rule that a beta PR never carries `Closes #N` — an open issue with
  # a merged PR is the NORMAL state during beta graduation, not a finished one.
  # (A stale worktree does NOT by itself close its issue -- it only stops the
  # worktree reading as live work; the column still comes from the merged-PR
  # scan and the labels.)
  def worktree_dead_pr($wt):
    if $wt == null or ($wt.branch // "") == "" then null
    else ( [ $merged_prs[] | select(.headRefName == $wt.branch) | {number, why: "merged in #\(.number)"} ]
         + [ $closed_prs[] | select(.headRefName == $wt.branch) | {number, why: "was the head of closed-unmerged PR #\(.number)"} ]
         )[0] // null end;
  def worktree_is_stale($wt):
    worktree_dead_pr($wt) != null;

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

  # The most recent `@claude-bot analyze` trigger on the issue, and how long ago
  # it was posted. Stage 2 normally finishes in minutes and stamps `analyzed` or
  # `needs-human-review` (removing `ready-for-analysis`); a trigger that is hours
  # old with the item still `ready-for-analysis` and unstamped means the run
  # never completed -- most often because the workflow had no API credit. The
  # rhythm pass reads this two ways: `autonomous_analyze` stands down while ANY
  # analyze comment exists (so it never double-spends), and `refire_analyze`
  # re-posts the trigger once this ages past its staleness window. Matched on the
  # comment BODY, any author, since the PO identity posts it via gh-agent.sh.
  def last_analyze_comment($comments):
    ([ $comments[]? | select((.body // "") | test("@claude-bot[[:space:]]+analyze"; "i")) ]
     | sort_by(.createdAt) | last) as $c
    | if $c == null then null
      else {
        days: days_since($c.createdAt),
        hours: ((($now | tonumber) - ($c.createdAt | fromdateiso8601)) / 3600 | floor)
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

  # The CURRENT column of the card, straight off the board. `column` below is
  # the column the evidence says it should be in; without this field the two
  # could never be compared, and the `board` verb — "reconcile every card
  # against the derived column, the digest always wins" — had nothing to
  # reconcile against. A pass had to make a second `gh project item-list` call
  # by hand to recover exactly this, which is the one thing this script exists
  # to stop.
  #
  # NOTE: no apostrophes anywhere in this jq program. It is a single-quoted
  # shell string, so one apostrophe in a comment ends it early and jq reports
  # the useless "Top-level program not given".
  #
  # `null` means NO CARD, not "no status": an issue that never made it onto the
  # board. That is a live trap rather than a cosmetic gap, because
  # `Ready for Dev` now requires a Priority and priority is a board field — so
  # an off-board issue can never become dispatchable however well it is
  # analysed. #621 and #624 were both in that state.
  def board_status($n):
      [ $board.items[]? | select(.content.number? == $n) | .status? | select(. != null) ][0] // null;

  # A worktree only means work-in-progress while nothing has superseded it.
  # A merged PR for the same issue means the branch already landed and the
  # worktree is just un-pruned rot.
  #
  # A merged PR belongs to an issue when EITHER:
  #   (a) its body carries a work-verb reference (`fixes|closes|resolves|refs|
  #       part of|tracking` #N -- the `refs` list), OR
  #   (b) its head branch follows the dispatch convention `.../issue-<n>-...`
  #       (which `run-agent.sh` and implement-issue Step 4 enforce) AND the
  #       body still mentions `#n` once cross-reference phrases are stripped
  #       (the `mentions` list).
  #
  # (b) exists because dropping the branch signal the instant a PR merges is
  # the bug that left #428 reading `Backlog` after PR #705
  # (`feat/issue-428-consumption-overlay`) shipped it to beta -- #705 links the
  # issue only as a bare `#428` and a comment URL, no work verb, which is
  # legitimate under the no-auto-close rule. The `mentions` half is what keeps
  # (b) narrow: a merged PR on `fix/issue-403-logging` whose body says "Related
  # to #403. Not closing it" still must NOT flip #403 -- the branch matches but
  # the only body reference is a cross-ref phrase, which `mentions` has
  # stripped. `prs_for` trusts the bare branch convention for OPEN PRs; the
  # merged path is deliberately one notch stricter, because a merged PR moves a
  # column and an open one does not.
  #
  # It still does not CLOSE the issue -- an open issue with a merged fix is the
  # expected state through beta graduation. It drives the `In Verification`
  # column and the `merged_prs` visibility list.
  def merged_matches_issue($p; $n):
    (($p.refs | index($n)) != null)
    or (((($p.headRefName // "") | test("issue-\($n)(\\D|$)")))
        and (($p.mentions | index($n)) != null));
  def merged_pr_for($n):
    ([ $merged_prs[] | select(merged_matches_issue(.; $n)) ]) as $matches
    | if ($matches | length) == 0 then null else $matches[0].number end;

  # Column names match the board`s Status options exactly (Backlog, Analysis,
  # Ready for Dev, In Progress, In Review, In Verification, Done) so
  # reconciling a card against this value is a string comparison and not a
  # translation table.
  #
  # `Ready for Dev` also requires a Priority. The design always said so; the
  # condition was left out because no board existed and it would have made
  # Ready unreachable. The board exists, and every item carries P1-P4.
  #
  # PHASE COMES FROM ARTIFACTS, with one override a wait DOES rewrite (#707).
  # `Status` is the stage, `Awaiting` is the wait -- mostly orthogonal, but a
  # recorded wait (or `blocked`) pulls the item BACK to Analysis over a bare
  # worktree or a still-draft PR, because unsettled scope must not read as
  # progress. It does NOT override In Review -- a PR that is out of draft is
  # genuinely in the review loop -- and the rhythm pass ranks the wait
  # separately.
  #
  # "Back" is literal: the wait is a FLOOR-LOWER, never a set. It can only move
  # an item LEFT (toward Analysis), never right. A `discussion` / `blocked` tag
  # on a raw Backlog musing (no worktree, no PR, no `analyzed` label -- #703)
  # must NOT be promoted to Analysis: that manufactured a `board_status` !=
  # `column` mismatch every pass, so `move_card` yanked the card to Analysis
  # minutes after a human moved it to Backlog, forever. The artifact/label
  # column is computed first as `$natural`; the wait only rewrites it when
  # `$natural` is already right of Analysis.
  #
  # DRAFT IS NOT IN REVIEW (#707). An open PR only means In Review once it is
  # out of draft -- the review loop has actually started. A draft PR is In
  # Progress: the branch and PR exist, nothing is reviewing them yet. This is
  # what lets #162 (draft PR, parked for the reporter) read as In Progress, and
  # as Analysis once an `Awaiting` is set on it.
  #
  # ORDER IS THE CONTENT. Active work outranks landed work: In Progress (a live
  # worktree or an open draft PR) is checked before In Verification, so an
  # issue with a merged intermediate PR AND an active follow-up branch reads
  # as In Progress, not as verified. A stray merged-and-done issue with a rot
  # worktree does not hit this -- scratch worktrees are excluded by
  # `matches_issue` and a genuinely merged branch is caught by
  # `worktree_is_stale`, so `$wt_live` is already false for both (#602).
  def column($labels; $open_prs; $merged_pr; $wt_live; $awaiting; $priority; $blocked):
      (any($open_prs[]; .isDraft != true)) as $in_review
      | (($wt_live) or (any($open_prs[]; .isDraft == true))) as $in_progress
      # The column the artifacts and labels imply, before any wait override.
      | (if $in_review then "In Review"
         elif $in_progress then "In Progress"
         elif $merged_pr != null then "In Verification"
         elif ($labels | index("analyzed")) and $priority != null then "Ready for Dev"
         elif ($labels | index("analyzed")) then "Analysis"
         else "Backlog" end) as $natural
      # A recorded wait / block pulls back to Analysis -- but only from a column
      # right of Analysis, and never out of In Review (#707). From Backlog it is
      # a no-op: a wait cannot promote un-analysed work.
      | if ($blocked or $awaiting != null)
           and $natural != "In Review"
           and $natural != "Backlog"
        then "Analysis"
        else $natural end;

  {
    counts: {
      issues: ($issues | length),
      prs: ($prs | length),
      worktrees: ($worktrees | length),
      sessions: ($sessions | length)
    },
    items: [ $issues[] | . as $i
      | (label_names) as $labels
      | (prs_for(.number)) as $open_prs
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
      | (column($labels; $open_prs; $merged_pr; $wt_live; $aw; $prio; $blocked)) as $col
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
          # Where the card actually sits today, so a board pass can diff it
          # against `column` above. null = the issue has no card at all.
          board_status: board_status(.number),
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
          # The last `@claude-bot analyze` trigger and its age -- `{days, hours}`
          # or null. Drives `refire_analyze` (re-post a Stage 2 run that never
          # completed) and stands `autonomous_analyze` down while any analyze
          # comment exists.
          last_analyze_comment: last_analyze_comment(.comments),
          priority: $prio,
          prs: $open_prs,
          # Every merged PR that belongs to this issue -- a WORK-verb body
          # reference (`fixes/closes/resolves/refs/part of/tracking`) OR the
          # `issue-<n>` dispatch branch convention, the same association
          # `merged_pr_for` uses. `merged_pr` above is the first in the order
          # `gh` returns (the most recent merge) and drives the In Verification
          # column; this plural exposes all of them, sorted, so a merged
          # intermediate PR (`Part of #N`, which must not close the issue)
          # stays visible even alongside later PRs.
          merged_prs: ([ $merged_prs[]
                         | select(merged_matches_issue(.; $i.number))
                         | .number ] | sort),
          merged_pr: $merged_pr,
          worktree: ($wt.path // null),
          worktree_branch: ($wt.branch // null),
          # A LIVE session holds its worktree locked. This, not `session`, is
          # what says whether anyone is on the item — see the note where the
          # worktree list is built.
          worktree_locked: ($wt.locked // false),
          # A worktree whose branch has no live PR -- merged, OR closed
          # unmerged -- is rot, and `sweep-prs` is what removes it. Flagged so a
          # board pass reports it instead of reading it as active work: #593,
          # #571, #542 and #466 all showed "In progress" for exactly this reason
          # while their PRs (#618, #579, #591, #517) had already merged; #428
          # showed it while its abandoned branch sat behind closed PR #437.
          stale_worktree: $wt_stale,
          # Why it is stale, ready for the rhythm pass to quote verbatim:
          # "merged in #N" or "was the head of closed-unmerged PR #N".
          stale_worktree_reason: ((worktree_dead_pr($wt)).why // null),
          session: session_for(.number),
          resume_count: resume_count(.comments),
          blocked_by: $bb,
          # The subset still open, and the only one that fails Ready.
          blocked_by_open: $bb_open,
          blocked: $blocked
        }
    ],
    # BOARD STATE FOR PULL REQUESTS, keyed by number.
    #
    # The board holds issues, and every judgement about a PR therefore had
    # nowhere to live. "#437 is lower priority, I will get to it later" and
    # "#167 and #354 are blocked" are real decisions, and the rhythm pass
    # re-reported all three as due on every tick because nothing recorded them
    # — so the same conversation happened every 30 minutes.
    #
    # Projects v2 takes PRs as items with the identical field set, so the fix
    # is membership rather than a parallel mechanism: a PR card carries the
    # same `Priority` and `Awaiting` an issue card does, and `backlog-rhythm.sh`
    # suppresses on them.
    #
    # `content.type` is what separates the two, confirmed against a real card
    # rather than assumed: an added PR reports `"type": "PullRequest"` with
    # `number`, `title`, `url` and `repository` alongside it. Numbers are unique
    # across issues and PRs in one repository, so this cannot collide with the
    # issue lookup above.
    #
    # Emitted as a lookup rather than merged into a PR list, because the digest
    # does not own the open-PR list — `backlog-rhythm.sh` fetches that with the
    # review fields it needs, and joins this in by number.
    in_flight_files: $in_flight,
    # PRs whose diff could not be read this pass -- see the loop above.
    # Reported as data, not swallowed and not fatal.
    undiffable_prs: $undiffable_prs,
    pr_board: [
      $board.items[]?
      | select(.content.type? == "PullRequest")
      | {
          number: .content.number,
          board_status: (.status? // null),
          priority: (.priority? // null),
          awaiting: (.awaiting? // null)
        }
    ],
    orphans: (
      [ $worktrees[] | select(. as $w | ($issues | map(.number) | any(. as $n | matches_issue($w; $n))) | not)
        | {kind: "worktree_no_issue", ref: .path, detail: "no open issue matches this worktree"} ]
      +
      [ $prs[] | select(. as $p | ($issues | map(.number) | any(. as $n | pr_matches_issue($p; $n))) | not)
        | {kind: "pr_no_issue", ref: (.number | tostring), detail: .title} ]
      +
      # An open issue with no card. Reported as an orphan because it is
      # invisible everywhere else: it carries no Priority and no Awaiting, so
      # it cannot reach `Ready for Dev`, cannot be ranked by `next`, and reads
      # as a quiet un-groomed Backlog item rather than as a missing card.
      # Adding it to the board is a triage action, not a bug in the item.
      [ $issues[] | select(board_status(.number) == null)
        | {kind: "issue_no_card", ref: (.number | tostring), detail: .title} ]
      +
      # A PullRequest CARD whose PR is no longer open (#707 / #638). A PR card
      # exists only to carry a deferral decision (`Priority` / `Awaiting`)
      # while the PR is open -- `backlog-rhythm.sh` joins `pr_board` against
      # the OPEN-PR list, so once the PR closes or merges its card is
      # reconciled by nothing: not `items` (issues only), not the rest of
      # `orphans`, not any rhythm action. It just sits in whatever column it
      # was last in -- #638, a closed draft, sat in `In Review` indefinitely.
      # A merged PR card is equally moot unless it has reached `Done`.
      ( [ $prs[].number ] as $open_pr_nums
        | [ $merged_prs[].number ] as $merged_pr_nums
        | [ $board.items[]?
            | select(.content.type? == "PullRequest")
            | . as $card
            | ($card.content.number) as $pn
            | select(($open_pr_nums | index($pn)) == null)
            | select(($card.status // "") != "Done")
            | (($merged_pr_nums | index($pn)) != null) as $is_merged
            | {kind: "stale_pr_card",
               ref: ($pn | tostring),
               detail: (if $is_merged
                        then "PR #\($pn) has merged; card still in \($card.status // "no status")"
                        else "PR #\($pn) is closed; card still in \($card.status // "no status")"
                        end)} ] )
      +
      # An Issue CARD whose issue is no longer open (#707). The mirror of
      # `issue_no_card`: that flags an open issue with no card, this flags a
      # card whose issue has closed or been deleted. `items` iterates only the
      # open-issue list, so the card of a closed issue -- which should have
      # moved to Done -- is reconciled by nothing and sits in whatever column
      # it held. `Done` cards are the expected resting state and are not flagged.
      ( [ $issues[].number ] as $open_issue_nums
        | [ $board.items[]?
            | select((.content.type? // "Issue") == "Issue")
            | . as $card
            | (.content.number?) as $in
            | select($in != null)
            | select(($open_issue_nums | index($in)) == null)
            | select(($card.status // "") != "Done")
            | {kind: "stale_issue_card",
               ref: ($in | tostring),
               detail: "issue #\($in) is closed; card still in \($card.status // "no status")"} ] )
    )
  }
'
