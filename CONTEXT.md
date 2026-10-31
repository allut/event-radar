# Event Radar

AI-powered event discovery for Tallinn. This glossary pins the project's
domain language so code, issues, and docs use one word per concept.

## Authentication

**Magic link**:
The single-use, short-lived link emailed to an address to prove the recipient
controls it. Proves control of an address; it is not itself a session.
_Avoid_: login link, verification link, OTP

**Confirmation magic link**:
A magic link sent solely to prove control of an address before an identity
link is created, rather than to start a session. Same mechanism as a magic
link, different purpose.
_Avoid_: linking email, verification email, challenge link

**Provider identity**:
An account held at an external identity provider, named by that provider's
stable subject identifier rather than by its address. The address it reports
may change; the identifier never does.
_Avoid_: social login, OAuth account, Google account

**Identity link**:
The durable binding of one provider identity to one account on one track. A
track's account may hold several; a provider identity may be linked once per
track.
_Avoid_: connected account, linked login, federation

**Session token**:
The signed, self-verifying value that proves an identity for the life of a
session. Carried in an httpOnly cookie and never readable by client code.
_Avoid_: access token, auth token, JWT

**Signed-in hint**:
A client-readable marker that a session token exists in this browser. It
carries no credential value and grants no access on its own.
_Avoid_: auth flag, session flag, client token

**Consumer track**:
The authentication track for people who read the feed. Has its own salts,
tables, and session lifetime.
_Avoid_: user auth, main auth

**Organizer track**:
The authentication track for people who submit events. Structurally mirrors
the consumer track and is never interchangeable with it.
_Avoid_: portal auth, submitter auth

**Admin track**:
The authentication track for the admin console. Password + required TOTP
rather than a magic link, with its own cookie name, path, and lifetime. Never
interchangeable with the consumer or organizer tracks.
_Avoid_: staff auth, ops login, superuser

**Sign out**:
Ends the session on the current device only. Other devices keep their
sessions.
_Avoid_: logout (when the distinction below matters)

**Sign out everywhere**:
Invalidates every session for an identity across all devices, immediately.
_Avoid_: global logout, force logout, revoke all

## Content Moderation

**Report**:
A signed-in user's flag that a specific event's hosted content is
inappropriate, submitted for admin resolution. Distinct from feedback
(preference signals like/dislike/bookmark) and from the organizer post-hoc
review queue (which judges a submitter's trustworthiness, not content).
_Avoid_: flag, complaint, feedback

**Resolve** (a report):
The admin action that closes out an open report, optionally with a
resolution note. Distinct from "review," which is reserved for the
organizer submission queue.
_Avoid_: review, approve, dismiss

## Event Claiming

**Publisher**:
The real-world entity a claim is granted against, resolved per source: one
per Fienta organizer id, the whole source for KUMU and Estonia Concert Hall
(each a single institution, the latter booking several halls under one
feed), or one per Piletilevi promoter id — read from a listing's schema.org
`Event.organizer` and resolved to that promoter's public profile page —
when that identity resolves. A resolved Piletilevi promoter always yields a
Publisher and splits into two tiers by what its public contact channel
proves (see Proof channel): a domain-provable promoter auto-grants the same
DNS-TXT way as KUMU/ECH; a mailbox-provable promoter (contact info with no
verifiable domain) auto-grants only on an exact match to the claimant's own
account email, else falls to admin review. A Piletilevi listing whose
organizer field doesn't resolve at all has no Publisher; see Series claim.
Distinct from `Organizer` (the portal account that holds a claim) and
`Venue` (an organizer's saved-venue directory) — a Publisher is neither.
_Avoid_: organizer (source sense), source organizer, feed organizer

**Proof channel**:
What a resolved Publisher's public contact info actually lets a claim
verify against, not whether the Publisher itself resolved. A working proof
channel is a Fienta token round-trip or a DNS-verifiable domain (KUMU, ECH,
or a domain-provable Piletilevi promoter) — these auto-grant. A resolved
identity with no such channel (a Piletilevi promoter with only a contact
mailbox) falls to a mailbox match against the claimant's account email, and
short of that, to admin review. Absence of a proof channel is not absence
of a Publisher — the two are resolved and verified in separate steps.
_Avoid_: verification method, proof mechanism (collides with
`verification_mechanism`, the stored field name for the specific check run)

**Publisher claim**:
A claim granted against a Publisher, covering every event traced back to
that entity across ingestion runs.
_Avoid_: organizer claim, source claim

**Series claim**:
A Piletilevi claim granted against an `event_series_key` (normalized title +
lowercased venue) instead of a resolved entity — the fallback for a listing
whose promoter identity fails to resolve at all, i.e. neither Piletilevi
Publisher tier applies (see Proof channel). A promoter that resolves to
either tier — domain-provable or mailbox-provable — always yields a
Publisher claim instead, never a Series claim. Covers every past and future
event sharing that series key, reusing the grouping series cooldown already
uses. Always routes to admin review — there is no auto-grant path for it —
and always requires a claim justification (below).
_Avoid_: listing claim, recurrence claim, per-event claim

**Claim justification**:
The non-blank, organizer-supplied reason required to create a Series claim
(#428) — its only claimant-supplied input, since a Series claim carries no
verifiable identity of its own. Stored on the claim and shown to the admin
reviewing it. Not required for, and not shown on, a Publisher claim.
_Avoid_: claim reason, claim note (collides with an admin resolution note)

**Dormant claim**:
An approved claim whose event lost a claimed-vs-claimed dedup collision to a
better-quality duplicate (#418) — its pins stop applying while dormant, but
the row is never deleted or revoked, and `status` (which still gates
duplicate-claim creation) is untouched. Reactivates automatically the next
dedup pass in which its target is canonical again.
_Avoid_: revoked claim, suspended claim, inactive claim

## Operator

**Operator**:
The legal person that runs Event Radar: it sells Promotions, controls the
personal data of consumers and Organizers, and is the party to the Terms and
the Organizer terms. There is exactly one at any time, and every published
identity (imprint, invoices, Privacy notice) names it. A person who signs in to
the admin console is an *admin*, not the Operator.
_Avoid_: owner, company, seller, platform, sole trader

## Discovery

**Daily Five**:
The five events a user is offered each day, chosen for them and rebuilt
daily. A recurring series they've just been shown is set aside unless the day
is short of events. Written *Daily 5* in docs and code; both name the same
thing.
_Avoid_: feed on its own (ambiguous with Explore), picks, top five

## Promotions

**Promotion**:
A placement, sold for a set window, of one event the Organizer owns:
either an event they submitted or one covered by an approved claim that is not
dormant. A Promotion buys Sponsored slots only. It never changes where the
event ranks in any organic list. It is always sold to the Organizer's own
business, never to another business through them. A complimentary Promotion, granted at no
charge, is still a Promotion: it is labelled, rotated and counted exactly like
one that was paid for.
_Avoid_: boost, bump, ad campaign, featured

**Promotion window**:
The whole Tallinn days, first and last included, during which a paid Promotion
may fill Sponsored slots. It never runs past the event's last day. Being inside
its window doesn't guarantee a Promotion shows: if the event stops being
eligible, the Promotion pauses and resumes by itself, and the days it loses are
never added back automatically.
_Avoid_: campaign, flight, run

**Promotion request**:
An Organizer's request for a Promotion on one event they own, with the dates
they want and their own business, which would pay. It is not a Promotion: nothing has
been sold, and it holds no days against the cap. An admin either grants it,
which creates the Promotion (possibly on other dates agreed with the
Organizer), or declines it with a reason. Otherwise it is withdrawn by the
Organizer, or expires once its event can no longer be promoted or its start
date arrives.
_Avoid_: promotion order, booking, pending promotion

**Promotion restriction**:
A kind of event content that may be listed but not promoted without an admin's
review: tobacco, gambling, alcohol-led, political, or a weapons sale. It never
affects whether or where the event lists organically. An admin who grants a
Promotion despite it gives a *Restriction clearance*, which belongs to that
Promotion, not to the event, and covers only the restriction it was given for.
_Avoid_: restricted category, banned event, unpromotable

**Sponsored slot**:
A labelled position on a public surface that shows one Promotion's event as
advertising and names the paying Organizer by the legal name of their business.
It sits beside the organic results,
outside them, and is never counted as one. Its Promotion is chosen by context
(the surface and the viewer's active filters), never by the viewer's tastes; a
viewer's own signals can only exclude a Promotion. When no Promotion is
eligible, the slot collapses and is never filled with something else.
_Avoid_: featured slot, promoted result, ad unit

**Ranking disclosure**:
The public statement of what decides which events can appear and in what order
the organic lists show them, giving the main signals and their relative
importance but never their weights. It also says how Sponsored slots relate to
those lists. It is owed to consumers whether or not any Promotion exists, and
it is part of the Organizer terms, so a change in substance is a change to
those terms.
_Avoid_: ranking page, how-it-works page, transparency page, algorithm

**Email ad consent**:
A digest subscriber's separate, affirmative agreement to receive a Sponsored
slot in their Daily Five email, and in no other email. Subscribing to the
digest is not this consent, and it starts off. It ends when the subscriber
withdraws it, unsubscribes from the digest, or its wording changes in
substance; it never expires on its own.
_Avoid_: marketing consent, sponsored consent, ad opt-in

**Featured** (reserved):
Kept for a future editorial pick that nobody pays for. Never use it for paid
placement.
_Avoid_: featured (for anything a Promotion bought)

## Theming

**Device theme**:
The light-or-dark setting the viewer's platform reports for the surface an
Event Radar page or email is being viewed on. It belongs to the device, not
to an account, and it may change at any time.
_Avoid_: system theme, OS theme, prefers-color-scheme

**Resolved theme**:
The binary light-or-dark actually painted for one view. Always exactly one of
the two; there is no third value to render.
_Avoid_: effective theme, active theme, current theme

**Theme override**:
A viewer's explicit choice of the resolved theme on one browser, held only
until that browser's device theme next changes. It is scoped to the browser
that made it, never to an account, and it expires rather than being cleared
by hand.
_Avoid_: theme preference, theme setting, saved theme
