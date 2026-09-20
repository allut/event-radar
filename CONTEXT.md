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
The authentication track for the operator console. Password + required TOTP
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
when that identity resolves. A Piletilevi listing whose organizer field
doesn't resolve has no Publisher; see Series claim. Distinct from
`Organizer` (the portal account that holds a claim) and `Venue` (an
organizer's saved-venue directory) — a Publisher is neither.
_Avoid_: organizer (source sense), source organizer, feed organizer

**Publisher claim**:
A claim granted against a Publisher, covering every event traced back to
that entity across ingestion runs.
_Avoid_: organizer claim, source claim

**Series claim**:
A Piletilevi claim granted against an `event_series_key` (normalized title +
lowercased venue) instead of a resolved entity — the fallback for a listing
whose promoter identity doesn't resolve to a Publisher. Where it does
resolve, a Publisher claim applies instead (see Publisher). Covers every
past and future event sharing that series key, reusing the grouping series
cooldown already uses.
_Avoid_: listing claim, recurrence claim, per-event claim

**Trusted claimant**:
An organizer whose Series claims auto-grant without a fresh admin review,
earned by having one prior claim of any kind admin-approved — a Publisher
claim on KUMU/Estonia Concert Hall, or an earlier Series claim — never by an
automated Fienta claim, which carries no admin judgment to build on.
Revoking any of that organizer's claims strips this status, and a revoked
claim is removed from the count that granted it.
_Avoid_: verified claimant, trusted organizer (collides with
`Organizer.verified`, a permanently separate submission-trust track per #385)

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
