// Admin console: pipeline triggers, tabs, labels, queue page sizes.
// .js extensions required: Cloudflare Pages Functions import constants as unbundled ESM.

import { type ContentMarkerState } from './core.js';

// /admin/pipeline (issue #159) is desktop-only — below this it shows a
// "come back at a desk" gate instead of the trigger console.
export const ADMIN_DESKTOP_BREAKPOINT_PX = 1024;

export const ADMIN_NOTE_TEXTAREA_ROWS = 3;

// PageState message while an admin list or detail loads.
export const ADMIN_LOADING_LABEL = 'Loading…';

// Queue page sizes (ADMIN_*_PAGE_SIZE) are cross-stack: _generated/sharedConstants.ts.
// URL (and API) param carrying the Claims tab: `approved` for Granted, omitted for pending.
export const ADMIN_CLAIMS_TAB_PARAM = 'status';

// Query-param name for the report-notification email's deep link into
// AdminReports — carries the reported event's id so the matching row's
// detail panel auto-opens on load.
export const ADMIN_REPORTS_PARAM = {
  report: 'report',
} as const;

// AdminEventDetail's tab strip — same no-i18n exemption as ADMIN_NAV_ITEMS.
export const ADMIN_EVENT_DETAIL_TABS = ['Overview', 'Classification', 'Dedup & reports', 'Promotions', 'Raw payload'] as const;

// title/description/important_info — the fields markerState() counts to
// decide 'matched' vs 'partial' vs 'empty' translation coverage per locale.
export const ADMIN_TRANSLATABLE_FIELD_COUNT = 3;

// AdminEventDetail's content-locale switch (SegmentedControl marker labels) —
// plain English, same no-i18n exemption as ADMIN_NAV_ITEMS.
export const ADMIN_CONTENT_LANG_MARKER_LABELS: Record<ContentMarkerState, string> = {
  empty: 'not translated',
  partial: 'partially translated',
  matched: 'translated',
};

// Shared "open full details" link on AdminSubmissions/AdminReports detail
// panes (AdminQueue.module.css's .queueDetailLink) — same no-i18n exemption.
export const ADMIN_QUEUE_DETAIL_LINK_LABEL = 'Open full details →';

// Shown on page 1 of Admin Reports when an email deep link (?report=<id>)
// names a report that is no longer in the queue — same no-i18n exemption.
// `{id}` is the event id.
export const ADMIN_REPORT_PROMOTED_LABEL = 'Promoted';
export const ADMIN_REPORT_RESOLVED_NOTICE = 'Report #{id} was already resolved. Showing the start of the queue.';
export const ADMIN_REPORT_RESOLVED_LINK_LABEL = 'Open event #{id}';

// Fallback error toast copy shared across admin mutations that don't get a
// server-provided message — same no-i18n exemption as the rest of admin.
export const ADMIN_GENERIC_ERROR = 'Something went wrong. Try again.';

// AdminShell's foot-area theme toggle (issue #255) — same {value, label}
// shape as THEME_OPTIONS (theme.ts), but plain-English labels: same no-i18n
// exemption as ADMIN_NAV_ITEMS, since the admin console has no locale.
// Two options only (ADR 0003) — device-following is the default state, not
// a picker entry.
export const ADMIN_THEME_OPTIONS = [
  { value: 'light', label: 'Light' },
  { value: 'dark', label: 'Dark' },
] as const;

// /admin/pipeline (issue #159) — one row per job-trigger endpoint. The admin
// console is English-only/internal, so labels/hints are plain strings, not
// i18n keys (matches AdminReports/AdminSubmissions' own inline copy).
export type AdminTriggerId =
  | 'ingest_all'
  | 'ingest_source'
  | 'dedup'
  | 'classify'
  | 'publish'
  | 'geocode'
  | 'refetch'
  | 'sync_organizers'
  | 'cleanup'
  | 'build_feeds'
  | 'send_digests'
  | 'pipeline_run';

export interface AdminPipelineTrigger {
  id: AdminTriggerId;
  label: string;
  hint: string;
  dryRunCapable?: boolean;
  needsSlug?: boolean;
  /** pipeline_run only — the stage order PipelineRunBreakdown renders through. */
  stages?: string[];
  /** Set only on cleanup/send_digests/pipeline_run (issue #160) — a real
   * (dry_run=false) run of these requires the typed-confirmation modal,
   * naming this endpoint's specific consequence. */
  dangerCopy?: string;
}

export const ADMIN_PIPELINE_TRIGGERS: AdminPipelineTrigger[] = [
  { id: 'ingest_all', label: 'Ingest all sources', hint: 'Pull raw events from every enabled source' },
  { id: 'ingest_source', label: 'Ingest one source', hint: 'Pull raw events from a single source by slug', needsSlug: true },
  { id: 'dedup', label: 'Dedup pass', hint: 'Drain the dedup backlog' },
  { id: 'classify', label: 'Classify', hint: 'LLM classification of pending events' },
  { id: 'publish', label: 'Publish', hint: 'Promote qualifying events to published' },
  { id: 'geocode', label: 'Geocode', hint: 'Backfill lat/lng from venue addresses' },
  { id: 'refetch', label: 'Refetch details', hint: 'Re-fetch source detail pages' },
  { id: 'sync_organizers', label: 'Sync organizers', hint: 'Discover new organizers, flag stale ones' },
  {
    id: 'cleanup',
    label: 'Cleanup',
    hint: 'Prune satellite tables past retention',
    dryRunCapable: true,
    dangerCopy: 'This deletes rows from satellite tables (raw events, feedback, expired sessions, and more). Events themselves are never deleted, but this cannot be undone.',
  },
  { id: 'build_feeds', label: 'Build feeds', hint: 'Build Daily 5 for every active user' },
  {
    id: 'send_digests',
    label: 'Send digests',
    hint: 'Send the daily email digest',
    dryRunCapable: true,
    dangerCopy: 'This sends a real email to every opted-in user right now, not a test send.',
  },
  {
    id: 'pipeline_run',
    label: 'Run full pipeline',
    hint: 'All seven stages in order',
    dryRunCapable: true,
    stages: ['sync_organizers', 'ingest', 'dedup', 'classify', 'publish', 'build_feeds', 'send_digests'],
    dangerCopy: 'This runs the full pipeline end to end, including LLM classification (real spend) and a real digest send to every opted-in user.',
  },
];

// pipeline_run's bespoke stage-by-stage breakdown (PipelineRunBreakdown,
// issue #161) — display label per entry in ADMIN_PIPELINE_TRIGGERS'
// pipeline_run.stages, keyed by the same stage names admin_jobs.py streams.
export const ADMIN_PIPELINE_STAGE_LABELS: Record<string, string> = {
  sync_organizers: 'Sync organizers',
  ingest: 'Ingest',
  dedup: 'Dedup',
  classify: 'Classify',
  publish: 'Publish',
  build_feeds: 'Build feeds',
  send_digests: 'Send digests',
};

// Admin screens are English-only; the shared DatePicker still wants a locale.
export const ADMIN_LOCALE = 'en';
