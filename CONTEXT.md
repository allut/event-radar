# What's on Radar

AI-powered event discovery for Tallinn. This glossary pins the project's
domain language so code, issues, and docs use one word per concept.

## Authentication

**Magic link**:
The single-use, short-lived link emailed to an address to prove the recipient
controls it. Proves control of an address; it is not itself a session.
_Avoid_: login link, verification link, OTP

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
