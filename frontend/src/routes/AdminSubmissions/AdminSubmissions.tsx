import { useCallback, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { adminApi } from '../../api/client';
import {
  ADMIN_GENERIC_ERROR,
  ADMIN_QUEUE_DETAIL_LINK_LABEL,
  ADMIN_REVIEW_QUEUE_PAGE_SIZE,
} from '../../constants/admin';
import { API, PAGE_PARAM, QUERY_KEYS } from '../../constants/api';
import { ADMIN_RESOLUTION_MESSAGES } from '../../constants/claims';
import { LOCALE_EN, UI_STATE } from '../../constants/core';
import { ROUTES } from '../../constants/routes';
import { apiErrorMessage, relativeTimeFromNow, safeUrl } from '../../utils';
import PageState from '../../components/PageState';
import Toast from '../../components/Toast';
import { useToast } from '../../hooks/useToast';
import { useAdminQueuePage } from '../../hooks/useAdminQueuePage';
import Pager from '../../components/Pager';
import AdminQueueSplitView from '../../components/AdminQueueSplitView';
import AdminQueueActionPanel from '../../components/AdminQueueActionPanel';
import queueStyles from '../../components/shared/AdminQueue.module.css';
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

// Module-scope — referentially stable forever, so QueueRowList's memo
// (AdminQueueSplitView.tsx, Big-O audit #5, item 3.5) never sees these
// change identity on a resolution-note keystroke.
function getSubmissionId(item: AdminSubmission): number {
  return item.id;
}
function renderSubmissionRow(item: AdminSubmission & { createdAtRelative: string }) {
  return (
    <>
      <div className={styles.rowTitle}>{item.title}</div>
      <div className={styles.rowMeta}>
        {item.submitted_by_organizer_id !== null
          ? `Organizer #${item.submitted_by_organizer_id}`
          : 'Unknown organizer'}
        {' · '}
        {item.createdAtRelative}
      </div>
    </>
  );
}

interface AdminSubmissionsResponse {
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
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
  const [note, setNote] = useState('');
  const {
    rows,
    total,
    tags: resolvedById,
    tagRow,
    selectedId,
    setSelectedId,
    listRef,
    isLoading,
    isError,
    isPlaceholderData,
    offset: shownOffset,
    pagerProps,
  } = useAdminQueuePage<AdminSubmissionsResponse, AdminSubmission, ResolutionKind>({
    queryKey: [QUERY_KEYS.adminSubmissions],
    pageSize: ADMIN_REVIEW_QUEUE_PAGE_SIZE,
    fetchPage: ({ limit, offset }) =>
      adminApi.get<AdminSubmissionsResponse>(
        `${API.adminSubmissions}?${PAGE_PARAM.limit}=${limit}&${PAGE_PARAM.offset}=${offset}`,
      ),
    select: (data) => ({ items: data.events, total: data.total, offset: data.offset }),
    getId: getSubmissionId,
    onPageSettled: () => setNote(''),
  });

  // Precomputed once per data/resolution change, not per render — see
  // AdminReports.tsx for why (Big-O audit M4).
  const items = useMemo(
    () => rows.map((item) => ({ ...item, createdAtRelative: relativeTimeFromNow(item.created_at) })),
    [rows],
  );

  const currentId = selectedId ?? items[0]?.id ?? null;

  const actionMutation = useMutation({
    mutationFn: ({ item, kind, note }: { item: AdminSubmission; kind: ResolutionKind; note: string; offset: number }) => {
      const path = kind === 'approved' ? API.adminSubmissionApprove(item.id) : API.adminSubmissionRetract(item.id);
      return adminApi.post<AdminSubmissionActionResult>(path, { resolution_note: note });
    },
    onSuccess: (result, { item, kind, offset: actedOffset }) => {
      const resolvedItem = kind === 'retracted' && result.status ? { ...item, status: result.status } : item;
      // Tags the row in place and refetches this page once, so the next
      // row up fills the gap (spec #551). The note draft only resets when
      // the admin is still on the page they acted on.
      if (tagRow(resolvedItem, kind, actedOffset)) setNote('');
      void queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.adminCounts] });
    },
    onError: (err) => {
      showToast(UI_STATE.error, apiErrorMessage(err, ADMIN_GENERIC_ERROR));
    },
  });

  function act(item: AdminSubmission, kind: ResolutionKind) {
    if (!note.trim()) return;
    actionMutation.mutate({ item, kind, note: note.trim(), offset: shownOffset });
  }

  // Stable across note keystrokes (only resolvedById changes them) — see
  // renderSubmissionRow's module-scope siblings above for why this matters.
  const isResolved = useCallback(
    (item: AdminSubmission) => resolvedById.has(item.id),
    [resolvedById],
  );
  const resolvedTag = useCallback(
    (item: AdminSubmission) => (resolvedById.get(item.id)?.kind === 'retracted' ? 'Retracted' : 'Approved'),
    [resolvedById],
  );
  const selectRow = useCallback((id: number) => {
    setSelectedId(id);
    setNote('');
  }, [setSelectedId]);

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
      ) : items.length === 0 && total > 0 ? (
        // A past-end page about to clamp to the real last page.
        <PageState kind={UI_STATE.loading} message="Loading…" inline />
      ) : (
        <div className={styles.queue} aria-busy={isPlaceholderData}>
        <AdminQueueSplitView
          items={items}
          getId={getSubmissionId}
          isResolved={isResolved}
          resolvedTag={resolvedTag}
          selectedId={currentId}
          onSelect={selectRow}
          emptyLabel="No pending submissions."
          renderRow={renderSubmissionRow}
          listRef={listRef}
          listFooter={
            // The pager's strings come from shared/i18n even here: docs/frontend.md "Admin Console"
            <Pager {...pagerProps} locale={LOCALE_EN} liveNoun="items" className={queueStyles.queuePager} />
          }
          renderDetail={(item) => {
            const resolution = resolvedById.get(item.id);
            const previewUrl = safeUrl(item.url);
            return (
              <div>
                <h2 className={styles.detailTitle}>{item.title}</h2>
                <p className={styles.detailMeta}>{item.venue_name ?? 'No venue'} · status: {item.status}</p>
                <Link to={ROUTES.adminEventDetail(item.id)} className={queueStyles.queueDetailLink}>
                  {ADMIN_QUEUE_DETAIL_LINK_LABEL}
                </Link>
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
                    ✓ {ADMIN_RESOLUTION_MESSAGES[resolution.kind === 'retracted' ? 'retracted' : 'approved']}
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
        </div>
      )}
      {toast.status !== UI_STATE.idle && <Toast status={toast.status} message={toast.message} />}
    </div>
  );
}
