# Claim eligibility tightens: no fast-track, bounded admin-review expiry, proof preempts assertion

Status: accepted

#409's original claim-flow spec (implemented pre-#425) shipped two decisions
this ADR reverses, plus a duplicate-claim behavior it narrows. Slice 1 of
#425 (#427–#431) found all three unsafe once claims saw real Piletilevi
promoters with no verifiable domain, and real admin turnaround times: a
single prior approval fast-tracking unrelated future claims, a pending claim
with no human resolution deadline, and a race where the first claimant to
land a row — proven or not — permanently locked out every other one.

## Trusted claimant is removed entirely

#409 granted a "Trusted claimant" status to any organizer with one prior
admin-approved claim of any kind, and let that status auto-grant a later
Series claim without fresh admin review. The reasoning at the time was that
an organizer already vetted once shouldn't need re-vetting for an unrelated
target.

That reasoning didn't survive contact with Piletilevi's promoter data:
Series claims exist precisely because a promoter's identity failed to
resolve to anything — there is nothing about that specific target for a
prior unrelated approval to vouch for. Trusted claimant let one verified
relationship (say, a Fienta organizer id) launder trust onto a completely
different, unverified one (a Piletilevi series with no resolvable promoter)
purely because the same account happened to hold both. #428 deletes the
status and its supporting code outright rather than narrowing it further —
every remaining auto-grant path (Fienta token, KUMU/ECH DNS-TXT, Piletilevi
domain DNS-TXT, Piletilevi mailbox match) now checks evidence about the
specific target being claimed, never about the claimant's history.

## Admin-review claims now expire

#409 explicitly chose "an admin-review claim never expires," reasoning that
a claim genuinely waiting on a human shouldn't be penalized for admin
turnaround time. Combined with the pre-#431 uniqueness rule (below), this
meant a single admin-review claim — including a bad-faith or abandoned one —
could lock a Publisher or Series target indefinitely, with no automated
recovery path.

#430 adds `CLAIM_ADMIN_REVIEW_EXPIRY_DAYS` (30 days, vs. the unchanged
7-day `CLAIM_EXPIRY_DAYS` for automated mechanisms), reusing the existing
expiry sweep and its existing notification email rather than building a new
mechanism. The window is deliberately generous — long enough that a genuine
admin backlog isn't itself punished — but it is no longer infinite. This
also covers `piletilevi_mailbox`: that mechanism can auto-grant, but a
claim that instead falls to admin review under it has nothing an organizer
can act on to fix the mismatch (the promoter's published contact and the
organizer's own account email are both outside their control from the
pending screen), so it expires on the same 30-day window as true
`admin_review` claims, not the 7-day one.

## Proof preempts assertion: approved-only uniqueness

#409 rejected two accounts racing to claim the same Publisher or Series "at
the entry surface before a row is inserted" — in practice, a unique
constraint spanning both `pending` and `approved` statuses. That protected
against a literal simultaneous race, but it also meant the *first* claim
filed against a target — proven or not — permanently blocked every later
one, including the actual owner. A junk or mistaken claim that never
resolves (and, pre-#430, never expired) could leave the genuine owner
locked out with a bare `409` and no way to even start proving ownership,
since the proof token lives on the claim row they never got to create.

#431 narrows the constraint to "one *approved* claim per target." Multiple
`pending` claims may now coexist on the same target, each with its own
proof token. The moment any one of them passes automated verification, it
auto-declines every other still-pending claim on that target (with the
existing decline email to each). An attempt against a target that already
has an *approved* claim is unchanged: `409`, support-facing message, no
contest/override flow. The principle: evidence resolves a contested claim,
not arrival order.

## Considered options

- **Narrow Trusted claimant instead of deleting it** (e.g. scope it to the
  same source) — rejected. Every remaining case where it could still fire
  is a case where a real per-target proof mechanism already exists; keeping
  a fallback shortcut around it just reintroduces the laundering problem at
  a smaller radius.
- **Keep admin-review claims non-expiring, add a dashboard staleness flag
  instead** — rejected. A flag an admin has to notice and act on doesn't
  bound how long a target stays locked; an actual expiry does.
- **Reject a second pending claim on a target outright (status quo) and
  instead speed up admin turnaround** — rejected. Turnaround time is an
  operational lever, not a correctness guarantee; a genuine owner shouldn't
  be unable to even start the proof process because of an unrelated
  claimant's still-pending row.
- **First-claim-wins with a manual override endpoint for admins** —
  rejected as strictly more admin work than proof-preempts-assertion for
  the common case (an automated mechanism resolves it with no admin
  involvement at all), while still available in practice via the existing
  admin decline/revoke actions for the cases automation can't settle.

## Consequences

- **A claimant can start proving ownership even with a stale, unrelated
  pending claim already on the target** — the property #409's uniqueness
  rule was blocking as an unwanted side effect, not the property it was
  protecting.
- **`CLAIM_ADMIN_REVIEW_EXPIRY_DAYS` and `CLAIM_EXPIRY_DAYS` must be kept
  distinct in any future claim-flow change** — collapsing them either
  re-introduces punishing genuine admin turnaround (if shortened to 7) or
  re-introduces the unbounded-lock problem (if the automated window is
  lengthened to 30).
- **The migration narrowing the partial unique indexes (0048) is one-way in
  practice**: reverting it without also reintroducing a pre-insert
  duplicate-pending check would silently allow the exact race #409 first
  guarded against.
- **`CONTEXT.md`'s Event Claiming glossary drops Trusted claimant entirely**
  and gains a Proof channel entry — see the glossary itself for the current
  vocabulary.
