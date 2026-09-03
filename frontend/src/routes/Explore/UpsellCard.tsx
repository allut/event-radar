import { t } from '../../i18n';
import styles from './UpsellCard.module.css';

interface UpsellCardProps {
  locale: string;
  onCtaClick: () => void;
}

/** Persistent sign-in upsell, injected into the results grid as an EventCard
 * sibling for anonymous /explore visitors (issue #235) — not a banner or a
 * dismissible overlay, so it reappears on any grid re-render (e.g. a filter
 * change) same as any other card. */
export default function UpsellCard({ locale, onCtaClick }: UpsellCardProps) {
  return (
    <article className={styles.card}>
      <div className={styles.body}>
        <h2 className={styles.headline}>{t('explore_upsell_headline', locale)}</h2>
        <p className={styles.copy}>{t('explore_upsell_body', locale)}</p>
        <button type="button" className={styles.cta} onClick={onCtaClick}>
          {t('explore_upsell_cta', locale)}
        </button>
      </div>
    </article>
  );
}
