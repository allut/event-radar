import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { adminApi, ApiError } from '../../api/client';
import { API, QUERY_KEYS, ROUTES, UI_STATE, REPORT_STATUS, ADMIN_EVENT_DETAIL_TABS } from '../../constants';
import { sanitizeHtml, formatAdminTimestamp } from '../../utils';
import PageState from '../../components/PageState';
import Toast from '../../components/Toast';
import { useToast } from '../../hooks/useToast';
import AdminQueueActionPanel from '../../components/AdminQueueActionPanel';
import styles from './AdminEventDetail.module.css';

interface InspectorEvent {
  id: number;
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
  resolved: { path: API.adminReportResolve, message: 'Resolved.' },
  taken_down: { path: API.adminReportTakedown, message: 'Event taken down.' },
  approved: { path: API.adminSubmissionApprove, message: 'Submission approved.' },
  retracted: { path: API.adminSubmissionRetract, message: 'Submission retracted.' },
};

type Tab = (typeof ADMIN_EVENT_DETAIL_TABS)[number];

// Admin event inspector (issue #157, part of #153): deep-linkable detail
// panel for one event regardless of status. Tabbed layout — chosen over a
// stacked single column or a two-column dashboard after a 3-variant
// prototype review (see branch prototype/admin-event-inspector-157).
export default function AdminEventDetail({ eventId }: { eventId: string }) {
  const queryClient = useQueryClient();
  const { toast, showToast } = useToast();
  const [tab, setTab] = useState<Tab>('Overview');
  const [note, setNote] = useState('');

  const { data, isLoading, isError } = useQuery({
    queryKey: [QUERY_KEYS.adminEventDetail, eventId],
    queryFn: () => adminApi.get<InspectorResponse>(API.adminEventDetail(eventId)),
  });

  const sanitizedDescription = useMemo(
    () => (data?.event.description_orig ? sanitizeHtml(data.event.description_orig) : null),
    [data],
  );
  const sanitizedImportantInfo = useMemo(
    () => (data?.event.important_info ? sanitizeHtml(data.event.important_info) : null),
    [data],
  );

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
      showToast(UI_STATE.error, err instanceof ApiError ? err.message : 'Something went wrong. Try again.');
    },
  });

  function act(kind: ActionKind) {
    if (!note.trim()) return;
    actionMutation.mutate({ kind, note: note.trim() });
  }

  if (isLoading) return <PageState kind={UI_STATE.loading} message="Loading…" inline />;
  if (isError || !data) return <PageState kind={UI_STATE.error} message="Couldn't load this event." inline />;

  const { event, dedup_siblings, reports, raw_events, in_todays_feed } = data;
  const openReports = reports.filter((r) => r.status === REPORT_STATUS.open);
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
            <dl className={styles.factList}>
              <dt>Dedup group</dt><dd>{event.dedup_group_id ?? '—'}</dd>
              <dt>Organizer submission</dt><dd>{event.submitted_by_organizer_id ?? 'No'}</dd>
              <dt>Cancellation reason</dt><dd>{event.cancellation_reason ?? '—'}</dd>
              <dt>Created</dt><dd>{formatAdminTimestamp(event.created_at)}</dd>
              <dt>Updated</dt><dd>{formatAdminTimestamp(event.updated_at)}</dd>
              <dt>Detail refetched</dt><dd>{formatAdminTimestamp(event.detail_refetched_at)}</dd>
            </dl>
            {sanitizedDescription ? (
              <div className={styles.proseHtml} dangerouslySetInnerHTML={{ __html: sanitizedDescription }} />
            ) : (
              <p className={styles.prose}>No description.</p>
            )}
            {sanitizedImportantInfo && (
              <div
                className={styles.importantInfo}
                dangerouslySetInnerHTML={{ __html: sanitizedImportantInfo }}
              />
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
                <pre className={styles.rawPayload}>{JSON.stringify(re.payload, null, 2)}</pre>
              </div>
            ))
          )
        )}
      </div>
      {toast.status !== UI_STATE.idle && <Toast status={toast.status} message={toast.message} />}
    </div>
  );
}
