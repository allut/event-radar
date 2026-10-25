import { useQuery } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import { adminApi } from '../../api/client';
import { API, PAGE_PARAM, QUERY_KEYS } from '../../constants/api';
import { LOCALE_EN, UI_STATE } from '../../constants/core';
import {
  ADMIN_PROMOTIONS_PAGE_SIZE,
  ADMIN_PROMOTIONS_STATE_FILTERS,
  ADMIN_PROMOTIONS_STATE_PARAM,
  PROMOTION_COPY,
  PROMOTION_STRIPE_COPY,
  PROMOTION_TRUST_CADENCE,
  PROMOTION_TRUST_HEADING,
} from '../../constants/promotions';
import { usePageParam } from '../../hooks/usePageParam';
import { usePagedQuery } from '../../hooks/usePagedQuery';
import type { CapStripResponse, PromotionRow } from '../../lib/promotions';
import { formatDay } from '../../lib/promotions';
import EmptyState from '../../components/EmptyState';
import PageState from '../../components/PageState';
import Pager from '../../components/Pager';
import PromotionCapStrip from '../../components/PromotionCapStrip';
import PromotionRequests from '../../components/PromotionRequests';
import PromotionTrust from '../../components/PromotionTrust';
import PromotionsTable from '../../components/PromotionsTable';
import queueStyles from '../../components/shared/AdminQueue.module.css';
import { ADMIN_LOADING_LABEL } from '../../constants/admin';
import styles from './AdminPromotions.module.css';

interface PromotionsResponse {
  today: string;
  promotions: PromotionRow[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

// Admin Promotions (#600): the 14-day cap strip and every Promotion with its
// computed state. Granting happens on the event's detail page (Promotions
// tab), where the owner and window rules are known.
export default function AdminPromotions() {
  const [searchParams] = useSearchParams();
  const { setListParams } = usePageParam({ defaults: { [ADMIN_PROMOTIONS_STATE_PARAM]: '' } });
  const stateParam = searchParams.get(ADMIN_PROMOTIONS_STATE_PARAM) ?? '';
  const activeState = ADMIN_PROMOTIONS_STATE_FILTERS.some((f) => f.value === stateParam) ? stateParam : '';

  const strip = useQuery({
    queryKey: [QUERY_KEYS.adminPromotionCapStrip],
    queryFn: () => adminApi.get<CapStripResponse>(API.adminPromotionCapStrip),
  });

  const list = usePagedQuery({
    queryKey: [QUERY_KEYS.adminPromotions, activeState],
    pageSize: ADMIN_PROMOTIONS_PAGE_SIZE,
    fetchPage: ({ limit, offset }) => {
      const stateQuery = activeState ? `${ADMIN_PROMOTIONS_STATE_PARAM}=${activeState}&` : '';
      return adminApi.get<PromotionsResponse>(
        `${API.adminPromotions}?${stateQuery}${PAGE_PARAM.limit}=${limit}&${PAGE_PARAM.offset}=${offset}`,
      );
    },
    select: (data) => ({ items: data.promotions, total: data.total, offset: data.offset }),
  });

  function selectState(value: string) {
    setListParams((params) => {
      params.set(ADMIN_PROMOTIONS_STATE_PARAM, value);
      return params;
    });
  }

  return (
    <div className={styles.page}>
      <div className={styles.head}>
        <div>
          <p className={styles.eyebrow}>Admin / Commerce</p>
          <h1 className={styles.title}>Promotions</h1>
        </div>
        {strip.data && <span className={styles.today}>Today: {formatDay(strip.data.today)} · Tallinn</span>}
      </div>

      <section aria-labelledby="cap-heading" className={styles.section}>
        <h2 id="cap-heading" className={styles.sectionTitle}>{PROMOTION_COPY.capStripHeading}</h2>
        {strip.isLoading ? (
          <PageState kind={UI_STATE.loading} message={ADMIN_LOADING_LABEL} inline />
        ) : strip.isError || !strip.data ? (
          <PageState kind={UI_STATE.error} message="Couldn’t load the cap strip." inline />
        ) : (
          <PromotionCapStrip days={strip.data.days} todayIso={strip.data.today} />
        )}
      </section>

      <PromotionRequests />

      <section aria-labelledby="list-heading" className={styles.section}>
        <h2 id="list-heading" className={styles.sectionTitle}>{PROMOTION_COPY.listHeading}</h2>
        <div className={queueStyles.queueTabStrip} role="tablist">
          {ADMIN_PROMOTIONS_STATE_FILTERS.map((f) => (
            <button
              key={f.value}
              type="button"
              role="tab"
              aria-selected={activeState === f.value}
              className={activeState === f.value ? queueStyles.queueTabActive : queueStyles.queueTab}
              onClick={() => selectState(f.value)}
            >
              {f.label}
            </button>
          ))}
        </div>
        {list.isLoading ? (
          <PageState kind={UI_STATE.loading} message={ADMIN_LOADING_LABEL} inline />
        ) : list.isError ? (
          <PageState kind={UI_STATE.error} message={PROMOTION_COPY.loadFailed} inline />
        ) : list.items.length === 0 && list.total > 0 ? (
          // A past-end page about to clamp to the real last page.
          <PageState kind={UI_STATE.loading} message={ADMIN_LOADING_LABEL} inline />
        ) : list.items.length === 0 ? (
          <EmptyState admin title={PROMOTION_COPY.noPromotions} message={PROMOTION_COPY.noPromotionsHint} />
        ) : (
          <PromotionsTable rows={list.items} ariaBusy={list.isPlaceholderData} />
        )}
        <p className={styles.listHint}>{PROMOTION_STRIPE_COPY.listHint}</p>
        {/* The pager's strings come from shared/i18n even here: docs/frontend.md "Admin Console" */}
        <Pager {...list.pagerProps} locale={LOCALE_EN} liveNoun="items" className={queueStyles.queuePager} />
      </section>

      <section aria-labelledby="trust-review-heading" className={styles.section}>
        <div className={styles.trustHead}>
          <h2 id="trust-review-heading" className={styles.sectionTitleInline}>{PROMOTION_TRUST_HEADING}</h2>
          <span className={styles.trustCadence}>{PROMOTION_TRUST_CADENCE}</span>
        </div>
        <PromotionTrust />
      </section>
    </div>
  );
}
