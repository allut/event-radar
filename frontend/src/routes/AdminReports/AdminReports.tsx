import { useCallback, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { adminApi } from '../../api/client';
import {
  ADMIN_GENERIC_ERROR,
  ADMIN_QUEUE_DETAIL_LINK_LABEL,
  ADMIN_REPORT_RESOLVED_LINK_LABEL,
  ADMIN_REPORT_RESOLVED_NOTICE,
  ADMIN_REPORTS_PARAM,
  ADMIN_REPORTS_QUEUE_PAGE_SIZE,
} from '../../constants/admin';
import { API, PAGE_PARAM, PAGE_QUERY_PARAM, QUERY_KEYS } from '../../constants/api';
import { ADMIN_RESOLUTION_MESSAGES } from '../../constants/claims';
import { LOCALE_EN, UI_STATE } from '../../constants/core';
import { REPORT_REASONS_BY_VALUE } from '../../constants/feedback';
import { ROUTES } from '../../constants/routes';
import { t } from '../../i18n';
import { apiErrorMessage, relativeTimeFromNow } from '../../utils';
import PageState from '../../components/PageState';
import Toast from '../../components/Toast';
import { useToast } from '../../hooks/useToast';
import { useAdminQueuePage, type ActionSpot } from '../../hooks/useAdminQueuePage';
import Pager from '../../components/Pager';
import AdminQueueSplitView from '../../components/AdminQueueSplitView';
import AdminQueueActionPanel from '../../components/AdminQueueActionPanel';
import queueStyles from '../../components/shared/AdminQueue.module.css';
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

// Module-scope — referentially stable forever, so QueueRowList's memo
// (AdminQueueSplitView.tsx, Big-O audit #5, item 3.5) never sees these
// change identity on a resolution-note keystroke.
function getReportId(item: AdminReportedEvent): number {
  return item.event_id;
}
function reportResolvedTag(): string {
  return 'Resolved';
}
function renderReportRow(item: AdminReportedEvent & { oldestOpenReportRelative: string }) {
  return (
    <>
      <div className={styles.rowTitle}>{item.title}</div>
      <div className={styles.rowMeta}>
        {item.has_illegal_allegation && <span className={styles.illegalDot} aria-label="Illegal content alleged" />}
        {item.report_count} report{item.report_count === 1 ? '' : 's'} · {item.oldestOpenReportRelative}
      </div>
    </>
  );
}

interface AdminReportsResponse {
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
  events: AdminReportedEvent[];
  /** True when `report=<id>` named an event that is no longer in the queue. */
  report_not_found: boolean;
}

interface AdminReportActionResult {
  event_id: number;
  status?: string;
  resolved_count: number;
}

type ResolutionKind = 'resolved' | 'taken_down';

function reasonLabel(reason: string): string {
  return t(REPORT_REASONS_BY_VALUE.get(reason)?.labelKey ?? reason, LOCALE_EN);
}

// The reports moderation queue (issue #155) — establishes the shared
// split-view inbox pattern (AdminQueueSplitView/AdminQueueActionPanel) that
// the submissions screen (#156) and the event inspector reuse. GET
// /admin/reports only ever returns REPORT_STATUS_OPEN rows, so resolving one
// removes it from the next fetch; useAdminQueuePage keeps the acted-on row
// in place, greyed out and tagged, and refetches the page once (spec #551).
//
// The admin email deep link is `?report=<event_id>`. With no `page` the
// server finds that row's page and returns its real offset (usePagedQuery
// syncs the URL to it silently); once the URL carries a `page`, `report` is
// only used to pick the selected row and is never sent. A row located on
// page 1 leaves the URL without a `page`, so the locate runs once per link:
// later refetches ask for the plain page and keep its not-found flag, rather
// than re-locating and jumping pages if the row has since moved.
export default function AdminReports() {
  const queryClient = useQueryClient();
  const { toast, showToast } = useToast();
  const [searchParams] = useSearchParams();
  const [note, setNote] = useState('');

  const rawLinkedId = searchParams.get(ADMIN_REPORTS_PARAM.report);
  const parsedLinkedId = rawLinkedId === null ? NaN : Number(rawLinkedId);
  const linkedId = Number.isInteger(parsedLinkedId) && parsedLinkedId > 0 ? parsedLinkedId : null;
  // Only ask the server to locate the row while the URL has no page.
  const locateId = linkedId !== null && !searchParams.has(PAGE_QUERY_PARAM) ? linkedId : null;

  const {
    rows,
    data,
    total,
    tags: resolvedById,
    tagRow,
    resyncAfterFailedAction,
    selectedId,
    setSelectedId,
    listRef,
    isLoading,
    isError,
    isPlaceholderData,
    actionSpot,
    pagerProps,
  } = useAdminQueuePage<AdminReportsResponse, AdminReportedEvent, ResolutionKind>({
    // A located response holds a page the plain page-1 key must not cache.
    queryKey: locateId === null ? [QUERY_KEYS.adminReports] : [QUERY_KEYS.adminReports, 'locate', locateId],
    pageSize: ADMIN_REPORTS_QUEUE_PAGE_SIZE,
    fetchPage: async ({ limit, offset, page }) => {
      // Already located when this query holds a response: the first locate's.
      // Read from the cache, not component state, so it holds across a
      // remount (detail page and Back) for as long as the located data does.
      const located =
        locateId === null
          ? undefined
          : queryClient.getQueryData<AdminReportsResponse>([QUERY_KEYS.adminReports, 'locate', locateId, page]);
      const locate = locateId === null || located !== undefined ? '' : `&${ADMIN_REPORTS_PARAM.report}=${locateId}`;
      const response = await adminApi.get<AdminReportsResponse>(
        `${API.adminReports}?${PAGE_PARAM.limit}=${limit}&${PAGE_PARAM.offset}=${offset}${locate}`,
      );
      if (located !== undefined) return { ...response, report_not_found: located.report_not_found };
      if (locateId !== null) {
        if (!response.report_not_found && response.offset !== offset) {
          // The silent replace to the located page then finds it cached.
          queryClient.setQueryData([QUERY_KEYS.adminReports, response.offset / limit + 1], response);
        }
      }
      return response;
    },
    select: (response) => ({ items: response.events, total: response.total, offset: response.offset }),
    getId: getReportId,
    // Every cached page of the queue (plain and located) goes out of date on
    // an action or a 409/404; only the mounted one refetches.
    invalidateKey: [QUERY_KEYS.adminReports],
    onPageSettled: () => setNote(''),
  });

  // Precomputed once per data/resolution change (not per render) — renderRow
  // below reads this instead of calling relativeTimeFromNow live, so typing
  // in the resolution-note textarea no longer re-parses every row's date
  // (Big-O audit M4).
  const items = useMemo(
    () => rows.map((item) => ({ ...item, oldestOpenReportRelative: relativeTimeFromNow(item.oldest_open_report_at) })),
    [rows],
  );

  const linkedRowShown = linkedId !== null && items.some((item) => item.event_id === linkedId);
  const currentId = selectedId ?? (linkedRowShown ? linkedId : null) ?? items[0]?.event_id ?? null;
  // The row is gone from the queue. Not when this very screen just resolved
  // it: the refetch after that action also reports it missing.
  const resolvedNoticeId =
    locateId !== null && data?.report_not_found === true && !resolvedById.has(locateId) ? locateId : null;

  const actionMutation = useMutation({
    mutationFn: ({ item, kind, note }: { item: AdminReportedEvent; kind: ResolutionKind; note: string; spot: ActionSpot }) => {
      const path = kind === 'resolved' ? API.adminReportResolve(item.event_id) : API.adminReportTakedown(item.event_id);
      return adminApi.post<AdminReportActionResult>(path, { resolution_note: note });
    },
    onSuccess: (result, { item, kind, spot }) => {
      const resolvedItem = kind === 'taken_down' && result.status ? { ...item, status: result.status } : item;
      // Tags the row in place and refetches this page once, so the next
      // report up fills the gap (spec #551). The note draft only resets when
      // the admin is still on the page they acted on.
      if (tagRow(resolvedItem, kind, spot)) setNote('');
      void queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.adminCounts] });
    },
    onError: (err) => {
      showToast(UI_STATE.error, apiErrorMessage(err, ADMIN_GENERIC_ERROR));
      resyncAfterFailedAction(err);
    },
  });

  function act(item: AdminReportedEvent, kind: ResolutionKind) {
    if (!note.trim()) return;
    actionMutation.mutate({ item, kind, note: note.trim(), spot: actionSpot(item) });
  }

  // Stable across note keystrokes (only resolvedById changes them) — see
  // renderReportRow's module-scope siblings above for why this matters.
  const isResolved = useCallback(
    (item: AdminReportedEvent) => resolvedById.has(item.event_id),
    [resolvedById],
  );
  const selectRow = useCallback((id: number) => {
    setSelectedId(id);
    setNote('');
  }, [setSelectedId]);

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
      ) : items.length === 0 && total > 0 ? (
        // A past-end page about to clamp to the real last page.
        <PageState kind={UI_STATE.loading} message="Loading…" inline />
      ) : (
        <>
        {resolvedNoticeId !== null && (
          <p className={styles.notice} role="status">
            {ADMIN_REPORT_RESOLVED_NOTICE.replace('{id}', String(resolvedNoticeId))}{' '}
            <Link to={ROUTES.adminEventDetail(resolvedNoticeId)} className={styles.noticeLink}>
              {ADMIN_REPORT_RESOLVED_LINK_LABEL.replace('{id}', String(resolvedNoticeId))}
            </Link>
          </p>
        )}
        <div className={styles.queue} aria-busy={isPlaceholderData}>
        <AdminQueueSplitView
          items={items}
          getId={getReportId}
          isResolved={isResolved}
          resolvedTag={reportResolvedTag}
          selectedId={currentId}
          onSelect={selectRow}
          emptyLabel="No open reports."
          initialDetailOpen={linkedRowShown}
          renderRow={renderReportRow}
          listRef={listRef}
          listFooter={
            // The pager's strings come from shared/i18n even here: docs/frontend.md "Admin Console"
            <Pager
              {...pagerProps}
              locale={LOCALE_EN}
              liveNoun="items"
              dropOnPageChange={[ADMIN_REPORTS_PARAM.report]}
              className={queueStyles.queuePager}
            />
          }
          renderDetail={(item) => {
            const resolution = resolvedById.get(item.event_id);
            return (
              <div>
                <h2 className={styles.detailTitle}>{item.title}</h2>
                <p className={styles.detailMeta}>{item.venue ?? 'No venue'} · status: {item.status}</p>
                <Link to={ROUTES.adminEventDetail(item.event_id)} className={queueStyles.queueDetailLink}>
                  {ADMIN_QUEUE_DETAIL_LINK_LABEL}
                </Link>
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
                    ✓ {ADMIN_RESOLUTION_MESSAGES[resolution.kind === 'taken_down' ? 'taken_down' : 'resolved']} Reporters notified.
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
        </div>
        </>
      )}
      {toast.status !== UI_STATE.idle && <Toast status={toast.status} message={toast.message} />}
    </div>
  );
}
