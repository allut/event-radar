import { type PersonaData } from '../constants';
import { t } from '../i18n';
import styles from './PersonaCard.module.css';

export type { PersonaData };

interface Props {
  persona: PersonaData;
  role: 'none' | 'primary' | 'secondary';
  primaryTaken: boolean;
  locale: string;
  onClickPrimary: () => void;
  onClickSecondary: () => void;
}

export default function PersonaCard({
  persona,
  role,
  primaryTaken,
  locale,
  onClickPrimary,
  onClickSecondary,
}: Props) {
  const isPrimary = role === 'primary';
  const isSecondary = role === 'secondary';
  const isNone = role === 'none';

  return (
    <div
      className={[
        styles.card,
        isPrimary ? styles.primary : '',
        isSecondary ? styles.secondary : '',
      ].join(' ')}
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

      {primaryTaken && isNone && (
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
