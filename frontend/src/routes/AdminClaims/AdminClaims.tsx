import { useCallback, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { adminApi } from '../../api/client';
import { ADMIN_CLAIMS_QUEUE_PAGE_SIZE } from '../../_generated/sharedConstants';
import {
  ADMIN_CLAIMS_TAB_PARAM,
  ADMIN_GENERIC_ERROR,
  ADMIN_QUEUE_DETAIL_LINK_LABEL,
  ADMIN_LOADING_LABEL,
} from '../../constants/admin';
import { API, PAGE_PARAM, QUERY_KEYS } from '../../constants/api';
import {
  ADMIN_CLAIM_ACTION_TAGS,
  ADMIN_CLAIM_MECHANISM_LABELS,
  CLAIM_DNS_VERIFICATION_MECHANISMS,
  CLAIM_KIND_PUBLISHER,
  CLAIM_KIND_SERIES,
  CLAIM_STATUS_APPROVED,
  CLAIM_STATUS_PENDING,
  CLAIM_VERIFICATION_MECHANISM_FIENTA_TOKEN,
  CLAIM_VERIFICATION_MECHANISM_PILETILEVI_MAILBOX,
  type AdminClaimActionKind,
  type ClaimKind,
  type ClaimVerificationMechanism,
} from '../../constants/claims';
import { LOCALE_EN, UI_STATE } from '../../constants/core';
import { ROUTES } from '../../constants/routes';
import { apiErrorMessage, relativeTimeFromNow } from '../../utils';
import PageState from '../../components/PageState';
import Toast from '../../components/Toast';
import { useToast, type UseToastResult } from '../../hooks/useToast';
import { useAdminQueuePage, type ActionSpot } from '../../hooks/useAdminQueuePage';
import { usePageParam } from '../../hooks/usePageParam';
import Pager from '../../components/Pager';
import AdminQueueSplitView from '../../components/AdminQueueSplitView';
import AdminQueueActionPanel from '../../components/AdminQueueActionPanel';
import queueStyles from '../../components/shared/AdminQueue.module.css';
import styles from './AdminClaims.module.css';

type ClaimTab = typeof CLAIM_STATUS_PENDING | typeof CLAIM_STATUS_APPROVED;

interface AdminClaimOrganizer {
  id: number;
  email: string;
  name: string | null;
}

interface AdminClaimPublisher {
  id: number;
  name: string;
}

interface AdminClaim {
  id: number;
  kind: ClaimKind;
  status: string;
  organizer: AdminClaimOrganizer;
  publisher: AdminClaimPublisher | null;
  event_series_key: string | null;
  verification_mechanism: string | null;
  verification_domain: string | null;
  verification_contact: string | null;
  dns_record_name: string | null;
  proof_token: string;
  justification: string | null;
  event_id: number | null;
  event_title: string | null;
  created_at: string;
  resolved_at: string | null;
}

interface AdminClaimsResponse {
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
  claims: AdminClaim[];
}

interface AdminClaimActionResult {
  id: number;
  status?: string;
  event_id?: number | null;
  note: string;
}

function mechanismLabel(mechanism: string | null): string {
  if (!mechanism) return 'Unverified';
  return ADMIN_CLAIM_MECHANISM_LABELS[mechanism] ?? mechanism;
}

function targetLabel(item: AdminClaim): string {
  if (item.kind === CLAIM_KIND_PUBLISHER) return item.publisher?.name ?? 'Unknown publisher';
  const [title, venue] = (item.event_series_key ?? '').split('\x1f');
  return venue ? `${title} @ ${venue}` : title || 'Series claim';
}

function organizerLabel(organizer: AdminClaimOrganizer): string {
  return organizer.name || organizer.email;
}

// Module-scope — referentially stable, same rationale as AdminReports'
// renderReportRow siblings (AdminQueueSplitView's memo never sees these
// change identity on a resolution-note keystroke).
function getClaimId(item: AdminClaim): number {
  return item.id;
}
function renderClaimRow(item: AdminClaim & { relativeCreated: string }) {
  return (
    <>
      <div className={styles.rowTitle}>{organizerLabel(item.organizer)}</div>
      <div className={styles.rowMeta}>
        <span className={styles.mechBadge}>{mechanismLabel(item.verification_mechanism)}</span>
        {targetLabel(item)} · {item.relativeCreated}
      </div>
    </>
  );
}

// The claims moderation queue (#420) — a dedicated grant/decline/revoke
// decision shape, separate from /admin/reports (resolve/take-down) and
// /admin/submissions (approve/retract). Reuses AdminReports' split-view
// inbox pattern with an added Pending review / Granted tab switch, since a
// claim's evidence and available actions differ by status. The tab lives in
// the URL (`?status=approved`; pending omitted) next to `?page` (spec #551).
export default function AdminClaims() {
  const [searchParams] = useSearchParams();
  const { setListParams } = usePageParam({ defaults: { [ADMIN_CLAIMS_TAB_PARAM]: CLAIM_STATUS_PENDING } });
  const { toast, showToast } = useToast();
  const activeTab: ClaimTab =
    searchParams.get(ADMIN_CLAIMS_TAB_PARAM) === CLAIM_STATUS_APPROVED ? CLAIM_STATUS_APPROVED : CLAIM_STATUS_PENDING;

  // One push that also drops `page`, so a tab switch starts at page 1.
  function switchTab(tab: ClaimTab) {
    setListParams((params) => {
      params.set(ADMIN_CLAIMS_TAB_PARAM, tab);
      return params;
    });
  }

  return (
    <div>
      <div className={styles.head}>
        <p className={styles.eyebrow}>Admin / Trust</p>
        <h1 className={styles.title}>Claims</h1>
      </div>

      <div className={queueStyles.queueTabStrip} role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === CLAIM_STATUS_PENDING}
          className={activeTab === CLAIM_STATUS_PENDING ? queueStyles.queueTabActive : queueStyles.queueTab}
          onClick={() => switchTab(CLAIM_STATUS_PENDING)}
        >
          Pending review
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === CLAIM_STATUS_APPROVED}
          className={activeTab === CLAIM_STATUS_APPROVED ? queueStyles.queueTabActive : queueStyles.queueTab}
          onClick={() => switchTab(CLAIM_STATUS_APPROVED)}
        >
          Granted
        </button>
      </div>

      {/* Keyed by tab: the selection, note draft and acted-on tags are
          per-tab (a claim declined on one tab flips out of both server
          filters and must not leak into the other). */}
      {/* The toast lives here, not in the keyed queue: an action that fails
          after a tab switch still reports its error. */}
      <ClaimsQueue key={activeTab} activeTab={activeTab} showToast={showToast} />
      {toast.status !== UI_STATE.idle && <Toast status={toast.status} message={toast.message} />}
    </div>
  );
}

function ClaimsQueue({
  activeTab,
  showToast,
}: {
  activeTab: ClaimTab;
  showToast: UseToastResult['showToast'];
}) {
  const queryClient = useQueryClient();
  const [note, setNote] = useState('');
  const {
    rows,
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
  } = useAdminQueuePage<AdminClaimsResponse, AdminClaim, AdminClaimActionKind>({
    queryKey: [QUERY_KEYS.adminClaims, activeTab],
    pageSize: ADMIN_CLAIMS_QUEUE_PAGE_SIZE,
    fetchPage: ({ limit, offset }) =>
      adminApi.get<AdminClaimsResponse>(
        `${API.adminClaims}?${ADMIN_CLAIMS_TAB_PARAM}=${activeTab}&${PAGE_PARAM.limit}=${limit}&${PAGE_PARAM.offset}=${offset}`,
      ),
    select: (data) => ({ items: data.claims, total: data.total, offset: data.offset }),
    getId: getClaimId,
    // The claim changes tabs, so the other tab's cached pages are out of date
    // too: the action invalidates the whole prefix, refetching whichever tab
    // is mounted by then (the admin may have switched tab mid-action).
    invalidateKey: [QUERY_KEYS.adminClaims],
    onPageSettled: () => setNote(''),
  });

  const items = useMemo(
    () => rows.map((item) => ({ ...item, relativeCreated: relativeTimeFromNow(item.created_at) })),
    [rows],
  );

  const currentId = selectedId ?? items[0]?.id ?? null;

  const actionMutation = useMutation({
    mutationFn: ({ item, kind, note }: { item: AdminClaim; kind: AdminClaimActionKind; note: string; spot: ActionSpot }) => {
      const path =
        kind === 'granted'
          ? API.adminClaimGrant(item.id)
          : kind === 'declined'
            ? API.adminClaimDecline(item.id)
            : API.adminClaimRevoke(item.id);
      return adminApi.post<AdminClaimActionResult>(path, { resolution_note: note });
    },
    onSuccess: (_result, { item, kind, spot }) => {
      // Tags the row in place and refetches this page once, so the next
      // row up fills the gap (spec #551). The note draft only resets when
      // the admin is still on the page they acted on.
      if (tagRow(item, kind, spot)) setNote('');
      void queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.adminCounts] });
    },
    onError: (err) => {
      showToast(UI_STATE.error, apiErrorMessage(err, ADMIN_GENERIC_ERROR));
      resyncAfterFailedAction(err);
    },
  });

  function act(item: AdminClaim, kind: AdminClaimActionKind) {
    if (!note.trim()) return;
    actionMutation.mutate({ item, kind, note: note.trim(), spot: actionSpot(item) });
  }

  const isResolved = useCallback((item: AdminClaim) => resolvedById.has(item.id), [resolvedById]);
  const selectRow = useCallback((id: number) => {
    setSelectedId(id);
    setNote('');
  }, [setSelectedId]);
  const resolvedTag = useCallback(
    (item: AdminClaim) => ADMIN_CLAIM_ACTION_TAGS[resolvedById.get(item.id)?.kind ?? 'granted'],
    [resolvedById],
  );
  return (
    <>
      {isLoading ? (
        <PageState kind={UI_STATE.loading} message={ADMIN_LOADING_LABEL} inline />
      ) : isError ? (
        <PageState kind={UI_STATE.error} message="Couldn't load the claims queue." inline />
      ) : items.length === 0 && total > 0 ? (
        // A past-end page about to clamp to the real last page.
        <PageState kind={UI_STATE.loading} message={ADMIN_LOADING_LABEL} inline />
      ) : (
        <div aria-busy={isPlaceholderData}>
          <AdminQueueSplitView
            items={items}
            getId={getClaimId}
            isResolved={isResolved}
            resolvedTag={resolvedTag}
            selectedId={currentId}
            onSelect={selectRow}
            emptyLabel={activeTab === CLAIM_STATUS_PENDING ? 'No claims pending review.' : 'No granted claims.'}
            renderRow={renderClaimRow}
            listRef={listRef}
            listFooter={
              // The pager's strings come from shared/i18n even here: docs/frontend.md "Admin Console"
              <Pager {...pagerProps} locale={LOCALE_EN} liveNoun="items" className={queueStyles.queuePager} />
            }
            renderDetail={(item) => {
              const resolution = resolvedById.get(item.id);
              return (
                <div>
                  <h2 className={styles.detailTitle}>{organizerLabel(item.organizer)}</h2>
                  <p className={styles.detailMeta}>
                    {item.kind === CLAIM_KIND_PUBLISHER ? 'Publisher' : 'Series'} claim on {targetLabel(item)} · claimant:{' '}
                    {item.organizer.email}
                  </p>
                  {item.event_id !== null && (
                    <Link to={ROUTES.adminEventDetail(item.event_id)} className={queueStyles.queueDetailLink}>
                      {ADMIN_QUEUE_DETAIL_LINK_LABEL}
                    </Link>
                  )}

                  <div className={styles.evidence}>
                    {item.verification_mechanism === CLAIM_VERIFICATION_MECHANISM_FIENTA_TOKEN ? (
                      <>
                        <p className={styles.evidenceLabel}>Fienta token round-trip</p>
                        <div className={styles.evidenceRow}>
                          <span className={styles.evidenceKey}>Token</span>
                          <span className={styles.evidenceValue}>{item.proof_token}</span>
                        </div>
                      </>
                    ) : item.verification_mechanism !== null && CLAIM_DNS_VERIFICATION_MECHANISMS.has(item.verification_mechanism as ClaimVerificationMechanism) ? (
                      <>
                        <p className={styles.evidenceLabel}>DNS-TXT check</p>
                        <div className={styles.evidenceRow}>
                          <span className={styles.evidenceKey}>Domain</span>
                          <span className={styles.evidenceValue}>{item.verification_domain ?? '—'}</span>
                        </div>
                        <div className={styles.evidenceRow}>
                          <span className={styles.evidenceKey}>Expected record</span>
                          <span className={styles.evidenceValue}>{item.dns_record_name ?? '—'}</span>
                        </div>
                        <div className={styles.evidenceRow}>
                          <span className={styles.evidenceKey}>Value</span>
                          <span className={styles.evidenceValue}>{item.proof_token}</span>
                        </div>
                      </>
                    ) : item.verification_mechanism === CLAIM_VERIFICATION_MECHANISM_PILETILEVI_MAILBOX ? (
                      <>
                        <p className={styles.evidenceLabel}>Contact-mailbox check</p>
                        <div className={styles.evidenceRow}>
                          <span className={styles.evidenceKey}>Claimant account email</span>
                          <span className={styles.evidenceValue}>{item.organizer.email}</span>
                        </div>
                        <div className={styles.evidenceRow}>
                          <span className={styles.evidenceKey}>Published promoter contact</span>
                          <span className={styles.evidenceValue}>{item.verification_contact ?? '—'}</span>
                        </div>
                        <div className={styles.evidenceRow}>
                          <span className={styles.evidenceKey}>Result</span>
                          <span className={styles.evidenceValue}>
                            {item.verification_contact === null
                              ? 'No contact info published'
                              : item.verification_contact.toLowerCase() === item.organizer.email.toLowerCase()
                                ? 'Match'
                                : 'No match'}
                          </span>
                        </div>
                      </>
                    ) : (
                      <>
                        <p className={styles.evidenceLabel}>Claimant identity</p>
                        <div className={styles.evidenceRow}>
                          <span className={styles.evidenceKey}>No automated check available for this claim</span>
                        </div>
                      </>
                    )}
                    {item.kind === CLAIM_KIND_SERIES && item.justification && (
                      <>
                        <p className={styles.evidenceLabelSpaced}>Claimant&apos;s justification</p>
                        <p className={styles.justificationBlock}>&ldquo;{item.justification}&rdquo;</p>
                      </>
                    )}
                  </div>

                  {item.status === CLAIM_STATUS_APPROVED && (
                    <div className={styles.warnCallout}>
                      <strong>Revoking</strong> deletes this claim and reverts the event&apos;s pinned fields to
                      source authority immediately.
                    </div>
                  )}

                  {resolution ? (
                    <div className={styles.resolvedPanel}>✓ {ADMIN_CLAIM_ACTION_TAGS[resolution.kind]}.</div>
                  ) : item.status === CLAIM_STATUS_PENDING ? (
                    <AdminQueueActionPanel
                      noteValue={note}
                      onNoteChange={setNote}
                      noteLabel="Resolution note"
                      noteDisabled={actionMutation.isPending}
                      hint={!note.trim() ? 'Note required before granting or declining.' : undefined}
                      actions={[
                        { label: 'Grant claim', variant: 'primary', disabled: actionMutation.isPending || !note.trim(), onClick: () => act(item, 'granted') },
                        { label: 'Decline claim', variant: 'danger', disabled: actionMutation.isPending || !note.trim(), onClick: () => act(item, 'declined') },
                      ]}
                    />
                  ) : (
                    <AdminQueueActionPanel
                      noteValue={note}
                      onNoteChange={setNote}
                      noteLabel="Resolution note"
                      noteDisabled={actionMutation.isPending}
                      hint={!note.trim() ? 'Note required before revoking.' : undefined}
                      actions={[
                        { label: 'Revoke claim', variant: 'danger', disabled: actionMutation.isPending || !note.trim(), onClick: () => act(item, 'revoked') },
                      ]}
                    />
                  )}
                </div>
              );
            }}
          />
        </div>
      )}
    </>
  );
}
