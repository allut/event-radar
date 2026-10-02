import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { adminApi } from '../../api/client';
import {
  ADMIN_CONTENT_LANG_MARKER_LABELS,
  ADMIN_EVENT_DETAIL_TABS,
  ADMIN_GENERIC_ERROR,
  ADMIN_TRANSLATABLE_FIELD_COUNT,
  API,
  CONTENT_LANG_ORDER,
  QUERY_KEYS,
  ROUTES,
  UI_STATE,
  REPORT_STATUS,
  ADMIN_RESOLUTION_MESSAGES,
  type ContentLang,
  type ContentMarkerState,
} from '../../constants';
import { apiErrorMessage, sanitizeHtml, formatAdminTimestamp, localeLabel, safeUrl } from '../../utils';
import PageState from '../../components/PageState';
import Toast from '../../components/Toast';
import { useToast } from '../../hooks/useToast';
import AdminQueueActionPanel from '../../components/AdminQueueActionPanel';
import SegmentedControl from '../../components/SegmentedControl';
import chipStyles from '../../components/shared/Chip.module.css';
import styles from './AdminEventDetail.module.css';

interface LocaleContent {
  title: string;
  description: string | null;
  important_info: string | null;
  venue_name: string | null;
  translated: {
    title: boolean;
    description: boolean;
    important_info: boolean;
  };
}

interface InspectorEvent {
  id: number;
  slug: string;
  title_orig: string;
  description_orig: string | null;
  important_info: string | null;
  status: string;
  dedup_group_id: number | null;
  submitted_by_organizer_id: number | null;
  needs_review: boolean;
  cancellation_reason: string | null;
  created_at: string;
  updated_at: string;
  detail_refetched_at: string | null;
  starts_at: string;
  ends_at: string | null;
  venue_name: string | null;
  venue_address: string | null;
  lat: number | null;
  lng: number | null;
  url: string | null;
  image_url: string | null;
  price_min: number | null;
  price_max: number | null;
  currency: string | null;
  price_hint: string | null;
  has_free_tier: boolean;
  is_explicit: boolean;
  is_out_of_area: boolean;
  is_non_event: boolean;
  geocode_attempted_at: string | null;
  content_by_locale: Record<string, LocaleContent>;
  classification: {
    categories: string[];
    vibes: string[];
    quality_score: number | null;
    why_go_bullets: string[] | null;
    language_detected: string | null;
    model_used: string | null;
    classified_at: string;
  } | null;
}

interface DedupSibling {
  id: number;
  title: string;
  starts_at: string;
  venue: string | null;
  status: string;
  url: string | null;
  is_explicit: boolean;
}

interface InspectorReport {
  id: number;
  user_id: number;
  reason: string;
  is_illegal_allegation: boolean;
  detail: string | null;
  status: string;
  resolution_note: string | null;
  created_at: string;
  resolved_at: string | null;
}

interface RawEventEntry {
  id: number;
  source_slug: string;
  external_id: string | null;
  payload: unknown;
  fetched_at: string;
  processed_at: string | null;
}

interface InspectorResponse {
  event: InspectorEvent;
  dedup_siblings: DedupSibling[];
  reports: InspectorReport[];
  raw_events: RawEventEntry[];
  in_todays_feed: boolean;
}

type ActionKind = 'resolved' | 'taken_down' | 'approved' | 'retracted';

// One source of truth for each action's endpoint and success toast —
// mutationFn and onSuccess both key off this instead of separately
// enumerating the same 4 kinds.
const ACTION_CONFIG: Record<ActionKind, { path: (id: number) => string; message: string }> = {
  resolved: { path: API.adminReportResolve, message: ADMIN_RESOLUTION_MESSAGES.resolved },
  taken_down: { path: API.adminReportTakedown, message: ADMIN_RESOLUTION_MESSAGES.taken_down },
  approved: { path: API.adminSubmissionApprove, message: ADMIN_RESOLUTION_MESSAGES.approved },
  retracted: { path: API.adminSubmissionRetract, message: ADMIN_RESOLUTION_MESSAGES.retracted },
};

type Tab = (typeof ADMIN_EVENT_DETAIL_TABS)[number];

// Admin event inspector (issue #157, part of #153): deep-linkable detail
// panel for one event regardless of status. Tabbed layout — chosen over a
// stacked single column or a two-column dashboard after a 3-variant
// prototype review (see branch prototype/admin-event-inspector-157).
export default function AdminEventDetail({ eventId }: { eventId: string }) {
  const queryClient = useQueryClient();
  const { toast, showToast } = useToast();
  const [tab, setTab] = useState<Tab>(ADMIN_EVENT_DETAIL_TABS[0]);
  const [note, setNote] = useState('');
  const [contentLang, setContentLang] = useState<ContentLang>(CONTENT_LANG_ORDER[0]);

  const { data, isLoading, isError } = useQuery({
    queryKey: [QUERY_KEYS.adminEventDetail, eventId],
    queryFn: () => adminApi.get<InspectorResponse>(API.adminEventDetail(eventId)),
  });

  const activeContent = data?.event.content_by_locale[contentLang];
  const sanitizedDescription = useMemo(
    () => (activeContent?.description ? sanitizeHtml(activeContent.description) : null),
    [activeContent],
  );
  const sanitizedImportantInfo = useMemo(
    () => (activeContent?.important_info ? sanitizeHtml(activeContent.important_info) : null),
    [activeContent],
  );
  // Pretty-printing every raw scraped payload (routinely tens of KB each) is
  // otherwise redone on every render — including every resolution-note
  // keystroke while the Raw payload tab is open (Big-O audit M5).
  const rawPayloadsById = useMemo(() => {
    const map = new Map<number, string>();
    for (const re of data?.raw_events ?? []) {
      map.set(re.id, JSON.stringify(re.payload, null, 2));
    }
    return map;
  }, [data]);

  // Re-run only when the loaded event/reports change, not on every
  // resolution-note keystroke (Big-O audit #5, item 3.5). Hoisted above the
  // isLoading/isError early returns below — hooks must run unconditionally.
  const openReports = useMemo(
    () => (data?.reports ?? []).filter((r) => r.status === REPORT_STATUS.open),
    [data],
  );
  const langOptions = useMemo(() => {
    if (!data) return [];
    const { event } = data;
    const markerState = (code: ContentLang): ContentMarkerState => {
      if (code === CONTENT_LANG_ORDER[0]) return 'matched';
      const t = event.content_by_locale[code]?.translated;
      if (!t) return 'empty';
      const translatedCount = Number(t.title) + Number(t.description) + Number(t.important_info);
      if (translatedCount === 0) return 'empty';
      if (translatedCount === ADMIN_TRANSLATABLE_FIELD_COUNT) return 'matched';
      return 'partial';
    };
    return CONTENT_LANG_ORDER.map((code) => {
      const state = markerState(code);
      return {
        value: code,
        label: localeLabel(code),
        marker: { state, stateLabel: ADMIN_CONTENT_LANG_MARKER_LABELS[state] },
      };
    });
  }, [data]);

  const actionMutation = useMutation({
    mutationFn: ({ kind, note }: { kind: ActionKind; note: string }) =>
      adminApi.post(ACTION_CONFIG[kind].path(Number(eventId)), { resolution_note: note }),
    onSuccess: (_result, { kind }) => {
      setNote('');
      void queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.adminEventDetail, eventId] });
      void queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.adminCounts] });
      showToast(UI_STATE.success, ACTION_CONFIG[kind].message);
    },
    onError: (err) => {
      showToast(UI_STATE.error, apiErrorMessage(err, ADMIN_GENERIC_ERROR));
    },
  });

  function act(kind: ActionKind) {
    if (!note.trim()) return;
    actionMutation.mutate({ kind, note: note.trim() });
  }

  if (isLoading) return <PageState kind={UI_STATE.loading} message="Loading…" inline />;
  if (isError || !data) return <PageState kind={UI_STATE.error} message="Couldn't load this event." inline />;

  const { event, dedup_siblings, reports, raw_events, in_todays_feed } = data;
  const cl = event.classification;
  const actionDisabled = actionMutation.isPending || !note.trim();

  const actions: { label: string; variant: 'primary' | 'danger'; disabled?: boolean; onClick: () => void }[] = [];
  if (openReports.length > 0) {
    actions.push(
      { label: 'Resolve', variant: 'primary', disabled: actionDisabled, onClick: () => act('resolved') },
      { label: 'Take down event', variant: 'danger', disabled: actionDisabled, onClick: () => act('taken_down') },
    );
  }
  // submitted_by_organizer_id !== null mirrors the backend's own gate
  // (_submission_or_404, admin.py) — approve/retract 404 without it, so the
  // buttons must not render as if they'd work.
  if (event.needs_review && event.submitted_by_organizer_id !== null) {
    actions.push(
      { label: 'Approve', variant: 'primary', disabled: actionDisabled, onClick: () => act('approved') },
      { label: 'Retract', variant: 'danger', disabled: actionDisabled, onClick: () => act('retracted') },
    );
  }

  // The base locale (et) is never a fallback, even when its *_localized
  // dict happens to carry no 'et' key — its content is title_orig/etc.,
  // the canonical original, not a locale→en→orig fallback. Mirrors
  // markerState's own base-locale exemption above.
  const isFallback = (field: keyof LocaleContent['translated']) =>
    contentLang !== CONTENT_LANG_ORDER[0] && activeContent !== undefined && !activeContent.translated[field];
  const previewImageUrl = safeUrl(event.image_url);
  const sourceUrl = safeUrl(event.url);

  return (
    <div className={styles.page}>
      <div className={styles.head}>
        <div>
          <p className={styles.eyebrow}>Admin / Event #{event.id}</p>
          <h1 className={styles.title}>{event.title_orig}</h1>
        </div>
        <div className={styles.badges}>
          <span className={styles.statusBadge}>{event.status}</span>
          {in_todays_feed && <span className={styles.feedBadge}>In today&rsquo;s Daily 5</span>}
        </div>
      </div>

      {actions.length > 0 && (
        <div className={styles.actionSection}>
          <AdminQueueActionPanel
            noteValue={note}
            onNoteChange={setNote}
            noteLabel="Resolution note (logged with this action)"
            noteDisabled={actionMutation.isPending}
            hint={!note.trim() ? 'Note required before acting.' : undefined}
            actions={actions}
          />
        </div>
      )}

      <div className={styles.tabStrip} role="tablist">
        {ADMIN_EVENT_DETAIL_TABS.map((t) => (
          <button
            key={t}
            type="button"
            role="tab"
            aria-selected={tab === t}
            className={tab === t ? styles.tabActive : styles.tab}
            onClick={() => setTab(t)}
          >
            {t}
            {t === 'Dedup & reports' && reports.length > 0 && <span className={styles.tabCount}>{reports.length}</span>}
            {t === 'Raw payload' && raw_events.length > 0 && <span className={styles.tabCount}>{raw_events.length}</span>}
          </button>
        ))}
      </div>

      <div className={styles.tabPanel}>
        {tab === 'Overview' && (
          <>
            <div className={styles.contentSwitch}>
              <SegmentedControl
                variant="dial"
                options={langOptions}
                value={contentLang}
                onChange={(v) => setContentLang(v as ContentLang)}
                ariaLabel="Content language"
              />
            </div>

            <div className={styles.fieldHead}>
              <h2 className={styles.contentTitle}>{activeContent?.title}</h2>
              {isFallback('title') && (
                <span className={styles.fallbackTag}>fallback</span>
              )}
            </div>

            <div className={styles.fieldHead}>
              <span className={styles.subsectionTitle}>Description</span>
              {isFallback('description') && (
                <span className={styles.fallbackTag}>fallback</span>
              )}
            </div>
            {sanitizedDescription ? (
              <div className={styles.proseHtml} dangerouslySetInnerHTML={{ __html: sanitizedDescription }} />
            ) : (
              <p className={styles.prose}>No description.</p>
            )}

            {sanitizedImportantInfo && (
              <>
                <div className={styles.fieldHead}>
                  <span className={styles.subsectionTitle}>Important info</span>
                  {isFallback('important_info') && (
                    <span className={styles.fallbackTag}>fallback</span>
                  )}
                </div>
                <div
                  className={styles.importantInfo}
                  dangerouslySetInnerHTML={{ __html: sanitizedImportantInfo }}
                />
              </>
            )}

            <h3 className={styles.subsectionTitle}>Record</h3>
            <dl className={styles.factList}>
              <dt>Starts</dt><dd>{formatAdminTimestamp(event.starts_at)}</dd>
              <dt>Ends</dt><dd>{formatAdminTimestamp(event.ends_at)}</dd>
              <dt>Venue</dt><dd>{activeContent?.venue_name ?? event.venue_name ?? '—'}</dd>
              <dt>Address</dt><dd>{event.venue_address ?? '—'}</dd>
              <dt>Coords</dt><dd>{event.lat !== null && event.lng !== null ? `${event.lat}, ${event.lng}` : '—'}</dd>
              <dt>Price</dt>
              <dd>
                {event.price_min !== null || event.price_max !== null
                  ? `${event.price_min ?? '?'} – ${event.price_max ?? '?'} ${event.currency ?? ''}`.trim()
                  : '—'}
              </dd>
              <dt>Free tier</dt><dd>{event.has_free_tier ? 'Yes' : 'No'}</dd>
              <dt>Price hint</dt><dd>{event.price_hint ?? '—'}</dd>
              <dt>Source URL</dt>
              <dd>
                {sourceUrl ? (
                  <a href={sourceUrl} target="_blank" rel="noopener noreferrer" className={styles.factLinkInline}>
                    {sourceUrl}
                  </a>
                ) : '—'}
              </dd>
              <dt>Flags</dt>
              <dd className={chipStyles.chips}>
                {event.is_explicit && <span className={chipStyles.chip}>explicit</span>}
                {event.is_out_of_area && <span className={chipStyles.chip}>out of area</span>}
                {event.is_non_event && <span className={chipStyles.chip}>non-event</span>}
                {!event.is_explicit && !event.is_out_of_area && !event.is_non_event && '—'}
              </dd>
              <dt>Dedup group</dt><dd>{event.dedup_group_id ?? '—'}</dd>
              <dt>Organizer submission</dt><dd>{event.submitted_by_organizer_id ?? 'No'}</dd>
              <dt>Cancellation reason</dt><dd>{event.cancellation_reason ?? '—'}</dd>
              <dt>Created</dt><dd>{formatAdminTimestamp(event.created_at)}</dd>
              <dt>Updated</dt><dd>{formatAdminTimestamp(event.updated_at)}</dd>
              <dt>Detail refetched</dt><dd>{formatAdminTimestamp(event.detail_refetched_at)}</dd>
              <dt>Geocode attempted</dt><dd>{formatAdminTimestamp(event.geocode_attempted_at)}</dd>
            </dl>

            {previewImageUrl && (
              <div className={styles.imagePreview}>
                <img src={previewImageUrl} alt={event.title_orig} className={styles.imageThumb} />
                <p className={styles.imageMeta}>{previewImageUrl}</p>
              </div>
            )}
          </>
        )}

        {tab === 'Classification' && (
          cl ? (
            <>
              <div className={styles.chips}>
                {cl.categories.map((c) => <span key={c} className={styles.chip}>{c}</span>)}
                {cl.vibes.map((v) => <span key={v} className={styles.chipVibe}>{v}</span>)}
              </div>
              <p className={styles.factLine}>
                Quality score: {cl.quality_score ?? '—'} · Model: {cl.model_used ?? '—'} · Lang: {cl.language_detected ?? '—'} · Classified {formatAdminTimestamp(cl.classified_at)}
              </p>
              {cl.why_go_bullets && cl.why_go_bullets.length > 0 && (
                <ul className={styles.whyGo}>
                  {cl.why_go_bullets.map((b) => <li key={b}>{b}</li>)}
                </ul>
              )}
            </>
          ) : <p className={styles.empty}>Not yet classified.</p>
        )}

        {tab === 'Dedup & reports' && (
          <>
            {dedup_siblings.length > 0 && (
              <div className={styles.subsection}>
                <h3 className={styles.subsectionTitle}>Siblings</h3>
                {dedup_siblings.map((s) => (
                  <Link key={s.id} to={ROUTES.adminEventDetail(s.id)} className={styles.siblingRow}>
                    <span>{s.title}</span>
                    <span className={styles.factLabel}>#{s.id} · {s.status}</span>
                  </Link>
                ))}
              </div>
            )}
            <div className={styles.subsection}>
              <h3 className={styles.subsectionTitle}>Reports ({reports.length})</h3>
              {reports.length === 0 && <p className={styles.empty}>No reports.</p>}
              {reports.map((r) => (
                <div key={r.id} className={styles.reportItem}>
                  <div className={styles.reportItemHead}>
                    <strong>{r.reason}</strong>
                    <span className={r.status === REPORT_STATUS.open ? styles.openTag : styles.resolvedTag}>{r.status}</span>
                  </div>
                  {r.detail && <p>{r.detail}</p>}
                  {r.resolution_note && <p className={styles.factLabel}>Resolved: {r.resolution_note}</p>}
                </div>
              ))}
            </div>
          </>
        )}

        {tab === 'Raw payload' && (
          raw_events.length === 0 ? (
            <p className={styles.empty}>No raw events on file (organizer submission, or scrape history pruned).</p>
          ) : (
            raw_events.map((re) => (
              <div key={re.id} className={styles.rawBlock}>
                <p className={styles.rawMeta}>{re.source_slug} · {re.external_id ?? 'no external id'} · fetched {formatAdminTimestamp(re.fetched_at)}</p>
                {/* Escaped/pretty-printed text only — never parsed as HTML.
                    The one field in the console not sanitized at ingest. */}
                <pre className={styles.rawPayload}>{rawPayloadsById.get(re.id)}</pre>
              </div>
            ))
          )
        )}
      </div>
      {toast.status !== UI_STATE.idle && <Toast status={toast.status} message={toast.message} />}
    </div>
  );
}
