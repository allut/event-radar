import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { adminApi, ApiError } from '../../api/client';
import { API, QUERY_KEYS, UI_STATE } from '../../constants';
import { relativeTimeFromNow, safeUrl } from '../../utils';
import PageState from '../../components/PageState';
import Toast from '../../components/Toast';
import { useToast } from '../../hooks/useToast';
import AdminQueueSplitView from '../../components/AdminQueueSplitView';
import AdminQueueActionPanel from '../../components/AdminQueueActionPanel';
import styles from './AdminSubmissions.module.css';

interface AdminSubmission {
  id: number;
  title: string;
  description: string | null;
  venue_name: string | null;
  url: string | null;
  categories: string[];
  status: string;
  submitted_by_organizer_id: number | null;
  created_at: string;
}

interface AdminSubmissionsResponse {
  total: number;
  events: AdminSubmission[];
}

interface AdminSubmissionActionResult {
  id: number;
  status?: string;
  needs_review?: boolean;
  note: string;
}

type ResolutionKind = 'approved' | 'retracted';

// The organizer-submission review queue (issue #156) — reuses the shared
// split-view inbox pattern (AdminQueueSplitView/AdminQueueActionPanel)
// established by AdminReports (#155). GET /admin/submissions only ever
// returns needs_review rows, so an approved/retracted item disappears from
// the next server fetch — this screen keeps its own session-local snapshot
// (mirroring AdminReports' resolvedById) so the actioned row stays visible,
// greyed out and tagged, instead of vanishing.
export default function AdminSubmissions() {
  const queryClient = useQueryClient();
  const { toast, showToast } = useToast();
  const { data, isLoading, isError } = useQuery({
    queryKey: [QUERY_KEYS.adminSubmissions],
    queryFn: () => adminApi.get<AdminSubmissionsResponse>(API.adminSubmissions),
  });

  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [note, setNote] = useState('');
  const [resolvedById, setResolvedById] = useState<
    Record<number, { item: AdminSubmission; kind: ResolutionKind }>
  >({});

  const serverItems = data?.events;
  const items = useMemo(() => {
    const byId = new Map((serverItems ?? []).map((item) => [item.id, item]));
    for (const entry of Object.values(resolvedById)) byId.set(entry.item.id, entry.item);
    return Array.from(byId.values());
  }, [serverItems, resolvedById]);

  const currentId = selectedId ?? items[0]?.id ?? null;

  const actionMutation = useMutation({
    mutationFn: ({ item, kind, note }: { item: AdminSubmission; kind: ResolutionKind; note: string }) => {
      const path = kind === 'approved' ? API.adminSubmissionApprove(item.id) : API.adminSubmissionRetract(item.id);
      return adminApi.post<AdminSubmissionActionResult>(path, { resolution_note: note });
    },
    onSuccess: (result, { item, kind }) => {
      const resolvedItem = kind === 'retracted' && result.status ? { ...item, status: result.status } : item;
      setResolvedById((prev) => ({ ...prev, [item.id]: { item: resolvedItem, kind } }));
      setNote('');
      void queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.adminCounts] });
    },
    onError: (err) => {
      showToast(UI_STATE.error, err instanceof ApiError ? err.message : 'Something went wrong. Try again.');
    },
  });

  function act(item: AdminSubmission, kind: ResolutionKind) {
    if (!note.trim()) return;
    actionMutation.mutate({ item, kind, note: note.trim() });
  }

  return (
    <div>
      <div className={styles.head}>
        <p className={styles.eyebrow}>Admin / Organizer trust</p>
        <h1 className={styles.title}>Submissions</h1>
      </div>

      {isLoading ? (
        <PageState kind={UI_STATE.loading} message="Loading…" inline />
      ) : isError ? (
        <PageState kind={UI_STATE.error} message="Couldn't load the submissions queue." inline />
      ) : (
        <AdminQueueSplitView
          items={items}
          getId={(item) => item.id}
          isResolved={(item) => item.id in resolvedById}
          resolvedTag={(item) => (resolvedById[item.id]?.kind === 'retracted' ? 'Retracted' : 'Approved')}
          selectedId={currentId}
          onSelect={(id) => {
            setSelectedId(id);
            setNote('');
          }}
          emptyLabel="No pending submissions."
          renderRow={(item) => (
            <>
              <div className={styles.rowTitle}>{item.title}</div>
              <div className={styles.rowMeta}>
                {item.submitted_by_organizer_id !== null
                  ? `Organizer #${item.submitted_by_organizer_id}`
                  : 'Unknown organizer'}
                {' · '}
                {relativeTimeFromNow(item.created_at)}
              </div>
            </>
          )}
          renderDetail={(item) => {
            const resolution = resolvedById[item.id];
            const previewUrl = safeUrl(item.url);
            return (
              <div>
                <h2 className={styles.detailTitle}>{item.title}</h2>
                <p className={styles.detailMeta}>{item.venue_name ?? 'No venue'} · status: {item.status}</p>
                {item.categories.length > 0 && (
                  <div className={styles.chips}>
                    {item.categories.map((c) => (
                      <span key={c} className={styles.chip}>{c}</span>
                    ))}
                  </div>
                )}
                <div className={styles.preview}>
                  {item.description ?? 'No description.'}
                  {previewUrl && (
                    <>
                      <br />
                      <a href={previewUrl} target="_blank" rel="noopener noreferrer" className={styles.previewLink}>
                        {previewUrl} →
                      </a>
                    </>
                  )}
                </div>

                {resolution ? (
                  <div
                    className={
                      resolution.kind === 'retracted'
                        ? `${styles.resolvedPanel} ${styles.retractedPanel}`
                        : styles.resolvedPanel
                    }
                  >
                    ✓ {resolution.kind === 'retracted' ? 'Submission retracted.' : 'Submission approved.'}
                  </div>
                ) : (
                  <AdminQueueActionPanel
                    noteValue={note}
                    onNoteChange={setNote}
                    noteLabel="Note (logged with this action)"
                    noteDisabled={actionMutation.isPending}
                    hint={!note.trim() ? 'Note required before approving or retracting.' : undefined}
                    actions={[
                      { label: 'Approve', variant: 'primary', disabled: actionMutation.isPending || !note.trim(), onClick: () => act(item, 'approved') },
                      { label: 'Retract', variant: 'danger', disabled: actionMutation.isPending || !note.trim(), onClick: () => act(item, 'retracted') },
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
