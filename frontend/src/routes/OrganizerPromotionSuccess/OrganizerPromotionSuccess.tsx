import { useSearchParams } from 'react-router-dom';
import OrganizerTopBar from '../../components/OrganizerTopBar';
import PromotionResultCard from '../../components/PromotionResultCard';
import SeoTags from '../../components/SeoTags';
import {
  PROMOTION_CONFIRM_POLL_MAX,
  PROMOTION_CONFIRM_POLL_MS,
  PROMOTION_KIND,
  PROMOTION_PAID_STATUSES,
  PROMOTION_SUCCESS_ID_PARAM,
} from '../../constants/organizerPromotions';
import { ROUTES } from '../../constants/routes';
import { useLocalLocale } from '../../hooks/useLocalLocale';
import { useLocalePath } from '../../hooks/useLocalePath';
import { useOrganizerLogout } from '../../hooks/useOrganizerLogout';
import { useOrganizerPromotions } from '../../hooks/useOrganizerPromotions';
import { useStaticSeoMeta } from '../../hooks/useStaticSeoMeta';
import { t, ti } from '../../i18n';
import {
  formatMoney,
  formatPromoDay,
  formatPromoDays,
  formatPromoRange,
  type OrganizerPromotionItem,
} from '../../lib/organizerPromotions';
import styles from './OrganizerPromotionSuccess.module.css';

/** Where Stripe returns after a card payment (`?promotion_id=`). The webhook,
 * not this page, marks the Promotion paid, so the page asks the list until the
 * Promotion shows as paid, then confirms it; it never claims success on its own. */
export default function OrganizerPromotionSuccess() {
  const [locale, handleLocaleChange] = useLocalLocale();
  const localePath = useLocalePath();
  const handleLogout = useOrganizerLogout();
  const seoMeta = useStaticSeoMeta('promo_ok_title', locale);
  const [searchParams] = useSearchParams();
  const promotionId = Number(searchParams.get(PROMOTION_SUCCESS_ID_PARAM));

  const isPaid = (items: OrganizerPromotionItem[]) =>
    items.some((item) => item.kind === PROMOTION_KIND.promotion && item.id === promotionId && PROMOTION_PAID_STATUSES.has(item.status));
  // The webhook can trail the redirect by a few seconds: ask until it has landed.
  const { items, refetch } = useOrganizerPromotions({
    everyMs: PROMOTION_CONFIRM_POLL_MS,
    maxUpdates: PROMOTION_CONFIRM_POLL_MAX,
    until: isPaid,
  });
  const promotion = items.find((item) => item.kind === PROMOTION_KIND.promotion && item.id === promotionId);
  const paid = isPaid(items);

  const toPromotions = localePath(ROUTES.organizerPromotions);
  const toEvents = localePath(ROUTES.organizerDashboard);

  return (
    <div className={styles.page}>
      <SeoTags meta={seoMeta} />
      <OrganizerTopBar locale={locale} onLocaleChange={handleLocaleChange} onLogout={handleLogout} />
      <main className={styles.main}>
        {paid && promotion ? (
          <PromotionResultCard
            icon="check"
            live
            title={t('promo_ok_title', locale)}
            message={ti('promo_ok_msg', locale, { date: formatPromoDay(promotion.start_date, locale) })}
            recap={[
              { label: t('promo_recap_event', locale), value: promotion.event_title },
              {
                label: t('promo_recap_window', locale),
                value: `${formatPromoRange(promotion.start_date, promotion.end_date, locale)} · ${formatPromoDays(promotion.days, locale)}`,
              },
              { label: t('promo_recap_advertiser', locale), value: promotion.advertiser_legal_name },
              { label: t('promo_recap_paid', locale), value: formatMoney(promotion.price.gross_cents, locale) },
            ]}
            links={[
              { to: toPromotions, label: t('promo_view', locale), primary: true },
              { to: toEvents, label: t('promo_to_events', locale) },
            ]}
          />
        ) : (
          <PromotionResultCard
            icon="spinner"
            live
            title={t('promo_confirming_title', locale)}
            message={t('promo_confirming_msg', locale)}
            footnote={t('promo_late_note', locale)}
            links={[
              { onClick: () => void refetch(), label: t('promo_check_again', locale) },
              { to: toPromotions, label: t('promo_nav', locale) },
            ]}
          />
        )}
      </main>
    </div>
  );
}
