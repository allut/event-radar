import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { adminApi, ApiError } from '../../api/client';
import { API, QUERY_KEYS, REPORT_REASONS, UI_STATE } from '../../constants';
import { t } from '../../i18n';
import { relativeTimeFromNow } from '../../utils';
import PageState from '../../components/PageState';
import Toast from '../../components/Toast';
import { useToast } from '../../hooks/useToast';
import AdminQueueSplitView from '../../components/AdminQueueSplitView';
import AdminQueueActionPanel from '../../components/AdminQueueActionPanel';
import styles from './AdminReports.module.css';

interface AdminReport {
  reason: string;
  detail: string | null;
  is_illegal_allegation: boolean;
  created_at: string;
}

interface AdminReportedEvent {
  event_id: number;
  title: string;
  status: string;
  venue: string | null;
  submitted_by_organizer_id: number | null;
  report_count: number;
  reasons: string[];
  has_illegal_allegation: boolean;
  reports: AdminReport[];
  oldest_open_report_at: string;
}

interface AdminReportsResponse {
  total: number;
  events: AdminReportedEvent[];
}

interface AdminReportActionResult {
  event_id: number;
  status?: string;
  resolved_count: number;
}

type ResolutionKind = 'resolved' | 'taken_down';

function reasonLabel(reason: string): string {
  return t(REPORT_REASONS.find((r) => r.value === reason)?.labelKey ?? reason, 'en');
}

// The reports moderation queue (issue #155) — establishes the shared
// split-view inbox pattern (AdminQueueSplitView/AdminQueueActionPanel) that
// the submissions screen (#156) and the event inspector reuse. Resolved
// items are tracked client-side only (session-local, per the parent spec's
// "without re-querying" decision) since GET /admin/reports only ever
// returns REPORT_STATUS_OPEN rows — resolving one removes it from the next
// server fetch, so this screen keeps its own snapshot to render it greyed
// out with a status tag instead of letting it vanish.
export default function AdminReports() {
  const queryClient = useQueryClient();
  const { toast, showToast } = useToast();
  const { data, isLoading, isError } = useQuery({
    queryKey: [QUERY_KEYS.adminReports],
    queryFn: () => adminApi.get<AdminReportsResponse>(API.adminReports),
  });

  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [note, setNote] = useState('');
  const [resolvedById, setResolvedById] = useState<
    Record<number, { item: AdminReportedEvent; kind: ResolutionKind }>
  >({});

  const serverItems = data?.events;
  const items = useMemo(() => {
    const byId = new Map((serverItems ?? []).map((item) => [item.event_id, item]));
    for (const entry of Object.values(resolvedById)) byId.set(entry.item.event_id, entry.item);
    return Array.from(byId.values());
  }, [serverItems, resolvedById]);

  const currentId = selectedId ?? items[0]?.event_id ?? null;

  const actionMutation = useMutation({
    mutationFn: ({ item, kind, note }: { item: AdminReportedEvent; kind: ResolutionKind; note: string }) => {
      const path = kind === 'resolved' ? API.adminReportResolve(item.event_id) : API.adminReportTakedown(item.event_id);
      return adminApi.post<AdminReportActionResult>(path, { resolution_note: note });
    },
    onSuccess: (result, { item, kind }) => {
      const resolvedItem = kind === 'taken_down' && result.status ? { ...item, status: result.status } : item;
      setResolvedById((prev) => ({ ...prev, [item.event_id]: { item: resolvedItem, kind } }));
      setNote('');
      void queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.adminCounts] });
    },
    onError: (err) => {
      showToast(UI_STATE.error, err instanceof ApiError ? err.message : 'Something went wrong. Try again.');
    },
  });

  function act(item: AdminReportedEvent, kind: ResolutionKind) {
    if (!note.trim()) return;
    actionMutation.mutate({ item, kind, note: note.trim() });
  }

  return (
    <div>
      <div className={styles.head}>
        <p className={styles.eyebrow}>Admin / Moderation</p>
        <h1 className={styles.title}>Reports</h1>
      </div>

      {isLoading ? (
        <PageState kind={UI_STATE.loading} message="Loading…" inline />
      ) : isError ? (
        <PageState kind={UI_STATE.error} message="Couldn't load the reports queue." inline />
      ) : (
        <AdminQueueSplitView
          items={items}
          getId={(item) => item.event_id}
          isResolved={(item) => item.event_id in resolvedById}
          resolvedTag={() => 'Resolved'}
          selectedId={currentId}
          onSelect={(id) => {
            setSelectedId(id);
            setNote('');
          }}
          emptyLabel="No open reports."
          renderRow={(item) => (
            <>
              <div className={styles.rowTitle}>{item.title}</div>
              <div className={styles.rowMeta}>
                {item.has_illegal_allegation && <span className={styles.illegalDot} aria-label="Illegal content alleged" />}
                {item.report_count} report{item.report_count === 1 ? '' : 's'} · {relativeTimeFromNow(item.oldest_open_report_at)}
              </div>
            </>
          )}
          renderDetail={(item) => {
            const resolution = resolvedById[item.event_id];
            return (
              <div>
                <h2 className={styles.detailTitle}>{item.title}</h2>
                <p className={styles.detailMeta}>{item.venue ?? 'No venue'} · status: {item.status}</p>
                <div className={styles.chips}>
                  {item.has_illegal_allegation && <span className={styles.illegalChip}>Illegal content alleged</span>}
                  {item.reasons.map((r) => (
                    <span key={r} className={styles.chip}>{reasonLabel(r)}</span>
                  ))}
                </div>
                <div className={styles.reportList}>
                  {item.reports.map((r) => (
                    <div key={`${r.reason}-${r.created_at}`} className={styles.reportItem}>
                      <div className={styles.reportItemHead}>
                        <strong>{reasonLabel(r.reason)}</strong>
                        <span>{relativeTimeFromNow(r.created_at)}</span>
                      </div>
                      {r.detail && <p>{r.detail}</p>}
                    </div>
                  ))}
                </div>

                {resolution ? (
                  <div className={styles.resolvedPanel}>
                    ✓ {resolution.kind === 'taken_down' ? 'Event taken down.' : 'Resolved.'} Reporters notified.
                  </div>
                ) : (
                  <AdminQueueActionPanel
                    noteValue={note}
                    onNoteChange={setNote}
                    noteLabel="Resolution note (sent to reporters)"
                    noteDisabled={actionMutation.isPending}
                    hint={!note.trim() ? 'Note required before resolving or taking down.' : undefined}
                    actions={[
                      { label: 'Resolve', variant: 'primary', disabled: actionMutation.isPending || !note.trim(), onClick: () => act(item, 'resolved') },
                      { label: 'Take down event', variant: 'danger', disabled: actionMutation.isPending || !note.trim(), onClick: () => act(item, 'taken_down') },
                    ]}
                  />
                )}
              </div>
            );
          }}
        />
      )}
      {toast.status !== UI_STATE.idle && <Toast status={toast.status} message={toast.message} />}
    </div>
  );
}
