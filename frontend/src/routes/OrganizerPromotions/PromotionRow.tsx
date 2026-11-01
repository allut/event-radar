import { useId } from 'react';
import PromotionBadge from '../../components/PromotionBadge';
import { PROMOTION_KIND, PROMOTION_LIST_STATUS } from '../../constants/organizerPromotions';
import { t, ti } from '../../i18n';
import {
  formatPromoDay,
  formatPromoDays,
  formatPromoRange,
  pauseReasonKey,
  type OrganizerPromotionItem,
} from '../../lib/organizerPromotions';
import { cx } from '../../utils/style';
import PromotionReport from './PromotionReport';
import styles from './OrganizerPromotions.module.css';

// Statuses with complete days to report on.
const REPORT_STATUSES: ReadonlySet<string> = new Set([
  PROMOTION_LIST_STATUS.live,
  PROMOTION_LIST_STATUS.paused,
  PROMOTION_LIST_STATUS.finished,
  PROMOTION_LIST_STATUS.endedEarly,
]);

interface PromotionRowProps {
  item: OrganizerPromotionItem;
  locale: string;
  reportOpen: boolean;
  confirming: boolean;
  withdrawing: boolean;
  onToggleReport: () => void;
  onAskWithdraw: () => void;
  onCancelWithdraw: () => void;
  onWithdraw: () => void;
}

/** The one-line reason under a row: what the status means, in plain words. */
function reasonFor(item: OrganizerPromotionItem, locale: string): { text: string; tone: '' | 'warn' | 'bad' } {
  switch (item.status) {
    case PROMOTION_LIST_STATUS.requested:
      return { text: t('promo_reason_requested', locale), tone: '' };
    case PROMOTION_LIST_STATUS.declined:
      return {
        text: item.decline_reason
          ? ti('promo_reason_declined', locale, { reason: item.decline_reason })
          : t('promo_reason_declined_plain', locale),
        tone: 'bad',
      };
    case PROMOTION_LIST_STATUS.awaitingPayment:
      return {
        text: item.billing_email
          ? ti('promo_reason_awaiting_payment_to', locale, { email: item.billing_email })
          : t('promo_reason_awaiting_payment', locale),
        tone: 'warn',
      };
    case PROMOTION_LIST_STATUS.awaitingCheckout:
      return { text: t('promo_reason_awaiting_checkout', locale), tone: 'warn' };
    case PROMOTION_LIST_STATUS.scheduled:
      return { text: ti('promo_reason_scheduled', locale, { date: formatPromoDay(item.start_date, locale) }), tone: '' };
    case PROMOTION_LIST_STATUS.live:
      return { text: ti('promo_reason_live', locale, { date: formatPromoDay(item.end_date, locale) }), tone: '' };
    case PROMOTION_LIST_STATUS.paused:
      return {
        text: ti('promo_reason_paused', locale, {
          reason: t(`promo_why_${pauseReasonKey(item.paused_reason)}`, locale),
        }),
        tone: 'warn',
      };
    case PROMOTION_LIST_STATUS.finished:
      return {
        text: ti('promo_reason_finished', locale, { range: formatPromoRange(item.start_date, item.end_date, locale) }),
        tone: '',
      };
    case PROMOTION_LIST_STATUS.endedEarly:
      return { text: t('promo_reason_ended_early', locale), tone: 'bad' };
    default:
      return { text: t('promo_reason_cancelled', locale), tone: '' };
  }
}

/** One request or Promotion: title, window, advertiser, status badge, the
 * reason in plain words and its actions (withdraw, invoice, daily report). */
export default function PromotionRow({
  item,
  locale,
  reportOpen,
  confirming,
  withdrawing,
  onToggleReport,
  onAskWithdraw,
  onCancelWithdraw,
  onWithdraw,
}: PromotionRowProps) {
  const reportId = useId();
  const reason = reasonFor(item, locale);
  const canReport = item.kind === PROMOTION_KIND.promotion && item.has_report && REPORT_STATUSES.has(item.status);
  const canWithdraw = item.kind === PROMOTION_KIND.request && item.can_withdraw;
  const hasActions = (canWithdraw && !confirming) || Boolean(item.invoice_url) || canReport;

  return (
    <li id={`promotion-${item.kind}-${item.id}`} className={styles.pm} tabIndex={-1}>
      <div className={styles.pmTop}>
        <div className={styles.pmMain}>
          <span className={styles.pmTitle}>{item.event_title}</span>
          <span className={styles.rowMeta}>
            {formatPromoRange(item.start_date, item.end_date, locale)} · {formatPromoDays(item.days, locale)} ·{' '}
            {item.advertiser_legal_name}
          </span>
        </div>
        <PromotionBadge status={item.status} locale={locale} />
      </div>

      <p className={cx(styles.pmReason, reason.tone === 'warn' && styles.warn, reason.tone === 'bad' && styles.bad)}>
        {reason.text}
      </p>

      {confirming && (
        <div className={styles.pmConfirm} role="alertdialog" aria-label={t('promo_withdraw_q', locale)}>
          <span>{t('promo_withdraw_q', locale)}</span>
          <button type="button" className={cx(styles.smallBtn, styles.dangerBtn)} onClick={onWithdraw} disabled={withdrawing} autoFocus>
            {t('promo_withdraw_yes', locale)}
          </button>
          <button type="button" className={styles.smallBtn} onClick={onCancelWithdraw}>
            {t('promo_withdraw_keep', locale)}
          </button>
        </div>
      )}

      {hasActions && (
        <div className={styles.pmActions}>
          {canWithdraw && !confirming && (
            <button type="button" className={styles.smallBtn} onClick={onAskWithdraw}>
              {t('promo_withdraw', locale)}
            </button>
          )}
          {item.invoice_url && (
            <a
              className={styles.smallBtn}
              href={item.invoice_url}
              target="_blank"
              rel="noopener noreferrer"
              aria-label={ti('promo_open_invoice_aria', locale, { title: item.event_title })}
            >
              {t('promo_invoice', locale)} <span aria-hidden="true">↗</span>
            </a>
          )}
          {canReport && (
            <button
              type="button"
              className={styles.smallBtn}
              aria-expanded={reportOpen}
              aria-controls={reportId}
              onClick={onToggleReport}
            >
              {t('promo_report_toggle', locale)}
              <svg className={styles.caret} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
                <path d="M3.5 6l4.5 4.5L12.5 6" />
              </svg>
            </button>
          )}
        </div>
      )}

      {reportOpen && canReport && (
        <PromotionReport
          promotionId={item.id}
          panelId={reportId}
          title={item.event_title}
          running={item.status === PROMOTION_LIST_STATUS.live || item.status === PROMOTION_LIST_STATUS.paused}
          locale={locale}
        />
      )}
    </li>
  );
}
