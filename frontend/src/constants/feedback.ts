// Feedback signals, saved events, and event report reasons.
// .js extensions required: Cloudflare Pages Functions import constants as unbundled ESM.

import { REPORT_REASONS } from '../_generated/sharedConstants.js';

// ─── Reports (event_reports, issue #128) ────────────────────────────────────
// The reasons, in the form's order, and REPORT_REASON_OTHER are cross-stack:
// _generated/sharedConstants.ts. Labels and descriptions come from the
// report_reason_<slug>(_description) i18n keys.
export const REPORT_REASON_OPTIONS: readonly { value: string; labelKey: string; descriptionKey: string }[] =
  REPORT_REASONS.map((value) => ({
    value,
    labelKey: `report_reason_${value}`,
    descriptionKey: `report_reason_${value}_description`,
  }));
// Built once — avoids a linear REPORT_REASON_OPTIONS.find() per call (Big-O
// audit #5, item 3.4), mirroring PERSONAS_BY_SLUG/LOCALES_BY_CODE.
export const REPORT_REASONS_BY_VALUE: Map<string, (typeof REPORT_REASON_OPTIONS)[number]> = new Map(
  REPORT_REASON_OPTIONS.map((r) => [r.value, r]),
);
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
// The tab /saved opens on, left out of the URL; `?signal=` names any other tab.
export const SAVED_DEFAULT_SIGNAL: Signal = 'bookmark';

// ─── Saved Events (route-local tab config, mirrors SORT_OPTIONS/DATE_PRESETS) ─
export const SAVED_TABS: { value: Signal; labelKey: string }[] = [
  { value: 'bookmark', labelKey: 'saved_tab_bookmark' },
  { value: 'like', labelKey: 'saved_tab_like' },
  { value: 'dislike', labelKey: 'saved_tab_dislike' },
];

// Feedback-signal filter query-param name for the Saved Events feed
// (values are the Signal union: 'bookmark' | 'like' | 'dislike').
export const SIGNAL_PARAM = 'signal';
