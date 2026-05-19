import { type PersonaData } from '../constants';
import { t } from '../i18n';
import { cx } from '../utils';
import styles from './PersonaCard.module.css';

interface PersonaCardProps {
  persona: PersonaData;
  role: 'none' | 'primary' | 'secondary';
  isPrimaryTaken: boolean;
  locale: string;
  onClickPrimary: () => void;
  onClickSecondary: () => void;
}

export default function PersonaCard({
  persona,
  role,
  isPrimaryTaken,
  locale,
  onClickPrimary,
  onClickSecondary,
}: PersonaCardProps) {
  const isPrimary = role === 'primary';
  const isSecondary = role === 'secondary';
  const isNone = role === 'none';

  return (
    <div
      className={cx(styles.card, isPrimary && styles.primary, isSecondary && styles.secondary)}
    >
      <button
        type="button"
        className={styles.mainBtn}
        onClick={onClickPrimary}
        aria-pressed={isPrimary}
        title={isPrimary ? t('persona_btn_deselect', locale) : t('persona_btn_set_primary', locale)}
      >
        <span className={styles.emoji} aria-hidden>{persona.emoji}</span>
        <span className={styles.name}>{persona.name}</span>
        <span className={styles.vibe}>{persona.vibe}</span>
      </button>

      {isPrimaryTaken && isNone && (
        <button
          type="button"
          className={styles.secondaryBtn}
          onClick={onClickSecondary}
          title={t('persona_btn_set_secondary', locale)}
        >
          {t('persona_btn_add_secondary', locale)}
        </button>
      )}

      {isPrimary && (
        <div className={styles.badge} aria-label={t('persona_primary', locale)}>
          <span>{t('persona_primary', locale)}</span>
        </div>
      )}

      {isSecondary && (
        <button
          type="button"
          className={styles.secondaryBadge}
          onClick={onClickSecondary}
          title={t('persona_btn_remove_secondary', locale)}
          aria-label={t('persona_badge_secondary_label', locale)}
        >
          {t('persona_badge_secondary_text', locale)}
        </button>
      )}
    </div>
  );
}
