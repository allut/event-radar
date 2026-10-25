import { useEffect, useId, useState } from 'react';
import { Link, Navigate, useSearchParams } from 'react-router-dom';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { organizerApi } from '../../api/client';
import EmptyState from '../../components/EmptyState';
import OrganizerTopBar from '../../components/OrganizerTopBar';
import PageState from '../../components/PageState';
import SeoTags from '../../components/SeoTags';
import Toast from '../../components/Toast';
import { API, QUERY_KEYS } from '../../constants/api';
import { UI_STATE } from '../../constants/core';
import {
  PROMOTION_DAY_NET_CENTS,
  PROMOTION_EVENT_PARAM,
  PROMOTION_RUNNING_STATUSES,
  PROMOTION_VAT_PERCENT,
} from '../../constants/organizerPromotions';
import { ROUTES } from '../../constants/routes';
import { useLocalLocale } from '../../hooks/useLocalLocale';
import { useLocalePath } from '../../hooks/useLocalePath';
import { useOrganizerLogout } from '../../hooks/useOrganizerLogout';
import { useOrganizerPromotions } from '../../hooks/useOrganizerPromotions';
import { useStaticSeoMeta } from '../../hooks/useStaticSeoMeta';
import { useToast } from '../../hooks/useToast';
import { t, ti } from '../../i18n';
import { formatMoney, grossCents, type OrganizerPromotionItem } from '../../lib/organizerPromotions';
import PromotionRow from './PromotionRow';
import styles from './OrganizerPromotions.module.css';

const EXPLAINER_GETS = [
  ['promo_get_explore_title', 'promo_get_explore_desc'],
  ['promo_get_daily5_title', 'promo_get_daily5_desc'],
  ['promo_get_digest_title', 'promo_get_digest_desc'],
] as const;

/** The list item a row's badge points at: the event's open item, else its newest. */
function itemForEvent(items: OrganizerPromotionItem[], eventId: number): OrganizerPromotionItem | undefined {
  const forEvent = items.filter((item) => item.event_id === eventId);
  return forEvent.find((item) => PROMOTION_RUNNING_STATUSES.has(item.status) || item.status === 'requested') ?? forEvent[0];
}

/** Organizer Promotions (#614, #616): what a Promotion is and costs, then one
 * list of the Organizer's requests and Promotions, newest first, with withdraw,
 * the invoice link and the per-day report. The route 404s while the offer flag
 * is off, and the page then sends the Organizer back to Your events. */
export default function OrganizerPromotions() {
  const [locale, handleLocaleChange] = useLocalLocale();
  const localePath = useLocalePath();
  const handleLogout = useOrganizerLogout();
  const queryClient = useQueryClient();
  const seoMeta = useStaticSeoMeta('promo_nav', locale);
  const { toast, showToast } = useToast();
  const [searchParams] = useSearchParams();
  const focusEventId = Number(searchParams.get(PROMOTION_EVENT_PARAM));

  const { items, isLoading, isError, notOffered } = useOrganizerPromotions();
  const [explainOpen, setExplainOpen] = useState(true);
  const [openReport, setOpenReport] = useState<string | null>(null);
  const [confirmWithdraw, setConfirmWithdraw] = useState<number | null>(null);
  const explainId = useId();
  const howId = useId();
  const listId = useId();

  const withdraw = useMutation({
    mutationFn: (requestId: number) => organizerApi.post(API.organizerPromotionWithdraw(requestId)),
    onSettled: () => {
      setConfirmWithdraw(null);
      void queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.organizerPromotions] });
      void queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.organizerEvents] });
      void queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.organizerClaimEvents] });
    },
    onError: () => showToast(UI_STATE.error, t('generic_error', locale)),
  });

  // Arriving from an event row's badge: scroll to and focus that event's item.
  const target = Number.isNaN(focusEventId) || focusEventId === 0 ? undefined : itemForEvent(items, focusEventId);
  const targetId = target ? `promotion-${target.kind}-${target.id}` : null;
  useEffect(() => {
    if (!targetId) return;
    const node = document.getElementById(targetId);
    node?.scrollIntoView({ block: 'center' });
    node?.focus({ preventScroll: true });
  }, [targetId]);

  const dayNet = formatMoney(PROMOTION_DAY_NET_CENTS, locale);
  const dayGross = formatMoney(grossCents(PROMOTION_DAY_NET_CENTS, PROMOTION_VAT_PERCENT), locale);

  return (
    <div className={styles.page}>
      <SeoTags meta={seoMeta} />
      <OrganizerTopBar locale={locale} onLocaleChange={handleLocaleChange} onLogout={handleLogout} />

      <main className={styles.main}>
        <header className={styles.masthead}>
          <h1 className={styles.heading}>{t('promo_nav', locale)}</h1>
          <p className={styles.sub}>{t('promo_page_sub', locale)}</p>
        </header>

        {notOffered ? (
          // The offer is off: every Promotions route 404s, so leave for Your events.
          <Navigate to={localePath(ROUTES.organizerDashboard)} replace />
        ) : (
          <>
            <section className={styles.explain} aria-labelledby={howId}>
              <div className={styles.explainHead}>
                <h2 className={styles.explainTitle} id={howId}>{t('promo_how_title', locale)}</h2>
                <button
                  type="button"
                  className={styles.textButton}
                  aria-expanded={explainOpen}
                  aria-controls={explainId}
                  onClick={() => setExplainOpen((open) => !open)}
                >
                  {t(explainOpen ? 'promo_hide' : 'promo_show', locale)}
                </button>
              </div>
              {explainOpen && (
                <div id={explainId} className={styles.explainBody}>
                  <p className={styles.lede}>{ti('promo_what_is', locale, { label: t('sponsored_label', locale) })}</p>
                  <div>
                    <h3 className={styles.eyebrowSm}>{t('promo_gets_title', locale)}</h3>
                    <ul className={styles.gets}>
                      {EXPLAINER_GETS.map(([nameKey, descKey]) => (
                        <li key={nameKey} className={styles.get}>
                          <span className={styles.getName}>{t(nameKey, locale)}</span>
                          <span className={styles.getDesc}>{t(descKey, locale)}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                  <dl className={styles.facts}>
                    <div className={styles.fact}>
                      <dt>{t('promo_fact_price', locale)}</dt>
                      <dd className={styles.big}>{ti('promo_price_per_day', locale, { net: dayNet, gross: dayGross })}</dd>
                    </div>
                    <div className={styles.fact}>
                      <dt>{t('promo_fact_who', locale)}</dt>
                      <dd>{t('promo_fact_who_value', locale)}</dd>
                    </div>
                    <div className={styles.fact}>
                      <dt>{t('promo_fact_length', locale)}</dt>
                      <dd>{t('promo_fact_length_value', locale)}</dd>
                    </div>
                  </dl>
                  <div className={styles.promise}>
                    <strong>{t('promo_promise_1', locale)}</strong>
                    <span>{t('promo_promise_2', locale)}</span>
                  </div>
                </div>
              )}
            </section>

            <div className={styles.listHead}>
              <h2 className={styles.listTitle} id={listId}>{t('promo_list_title', locale)}</h2>
              <span className={styles.sub}>{t('promo_list_sub', locale)}</span>
            </div>

            {isLoading ? (
              <PageState kind={UI_STATE.loading} message={t('loading', locale)} inline />
            ) : isError ? (
              <PageState kind={UI_STATE.error} message={t('promo_list_error', locale)} inline />
            ) : items.length === 0 ? (
              <div className={styles.empty}>
                <EmptyState title={t('promo_empty_title', locale)} message={t('promo_empty_msg', locale)} />
                <Link to={localePath(ROUTES.organizerDashboard)} className={styles.smallBtn}>
                  {t('promo_to_events', locale)}
                </Link>
              </div>
            ) : (
              <ul className={styles.list} aria-labelledby={listId}>
                {items.map((item) => {
                  const key = `${item.kind}-${item.id}`;
                  return (
                    <PromotionRow
                      key={key}
                      item={item}
                      locale={locale}
                      reportOpen={openReport === key}
                      confirming={confirmWithdraw === item.id && item.kind === 'request'}
                      withdrawing={withdraw.isPending}
                      onToggleReport={() => setOpenReport((open) => (open === key ? null : key))}
                      onAskWithdraw={() => setConfirmWithdraw(item.id)}
                      onCancelWithdraw={() => setConfirmWithdraw(null)}
                      onWithdraw={() => withdraw.mutate(item.id)}
                    />
                  );
                })}
              </ul>
            )}
          </>
        )}
      </main>

      {toast.status !== UI_STATE.idle && <Toast status={toast.status} message={toast.message} />}
    </div>
  );
}
