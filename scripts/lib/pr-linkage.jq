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

# WORK references only -- the closing verbs plus the no-auto-close spellings
# (`Part of`, `tracking`, `Refs`). The no-auto-close rule forbids `Closes #N`
# on an intermediate PR, but every spelling it leaves still carries a work
# verb, so a beta PR stays visible (#652). Deliberately NOT bare `#N`: a body
# can name issues without working on them ("Related: #a, #b", "until #456 is
# resolved"), and that pulled shipped issues back to In Progress (#721).
#
# `\b` before the verb keeps it from matching a verb-shaped SUBSTRING
# ("counterpart of #6", "encloses #6"); `(?<!not )` drops a negated "Not part
# of #N". The `#N` side is bounded by integer equality at the call site, so
# `#2409` cannot match issue 409.
def linkage_refs:
  [ (. // "")
    | strip_code_spans
    | scan("(?i)(?<!not )\\b(?:fixes|closes|resolves|refs|part of|tracking|tracks) #([0-9]+)")
    | .[0] | tonumber ];
