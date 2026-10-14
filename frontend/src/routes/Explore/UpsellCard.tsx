import { t } from '../../i18n';
import styles from './UpsellCard.module.css';

interface UpsellCardProps {
  locale: string;
  onCtaClick: () => void;
}

/** Persistent sign-in upsell for anonymous /explore visitors (issue #235): a
 * full-width strip spanning the grid row above the first card, on every page
 * (issue #563) — it takes no event's slot, so the grid shows the same events
 * signed in or out. Not a banner or a dismissible overlay, so it reappears on
 * any grid re-render (e.g. a filter change). */
export default function UpsellCard({ locale, onCtaClick }: UpsellCardProps) {
  return (
    <aside className={styles.strip}>
      <div className={styles.text}>
        <h2 className={styles.headline}>{t('explore_upsell_headline', locale)}</h2>
        <p className={styles.copy}>{t('explore_upsell_body', locale)}</p>
      </div>
      <button type="button" className={styles.cta} onClick={onCtaClick}>
        {t('explore_upsell_cta', locale)}
      </button>
    </aside>
  );
}
