import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import { adminApi } from '../../api/client';
import { API, PAGE_PARAM, QUERY_KEYS } from '../../constants/api';
import {
  ADMIN_PROMOTION_REQUESTS_PAGE_SIZE,
  PROMOTION_NOT_SHOWING_NOT_OWNED,
} from '../../_generated/sharedConstants';
import { UI_STATE } from '../../constants/core';
import {
  ADMIN_PROMOTION_REQUESTS_PARAM,
  PROMOTION_REQUEST_COPY as COPY,
  PROMOTION_REQUEST_REASON_LABELS,
  PROMOTION_REQUEST_STATUS,
  PROMOTION_REQUEST_STATUS_OPTIONS,
  PROMOTION_RESTRICTION_NONE,
} from '../../constants/promotions';
import { useToast, type UseToastResult } from '../../hooks/useToast';
import {
  formatDayMonth,
  formatEuro,
  formatWindow,
  restrictionTag,
  type PromotionRequestRow,
  type PromotionRequestsResponse,
} from '../../lib/promotions';
import { relativeTimeFromNow } from '../../utils';
import PageState from '../PageState';
import PromotionGrantForm from '../PromotionGrantForm';
import SegmentedControl from '../SegmentedControl';
import Toast from '../Toast';
import DeclineRequestModal from './DeclineRequestModal';
import styles from './PromotionRequests.module.css';

function RestrictionChip({ restriction }: { restriction: string | null }) {
  if (restriction === null) return <span className={styles.chip}>{COPY.notAssessed}</span>;
  if (restriction === PROMOTION_RESTRICTION_NONE) return null;
  return <span className={styles.tag}>{restrictionTag(restriction)}</span>;
}

function RequestRow({
  request,
  selected,
  onGrant,
  onDecline,
}: {
  request: PromotionRequestRow;
  selected: boolean;
  onGrant: (r: PromotionRequestRow) => void;
  onDecline: (r: PromotionRequestRow) => void;
}) {
  const pending = request.status === PROMOTION_REQUEST_STATUS.pending;
  const reason = request.not_eligible_reason;
  const age = pending
    ? relativeTimeFromNow(request.created_at)
    : `${request.status} ${formatDayMonth(request.resolved_at ?? request.created_at)}`;
  return (
    <li className={selected ? styles.rowSelected : styles.row}>
      <div>
        <div className={styles.rowTitle}>
          {request.event_title} <RestrictionChip restriction={request.promotion_restriction} />
        </div>
        <div className={styles.rowMeta}>
          <span>{request.organizer_name}</span>
          <span>·</span>
          <span className={styles.mono}>{formatWindow(request.start_date, request.end_date)}</span>
          <span>·</span>
          <span className={styles.mono}>
            {request.days} days · {formatEuro(request.price.net_cents)} + {formatEuro(request.price.vat_cents)} VAT
          </span>
          <span>·</span>
          <span>{age}</span>
        </div>
        {request.note && <div className={styles.rowNote}>{COPY.organizerNote}“{request.note}”</div>}
        {pending && reason && (
          <div className={styles.reason}>
            {COPY.notGrantable}
            {PROMOTION_REQUEST_REASON_LABELS[reason] ?? reason}{' '}
            {reason === PROMOTION_NOT_SHOWING_NOT_OWNED ? COPY.dormantTail : COPY.editTail}
          </div>
        )}
        {request.status === PROMOTION_REQUEST_STATUS.declined && request.decline_reason && (
          <div className={styles.rowNote}>{COPY.reasonSent}{request.decline_reason}</div>
        )}
      </div>
      {pending && (
        <div className={styles.actions}>
          <button
            type="button"
            className={`${styles.primaryButton} ${styles.smallButton}`}
            aria-label={`${COPY.grant} ${request.event_title}`}
            onClick={() => onGrant(request)}
          >
            {COPY.grant}
          </button>
          <button
            type="button"
            className={`${styles.plainButton} ${styles.smallButton}`}
            aria-label={`${COPY.decline} ${request.event_title}`}
            onClick={() => onDecline(request)}
          >
            {COPY.decline}
          </button>
        </div>
      )}
    </li>
  );
}

/** Promotion request queue (#615) on /admin/promotions: pending count, each
 * request's not-eligible reason and restriction tag, the grant form prefilled
 * from a request and the decline dialog. Shown while requests are pending or
 * when a history tab is picked (`?requests=granted`). */
export default function PromotionRequests() {
  const { toast, showToast } = useToast();
  return (
    <>
      <RequestQueue showToast={showToast} />
      {toast.status !== UI_STATE.idle && <Toast status={toast.status} message={toast.message} />}
    </>
  );
}

function RequestQueue({ showToast }: { showToast: UseToastResult['showToast'] }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const param = searchParams.get(ADMIN_PROMOTION_REQUESTS_PARAM) ?? '';
  const status = PROMOTION_REQUEST_STATUS_OPTIONS.some((o) => o.value === param)
    ? param
    : PROMOTION_REQUEST_STATUS.pending;
  const [grantId, setGrantId] = useState<number | null>(null);
  const [declining, setDeclining] = useState<PromotionRequestRow | null>(null);

  const query = useQuery({
    queryKey: [QUERY_KEYS.adminPromotionRequests, status],
    queryFn: () =>
      adminApi.get<PromotionRequestsResponse>(
        `${API.adminPromotionRequests}?status=${status}&${PAGE_PARAM.limit}=${ADMIN_PROMOTION_REQUESTS_PAGE_SIZE}&${PAGE_PARAM.offset}=0`,
      ),
  });

  function selectStatus(value: string) {
    setGrantId(null);
    setSearchParams(
      (params) => {
        if (value === PROMOTION_REQUEST_STATUS.pending) params.delete(ADMIN_PROMOTION_REQUESTS_PARAM);
        else params.set(ADMIN_PROMOTION_REQUESTS_PARAM, value);
        return params;
      },
      { replace: true },
    );
  }

  const data = query.data;
  const pendingCount = data?.pending_count ?? 0;
  const history = status !== PROMOTION_REQUEST_STATUS.pending;
  const grantRequest = grantId === null ? null : (data?.requests.find((r) => r.id === grantId) ?? null);

  if (query.isLoading) return <PageState kind={UI_STATE.loading} message="Loading…" inline />;
  if (query.isError || !data) return <PageState kind={UI_STATE.error} message={COPY.loadFailed} inline />;

  // Nothing pending and no history tab picked: a quiet header, not an empty queue.
  if (pendingCount === 0 && !history) {
    return (
      <section aria-labelledby="requests-heading" className={styles.section}>
        <div className={styles.bar}>
          <h2 id="requests-heading" className={styles.sectionTitleInline}>{COPY.heading}</h2>
          <span className={styles.countPill}>{COPY.pendingCount(0)}</span>
          <button type="button" className={`${styles.plainButton} ${styles.smallButton}`} onClick={() => selectStatus(PROMOTION_REQUEST_STATUS_OPTIONS[1].value)}>
            {COPY.showHistory}
          </button>
        </div>
      </section>
    );
  }

  return (
    <section aria-labelledby="requests-heading" className={styles.section}>
      <div className={styles.bar}>
        <h2 id="requests-heading" className={styles.sectionTitleInline}>{COPY.heading}</h2>
        <span className={styles.countPill}>{COPY.pendingCount(pendingCount)}</span>
        <SegmentedControl
          ariaLabel={COPY.statusLabel}
          options={PROMOTION_REQUEST_STATUS_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
          value={status}
          onChange={selectStatus}
        />
      </div>
      <p className={styles.hintBlock}>{history ? COPY.historyHint : COPY.hint}</p>

      {data.requests.length === 0 ? (
        <ul className={styles.queue}>
          <li className={styles.rowEmpty}>
            <div className={styles.rowTitle}>{history ? COPY.nothingHere : COPY.noPending}</div>
            <div className={styles.rowMeta}>{history ? COPY.noneInStatus(status) : COPY.noPendingHint}</div>
          </li>
        </ul>
      ) : (
        <ul className={styles.queue}>
          {data.requests.map((r) => (
            <RequestRow key={r.id} request={r} selected={grantId === r.id} onGrant={(x) => setGrantId(x.id)} onDecline={setDeclining} />
          ))}
        </ul>
      )}
      {data.has_more && <p className={styles.hintBlock}>{COPY.truncated(data.requests.length, data.total)}</p>}

      {grantRequest && (
        <div className={styles.grant}>
          <h3 className={styles.sectionTitle}>{COPY.grantHeading(grantRequest.id)}</h3>
          <PromotionGrantForm
            key={grantRequest.id}
            eventId={String(grantRequest.event_id)}
            request={grantRequest}
            onNotify={showToast}
            onDone={() => setGrantId(null)}
            onCancel={() => setGrantId(null)}
          />
        </div>
      )}

      {declining && (
        <DeclineRequestModal
          request={declining}
          onClose={() => setDeclining(null)}
          onDeclined={(r) => {
            if (grantId === r.id) setGrantId(null);
            setDeclining(null);
            showToast(UI_STATE.success, COPY.declined(r.event_title));
          }}
        />
      )}
    </section>
  );
}
