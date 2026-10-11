// Feedback signals, saved events, and event report reasons.
// .js extensions required: Cloudflare Pages Functions import constants as unbundled ESM.

// ─── Reports (event_reports, issue #128) ────────────────────────────────────
// Mirrors the backend's VALID_REPORT_REASONS order (app/constants/reports.py) — labels/
// descriptions come from the report_reason_<slug>(_description) i18n keys.
export const REPORT_REASON_OTHER = 'other';
export const REPORT_REASONS: { value: string; labelKey: string; descriptionKey: string }[] = [
  { value: 'spam_or_scam', labelKey: 'report_reason_spam_or_scam', descriptionKey: 'report_reason_spam_or_scam_description' },
  { value: 'sexual_or_explicit', labelKey: 'report_reason_sexual_or_explicit', descriptionKey: 'report_reason_sexual_or_explicit_description' },
  { value: 'not_an_event', labelKey: 'report_reason_not_an_event', descriptionKey: 'report_reason_not_an_event_description' },
  { value: 'hateful_or_violent', labelKey: 'report_reason_hateful_or_violent', descriptionKey: 'report_reason_hateful_or_violent_description' },
  { value: 'misleading_info', labelKey: 'report_reason_misleading_info', descriptionKey: 'report_reason_misleading_info_description' },
  { value: 'event_ended_or_cancelled', labelKey: 'report_reason_event_ended_or_cancelled', descriptionKey: 'report_reason_event_ended_or_cancelled_description' },
  { value: 'wrong_location', labelKey: 'report_reason_wrong_location', descriptionKey: 'report_reason_wrong_location_description' },
  { value: REPORT_REASON_OTHER, labelKey: 'report_reason_other', descriptionKey: 'report_reason_other_description' },
];
// Built once — avoids a linear REPORT_REASONS.find() per call (Big-O audit
// #5, item 3.4), mirroring PERSONAS_BY_SLUG/LOCALES_BY_CODE.
export const REPORT_REASONS_BY_VALUE: Map<string, (typeof REPORT_REASONS)[number]> = new Map(
  REPORT_REASONS.map((r) => [r.value, r]),
);
// Mirrors the backend's REPORT_DETAIL_MAX_CHARS (app/constants/reports.py) — client-side
// validation only, the server re-validates and is the real boundary.
export const REPORT_DETAIL_MAX_CHARS = 500;
export const REPORT_DETAIL_TEXTAREA_ROWS = 4;

// ─── Events / feedback ───────────────────────────────────────────────────────
export type Signal = 'like' | 'dislike' | 'bookmark';

export const SIGNAL_CONFIG: Record<Signal, { icon: string }> = {
  like:     { icon: '👍' },
  dislike:  { icon: '👎' },
  bookmark: { icon: '🔖' },
};

// Backend-only feedback signal (shared/app-config.json `signals`) — sent when a
// visitor follows an event's external ticket link.
export const SIGNAL_CLICK_EXTERNAL = 'click_external';

export const SIGNAL_TO_CLASS: Record<Signal, string> = {
  like: 'activeLike',
  dislike: 'activeDislike',
  bookmark: 'activeBookmark',
};

// ─── Saved Events ────────────────────────────────────────────────────────────
export const SAVED_EVENTS_PAGE_SIZE = 24;

// ─── Saved Events (route-local tab config, mirrors SORT_OPTIONS/DATE_PRESETS) ─
export const SAVED_TABS: { value: Signal; labelKey: string }[] = [
  { value: 'bookmark', labelKey: 'saved_tab_bookmark' },
  { value: 'like', labelKey: 'saved_tab_like' },
  { value: 'dislike', labelKey: 'saved_tab_dislike' },
];

// Feedback-signal filter query-param name for the Saved Events feed
// (values are the Signal union: 'bookmark' | 'like' | 'dislike').
export const SIGNAL_PARAM = 'signal';
