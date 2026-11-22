# The ONE declaration of how a PR body links to an issue.
#
# Consumers: scripts/backlog-digest.sh (both its merged-PR and open-PR scans)
# and scripts/check-pr-linkage.sh (the CI gate, #828). Load with
# `jq -L scripts/lib 'include "pr-linkage"; ...'`. Before #828 the regex lived
# as two hand-synchronised copies inside the digest, and fixing only one of
# them is how PR #684 shipped.

# Inline-code spans carry EXAMPLES, never linkage declarations, so a `#N`
# inside backticks must not associate a PR with an issue: PR #679 explained its
# own fix with the literal line `- Blocked by #100 -- part of #409` and that
# example bounced issue #409 to In Verification.
def strip_code_spans: gsub("`[^`]*`"; "");

# FIX verbs -- the PR says it fixes the issue (#907). `Resolves-on-release` is
# the fix verb for every PR short of graduation: GitHub does not auto-close on
# it, so the no-auto-close rule holds, yet the board can tell the fix from a PR
# that only mentions the issue. The closing verbs are fix verbs too, used only
# on the graduation PR. A merged FIX reference is the only thing that moves an
# issue to In Verification or makes it a release close candidate: a CI fix
# triggered by an issue's failed analysis (#795 on #791), or a fix for one
# issue found while analysing another (#899 on #880), says `Refs` instead.
def fix_verbs: "resolves-on-release|fixes|closes|resolves";

# WORK verbs -- the fix verbs plus the related-or-partial spellings (`Refs`,
# `Part of`, `Tracks`, `tracking`). Any of them keeps a PR visible on its
# issue: an open one drives In Progress / In Review, a merged one is listed in
# `merged_prs` (#652). Deliberately NOT bare `#N`: a body can name issues
# without working on them ("Related: #a, #b", "until #456 is resolved"), and
# that pulled shipped issues back to In Progress (#721).
def work_verbs: fix_verbs + "|refs|part of|tracking|tracks";

# `\b` before the verb keeps it from matching a verb-shaped SUBSTRING
# ("counterpart of #6", "encloses #6"); `(?<!not )` drops a negated "Not part
# of #N". The `#N` side is bounded by integer equality at the call site, so
# `#2409` cannot match issue 409.
def _refs_by($verbs):
  [ (. // "")
    | strip_code_spans
    | scan("(?i)(?<!not )\\b(?:" + $verbs + ") #([0-9]+)")
    | .[0] | tonumber ];

def fix_refs: _refs_by(fix_verbs);
def linkage_refs: _refs_by(work_verbs);
