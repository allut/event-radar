import { Link } from 'react-router-dom';
import { SPONSORED_EXPLANATION_KEY, SPONSORED_RANKING_TARGET, type SponsoredExplanation } from '../../constants/sponsored';
import { t } from '../../i18n';
import { useLocalePath } from '../../hooks/useLocalePath';
import styles from './SponsoredSlot.module.css';

export interface SponsoredInfo {
  /** The business that paid, as snapshotted at sale. */
  advertiser: string;
  explanation: SponsoredExplanation;
}

interface SponsoredCaptionProps {
  advertiser: string;
  locale: string;
  open: boolean;
  panelId: string;
  onToggle: () => void;
}

/** The ad caption row: label, who paid, and the "Why?" text button. Sits above
 * the card image, outside the stretched link's overlay. */
export function SponsoredCaption({ advertiser, locale, open, panelId, onToggle }: SponsoredCaptionProps) {
  return (
    <div className={styles.caption}>
      <strong className={styles.label}>{t('sponsored_label', locale)}</strong>
      <span className={styles.advertiser}>· {advertiser}</span>
      <button type="button" className={styles.why} aria-expanded={open} aria-controls={panelId} onClick={onToggle}>
        {t('sponsored_why', locale)}
      </button>
    </div>
  );
}

interface SponsoredPanelProps {
  explanation: SponsoredExplanation;
  locale: string;
  id: string;
  onClose: () => void;
}

/** The explanation panel laid over the card body (never the caption). */
export function SponsoredPanel({ explanation, locale, id, onClose }: SponsoredPanelProps) {
  const localePath = useLocalePath();
  return (
    <div className={styles.panel} id={id}>
      <p className={styles.explanation}>{t(SPONSORED_EXPLANATION_KEY[explanation], locale)}</p>
      <Link to={localePath(SPONSORED_RANKING_TARGET)} className={styles.rankingLink}>
        {t('ranking_link', locale)}
      </Link>
      <button type="button" className={styles.close} onClick={onClose}>
        {t('sponsored_close', locale)}
      </button>
    </div>
  );
}
