# Data Model

What's in here: what the key tables' columns mean and who writes them, the `events` triggers and indexes, migrations, connection pooling and serializer rules.

`app/models/models.py` is the full column list. This doc covers what reading it won't tell you: meaning, authority, triggers and gotchas.

## Key Database Tables

### Users and Sign-In

- **`users.email_verified` flips true on the first successful magic-link verification.** It gates `build_daily_feeds` and `send_daily_digests`. See [security.md](security.md)'s Email Verification Gate section.
- **`users.email_digest_opt_in` gates the daily digest send, and new users start `false`.** The onboarding checkbox sends the choice with `POST /onboarding/persona`. Rows from before migration 0059 kept `true`. `users.locale` is one of `et`, `en` and `ru`.
- **`users.email_ad_consent` is the send-time gate for the digest's Sponsored slot, and starts `false`.** `email_ad_consent_version` holds the wording version agreed to. Only `app/email/consent.py` writes them, and every unsubscribe route withdraws consent through `set_digest_subscription`.
- **`email_ad_consent_log` is append-only, one row per grant or withdrawal.** It stores the source and locale. Its `user_id` FK cascades, so `log_account_deletion` logs before the account goes. Startup resets older wording versions to off, logged as `wording_change`.
- **`session_token_version` is bumped to revoke every session** of a user, or of an organizer on `organizers`. See [security.md](security.md)'s Session Revocation section.
- **`auth_magic_links` rows are one-use and store only a sha256 `token_hash`.** A non-null `pending_google_sub` marks a link that confirms a pending Google link instead of starting a session ([ADR 0002](adr/0002-google-sign-in-oauth-pkce.md)). There is no second token type.

### Linked Identities

- **`user_identities` maps an account to an external sign-in identity** by `provider` and `provider_sub`. `provider` is a data value such as `"google"`, not hardcoded. The `user_id` FK cascades on delete, and a plain index on it serves the "which providers are linked" lookup.
- **`UniqueConstraint("provider", "provider_sub")` is per table, not global.** One Google account may hold both a `User` and an `Organizer` row, and the two never merge. This mirrors the split between `auth_magic_links` and `organizer_magic_links`.
- **There is deliberately no `email` column.** The address lives on `users.email` or `organizers.email`, and an identity is keyed only by its stable `sub`.

### Organizers

- **`organizers` holds the self-service portal account;** see [organizer-portal.md](organizer-portal.md). `organizer_magic_links` and `organizer_identities` mirror the consumer tables for this auth track, constraints and all.
- **`organizers.verified` (default false) gates auto-publish.** An admin's first `POST /admin/submissions/{id}/approve` flips it true.
- **`organizers.email_verified_at` is stamped on the first sign-in by any path** (migration 0057). The weekly cleanup never prunes an organizer that has it. See [backend-ops.md](backend-ops.md)'s Data Retention & Cleanup section.
- **A blank `organizers.name` is stored as `NULL`.**
- **Neither account table has a theme column.** Migration 0040 dropped `theme_preference` ([ADR 0003](adr/0003-device-theme-with-expiring-override.md)).
- **`organizer_image_uploads` exists only to enforce `ORGANIZER_DAILY_IMAGE_UPLOAD_CAP`.** An upload can precede any submission, so the count can't come from `Event.created_at` the way the submission cap's does. Rows are never read back and never swept.

### Personas

- **`personas` holds the 9 static personas.** Each has a JSONB affinity vector and display names in et, en and ru.
- **`user_personas.weight` comes from the pick's rank.** Onboarding is a ranked multi-pick of up to `PERSONA_MAX_SELECTABLE` (3). `PERSONA_RANK_WEIGHTS` gives 1.0 / 0.4 / 0.2 by position, so the first pick leads (`app/routers/onboarding.py`).

### Ingestion Tables

| Table | Holds |
|---|---|
| `sources` | the ingestion source registry |
| `raw_events` | each source payload, as JSONB |
| `event_sources` | links from an event to a source and its `external_id` |
| `ingestion_runs` | one row per adapter run, with counts and `error` |
| `llm_calls` | the per-call LLM log and content-hash cache |
| `raw_inbound_emails` | stored newsletter-inbound webhook payloads |

- **A unique index on `event_sources(source_id, external_id)` makes ingestion idempotent** at the DB level (migration 0007).
- **`ingestion_runs.error` comes from the propagated adapter exception.** See [pipeline.md](pipeline.md)'s Pipeline Code Rules section.
- **The dedup, classification and venue-extract caches key off `llm_calls.content_hash`.** Rows are pruned after `LLM_CALLS_RETENTION_DAYS`; see [backend-ops.md](backend-ops.md)'s Data Retention & Cleanup section.
- **`raw_inbound_emails` backs a dormant path.** See [pipeline.md](pipeline.md)'s Newsletter Inbound section.

### Events

`events` holds one normalized row per occurrence. [pipeline.md](pipeline.md) covers the stages that write it.

| Column | Meaning |
|---|---|
| `title_orig`, `description_orig` | source text |
| `important_info` | ticket and access notes scraped from HTML-listing sources |
| `title_localized`, `description_localized`, `important_info_localized` | JSONB `{locale: html}` |
| `price_hint` | raw price text from ingestion, fed to classification |
| `price_min`, `price_max`, `currency` | parsed from `price_hint` by classification |
| `has_free_tier` | a paid event that also offers a free, companion or member tier |
| `venue_name`, `venue_address` | `NULL` when `venue_id` is set |
| `venue_id` | nullable FK → `venues`, organizer submissions only |
| `lat`, `lng` | backfilled by the geocoding job when missing |
| `status` | `draft` → `classified` → `published` or `cancelled` |
| `cancellation_reason` | one of `VALID_EVENT_CANCELLATION_REASONS` |
| `is_explicit` | NSFW filter flag |
| `is_non_event` | gift card, merch or webinar; blocks the publish gate |
| `is_out_of_area` | the LLM's `in_target_city` signal; blocks the publish gate |
| `detail_refetched_at`, `detail_refetch_count` | detail-refetch sync bookkeeping |
| `geocode_attempted_at` | geocoding backfill cooldown |
| `venue_extract_attempted_at` | venue-name extract cooldown (migration 0056) |
| `source_gone_since` | first time the detail-refetch saw the source page gone, cleared on a later successful fetch (migration 0058) |
| `submitted_by_organizer_id` | FK → `organizers`, indexed |
| `needs_review` | flags the admin review queue; partial index on true |
| `pinned_fields` | JSONB array of fields a claim has pinned |
| `promotion_restriction` | content-policy assessment for Promotions; `NULL` is unassessed (migration 0060) |
| `series_key` | DB-maintained series key (migration 0052) |
| `dedup_group_id` | the event's dedup group |
| `updated_at` | trigger-maintained change marker |

- **`published` is set by the publish gate, never directly by classification.** See [pipeline.md](pipeline.md)'s Publish Gate section.
- **Only the manual retract and takedown paths and the detail-refetch source-gone cancel set `cancellation_reason`:** `organizer_retract`, `admin_retract`, `report_takedown` and `source_gone`. Pipeline cancellations, such as `classify_pending`'s ended-draft sweep, leave it `NULL`. So do rows cancelled before the column existed.
- **`has_free_tier` is OR-merged across sources.** See [pipeline.md](pipeline.md)'s Prices section.
- **The `*_localized` columns have three writers:** per-locale page fetches at ingest, the organizer form's per-locale fields, and the detail-refetch backfill of missing locales. A source that concatenates several languages in one field is stored as-is, unsplit.
- **`submitted_by_organizer_id` and `needs_review` feed `GET /admin/submissions`.** See [organizer-portal.md](organizer-portal.md)'s Trust Gating and Review section.

#### The `updated_at` Trigger

- **`trg_events_set_updated_at` bumps `updated_at` only when a tracked column actually changes** (migration 0027). The bookkeeping columns stay untracked, so routine sync passes don't move the prerender's change marker. See [seo.md](seo.md)'s Change Detection and Copy-Forward section.
- **The trigger compares an explicit `ROW(...)` column list frozen in migration 0050.** `backend/tests/test_events_trigger_columns.py` checks it covers every `events` column outside its `UNTRACKED` set.
- **Adding an `events` column needs a migration that re-issues `trg_events_set_updated_at` with it.** Otherwise edits to that column never move `updated_at`, and the prerender keeps serving the stale page. Add the column to the test's expectations in the same change.

#### Series Key

- **`events.series_key` is maintained by the database, never written by the app** (`server_default=FetchedValue()`). It holds the serialized `event_series_key()`: `normalized_title(title_orig)`, then `\x1f`, then the normalized resolved venue name. That name is a linked `Venue`'s `coalesce(name_en, name)`, else `venue_name`.
- **Two triggers keep it current, both calling `event_series_key_sql()`,** the SQL mirror of `normalized_title()`. A `BEFORE INSERT/UPDATE OF title_orig, venue_name, venue_id` trigger runs on `events`. An `AFTER UPDATE OF name, name_en` trigger on `venues` refreshes linked events on a rename.
- **A btree index on `(series_key, starts_at)` serves `app/claims/pinning.py`** (`bulk_resolve_series_events`, `clear_claim_pins`). Dedup, dormancy, target resolution and the Daily 5 still compute keys in Python from loaded rows.
- **Known divergence: SQL `lower()` follows the DB locale.** It differs from Python on exotic case folds such as Turkish dotted `İ`. A miss there only means no series-claim match.
- **`backend/tests/test_events_series_key_sql.py` asserts parity and rename propagation** against a real migrated Postgres. It skips when none is reachable.

#### Claim Search Indexes

- **Two pg_trgm GIN expression indexes back claim discovery** (migration 0051). `ix_events_search_text_trgm` covers `app/constants/events.py::EVENT_SEARCH_TEXT_SQL`: `title_orig` plus every locale's `title_localized`. It serves `GET /organizer/claims/search`, which therefore matches a title in any locale.
- **`ix_events_url_trgm` serves the domain `ILIKE` in `GET /organizer/claims/suggestions`.**
- **The query side must match the index expression textually.** `app/routers/organizer_claims.py::claim_search_text()` builds it, and `backend/tests/test_claim_search_indexes.py` guards drift.
- **They are expression indexes, not columns,** so the `updated_at` trigger's column list is untouched.

#### Pinned Fields

- **`events.pinned_fields` lists the fields a claim has pinned against overwrite** by ingestion and detail-refetch. It defaults to `[]`. A per-locale text field pins one locale with a `"<field>:<locale>"` entry.
- **Price fields never take part:** `price_min`, `price_max`, `currency` and `has_free_tier`.
- **The claim-editing surface writes it** (`app/routers/organizer_claim_edits.py`, `app/claims/pinning.py`). A Dormant claim's pins count as absent. See [pipeline.md](pipeline.md)'s Localized Text Backfill section for how the refetch honors them.

### Classifications

- **`event_classifications` holds the LLM's output per event:** `categories[]`, `vibes[]`, `quality_score`, three `why_go_bullets`, `why_go_localized` (JSONB `{locale: [bullets]}`), `language_detected` and `model_used`.

### Feedback and Feeds

`user_event_feedback` holds two signal classes with different row rules. Keep them split: a single upsert-by-(user, event) rule would let a ticket click overwrite a bookmark.

- **Preference signals keep current state, one row per (user, event).** These are like, dislike and bookmark (`PREFERENCE_SIGNALS`), enforced by a partial unique index (migration 0019). `POST /feedback` upserts and `DELETE /feedback/{event_id}` removes. `GET /feedback/events?signal=` reads them for the Saved Events page.
- **Passive signals append, at most one row per (user, event, signal, UTC day).** These are `view` and `click_external`, the rest of `VALID_SIGNALS`, kept for page-view and ticket-click analytics. A partial unique index on the UTC date enforces the cap (`uq_user_event_feedback_passive_signal_day`, migration 0055).
- **`POST /feedback` inserts passive rows `ON CONFLICT DO NOTHING`**, so a client spamming the endpoint can't grow the table. Ranking reads only like and dislike rows, so the cap changes no score.
- **`daily_feeds` stores each user's Daily 5** as `user_id`, `feed_date` and a `BigInteger[]` of `event_ids`. The Sponsored slot is stored separately in `daily_sponsored_slots`.
- **There is no score cache.** Migration 0053 dropped `user_event_scores`, and `build_daily_feeds` recomputes scores every run. So a feedback or persona change needs no invalidation. See [pipeline.md](pipeline.md)'s Ranking section.

### Saved Venues

`venues` holds an organizer's reusable venues, picked across submissions in `frontend/src/components/VenuePicker/`. CRUD lives in `app/routers/organizer_venues.py`, scoped to `get_current_organizer`.

- **Names are per-locale columns: `name`, `name_en` and `name_ru`.** That follows the `personas` pattern, not the `events` JSONB pattern. `address` is a single non-localized column, since street names don't translate.
- **`lat` and `lng` come from the geocoding job's venue pass,** which then copies them onto linked events. See [pipeline.md](pipeline.md)'s Geocoding Backfill section. `venues.geocode_attempted_at` is the venue's own cooldown, separate from the event's.
- **`price_min`, `price_max` and `currency` are copy-in defaults only.** Once copied onto an event, the event's values are authoritative.
- **`deleted_at` is a soft delete.** It hides the venue from `GET /organizer/venues` and never touches events that already reference it.
- **Update and delete return 404, not 403, on another organizer's venue,** matching `app/routers/organizer_events.py`.
- **Editing any address field clears `lat`, `lng` and `geocode_attempted_at` synchronously,** which forces re-resolution.
- **A rename re-moderates every linked event,** because events show the venue name at read time. `app/routers/utils.py::remoderate_venue_linked_events` re-applies the explicit and non-event flags in one query. A newly flagged published event drops to `classified`, and every linked live event gets `needs_review`.
- **`ORGANIZER_DAILY_VENUE_CREATION_CAP` caps daily venue creation** with the same soft count-then-insert as the other organizer caps.

### Publishers and Claims

- **A `publishers` row is the real-world entity a Publisher claim is granted against.** `external_id` is unique with `source_id`: one row per Fienta organizer id or Piletilevi promoter id. The single KUMU/Estonia Concert Hall row has a `NULL` `external_id`. `status` is `active` or `retired`. See `CONTEXT.md`'s Event Claiming glossary.
- **`event_sources.publisher_id` links a listing to its resolved Publisher** (nullable, `ON DELETE SET NULL`). `event_sources.publisher_resolve_attempted_at` is the backfill's retry cooldown for listings the live Fienta re-query couldn't resolve.
- **Publisher rows and `publisher_id` stamps have several writers:** the Fienta organizer sync, ingest, the 6-hourly backfill and, for Piletilevi, claim time. See [pipeline.md](pipeline.md)'s Publisher Mirroring and Publisher Backfill sections.
- **A `claims` row is an organizer's claim over a Publisher or an event series.** `kind` (`publisher` or `series`) is the polymorphic tag. A `publisher` claim sets `publisher_id`. A `series` claim sets `event_series_key` to the serialized `"<normalized_title>\x1f<normalized_venue>"`.
- **A stored `revoked` always means a declined pending claim,** and the API serializes it as `declined`. An admin revoke of an approved claim deletes the row outright. `VALID_CLAIM_STATUSES` lists the stored values.
- **The expiry sweep clocks off `last_checked_at`, not `created_at`.** Creation and every recheck bump it.
- **Partial unique indexes on `publisher_id` and `event_series_key` cover approved claims only** (migration 0048, [ADR 0004](adr/0004-claim-eligibility-tightening.md)). Several pending claims can coexist on one target.
- **`claim_edit_attempts` gets a row for every save on the claim-editing surface,** successful or not. It counts against `ORGANIZER_DAILY_CLAIM_EDIT_CAP`, scaled by covered-event count in `app/claims/pinning.py::scaled_claim_edit_cap`.

| `claims` column | Meaning |
|---|---|
| `verification_mechanism` | one of `VALID_CLAIM_VERIFICATION_MECHANISMS` |
| `proof_token` | system-generated, reused by every recheck |
| `verification_domain` | DNS-TXT target; `NULL` for token and admin-review mechanisms |
| `verification_contact` | the Piletilevi promoter mailbox a `piletilevi_mailbox` check compared against, shown to the admin |
| `justification` | required for `series`, enforced in `app/claims/lifecycle.py` |
| `resolved_at` | set once `status` leaves `pending` |
| `dormant` | set by `app/dedup/rules.py::resolve_claim_dormancy()`; see [organizer-portal.md](organizer-portal.md)'s Dormant Claims section |

### Promotions

`promotions` holds one row per sold or granted Promotion window. `app/promotions/` owns the logic and never imports from `app/routers/utils.py`. See `CONTEXT.md`'s Promotions glossary.

- **`status` is commercial only:** `unpaid`, `paid`, `ended_early` or `void`. Scheduled, live and finished are computed from the window and today's Tallinn date by `app/promotions/windows.py::promotion_state()`, never stored.
- **`start_date` and `end_date` are inclusive Tallinn dates,** 3 to 14 days long, starting tomorrow at the earliest. They end on or before the event's last Tallinn day. `days` is stored beside them.
- **A complimentary grant is created `paid` at `net_price_cents = 0`** with a required `complimentary_note`. A priced grant stores the net price and the `vat_rate_percent` in force at sale, so a later rate change never rewrites it.
- **`organizer_id` is the owner resolved at grant time** by `app/promotions/owners.py::resolve_owner_ids()`: the submitter, or the holder of an approved, non-dormant claim. It costs two queries for any number of events.
- **The advertiser name and registry code are snapshots,** prefilled from the Organizer name. The caption names them, so a later Organizer rename must not change a running Promotion.
- **`invoice_reference` uses the `ER-M-` series with `invoice_source = 'manual'`.** `granted_by` is `admin` for a direct grant. There is no admin id because there is no admins table (ADR 0001).
- **An `unpaid` or `paid` row holds every day of its window against the cap of 5,** paused days included. `void` releases them all. Back-to-back windows on one event are allowed; overlap is not.
- **Every grant first takes `pg_advisory_xact_lock` (`PROMOTION_CAP_LOCK_KEY`) in `app/promotions/cap.py::lock_cap()`.** The cap check and insert then run in one transaction, so two concurrent grants can't both take the last day. The lock releases on commit.
- **`promotion_daily_stats` holds one row per Promotion per Tallinn day,** unique on `(promotion_id, day)` and never pruned (migration 0061). Columns: `gate_outcome`, `gate_reason`, and the counts `explore_served`, `daily5_placed`, `digest_sent`, `web_opens`, `digest_opens`, `slot_dislikes`. Counts only, no viewer identifiers. See [pipeline.md](pipeline.md) for the writers.
- **Starting or ending a Promotion never touches `events.updated_at`.** `events.promotion_restriction` is deliberately outside the `updated_at` trigger's column list.
- **`promotions.daily5_reach` is the Daily 5 reach** (migration 0063): NULL until the nightly build computes it, then frozen after the window ends.
- **`daily_sponsored_slots` holds one row per user per Tallinn day** (migration 0063), unique on `(user_id, slot_date)`. It stores the Daily 5 Sponsored slot apart from `daily_feeds`. Columns: `promotion_id` (NULL when a swap found nothing left), `is_swap` and `replaced_promotion_id`. It cascades with the user and is pruned on `DAILY_FEEDS_RETENTION_DAYS`.
- **Lifecycle commands live in `app/promotions/lifecycle.py`.** Each takes the cap lock, then a `FOR UPDATE` lock on the row, so it serializes against grants and other commands. Only `unpaid -> paid`, `unpaid -> void` and `paid -> ended_early` change `status`.
- **A Stripe refund holds no lock during the network call.** It commits first and re-locks after. A card-paid Promotion's dates cannot be edited, because the price charged caps every refund.
- **Mark paid is allowed while today (Tallinn) is before `start_date`.**
- **Edit before the start date rechecks window, overlap and cap against the other Promotions** (the row never collides with itself) and recomputes `days` and `net_price_cents`.
- **While live, edit only moves `end_date` earlier and never before today.** The price paid stays on the row, and a refund is recorded separately. A finished, ended or void row is not editable.
- **Re-point needs the same owner and the same dedup group** (`dedup_group_id`, or the event's own id when it has none). The window must still end on or before the target's last day and not overlap its Promotions.
- **End early and void store the admin's reason in `end_note`** (`end_reason = admin`) and stamp `ended_at`. Leaving the holding statuses releases every cap day at once, and the fill gate stops serving the row. The Organizer is emailed the reason in their locale by `app/email/promotion_notice.py` after commit, best-effort.
- **A refund is cumulative in `refunded_cents` (gross) with its notes in `refund_note`.** It needs a paid, non-complimentary row (live or ended early) and cannot exceed net plus VAT.
- **A Restriction clearance is four columns on `promotions`:** `restriction_cleared`, `restriction_clearance_by`, `restriction_clearance_note`, `restriction_cleared_at` (migration 0065). It covers only the restriction it names. A grant of a restricted event needs the checkbox and a note, and `POST .../{id}/clear-restriction` clears a newly flagged one.
- **`promotion_snapshots` is append-only and never pruned.** `app/promotions/snapshots.py::take_snapshot()` stores the title in et/en/ru, a 300-character description excerpt, image URL, venue, event dates, the Promotion's dates and net price, and the caption text (`REKLAAM · {advertiser}`).
- **A snapshot's `trigger` is `grant`, `mark_paid`, `edit` or `repoint`.** `grant` is a complimentary grant, which is born paid. A priced grant takes none until it is paid, and every edit takes one, scheduled or live.
- **`promotion_requests` holds an Organizer's request** (migration 0066): event, Organizer, window, advertiser name and registry code, billing email, note, `status`, `decline_reason`, `resolved_by`, the terms version and time. A partial unique index allows one `pending` row per event.
- **`status` is `pending`, `granted`, `declined`, `withdrawn` or `expired`.** Granting sets `promotions.source_request_id` in the same transaction.
- **Later tickets add the Stripe, attestation and checkout columns.**

### Moderation and Audit

- **`event_reports` holds user-filed content reports from `POST /reports`.** Admins resolve them or take the event down through `/admin/reports`; a takedown cancels the event with `cancellation_reason = report_takedown`. See `CONTEXT.md`'s Content Moderation glossary.
- **`event_reports.is_illegal_allegation` is legal-sensitive.** It is one reason `/admin/reports` is session-only.
- **`admin_actions` is a durable audit row per console action,** `promotion_grant`, `promotion_mark_paid`, `promotion_edit`, `promotion_repoint`, `promotion_end`, `promotion_void`, `promotion_refund`, `promotion_request_grant` and `promotion_request_decline` included (the request audit target is the request id), written by `log_admin_action()` in the same transaction as the mutation. See [backend-ops.md](backend-ops.md)'s Audit Logging section.
- **Card checkout adds columns to `promotions` and two tables** (migration 0067). The columns hold the Stripe customer, session, payment intent and invoice ids, `checkout_expires_at`, `invoice_url`, and the content-policy and Organizer-terms acceptance times and versions. `invoice_source = stripe` marks a card-paid row.
- **`stripe_customers` maps `(organizer_id, registry_code)` to a Stripe customer id,** so a repeat checkout reuses it. Its `billing_email` and `legal_name` (migration 0068) hold what Stripe last got, and a repeat checkout updates the Customer only when they differ; NULL on older rows means one update. `processed_stripe_events` holds the webhook event ids that make a replay a no-op.
- **The boot-time `assert_schema_at_head` guard exists because of this table.** Its migration (0030) went unapplied in production, and every audited admin action returned 500.

## Migrations

- **Chain `down_revision` to the previous revision**, and keep each migration small and reversible. CI round-trips the whole chain and runs `alembic check` (see `docs/backend-ops.md`'s CI section).
- **Before creating a unique index, add a defensive `DELETE`** that keeps the smallest `id` per key. Historical duplicates exist even where the application now prevents them; `event_sources(source_id, external_id)` in `0007` was the first case.

## Connection Pooling

- **`app/db.py` sets `pool_pre_ping=True` and `pool_recycle=DB_POOL_RECYCLE_SECONDS`** (280s, under Neon's 5-minute idle suspend). The pool then never hands out a connection the server has already dropped.

## Serializer Rules

- **Resolve venue fields through `app/events/venue.py`:** `resolve_venue_name()`, `resolve_venue_address()` and `resolve_venue_coords()`. A venue-linked event leaves `venue_name`/`venue_address` NULL, so a serializer that reads the columns directly shows a blank venue.
