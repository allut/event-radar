import { type PersonaData } from '../../constants';
import { t, ti } from '../../i18n';
import { cx } from '../../utils';
import styles from './PersonaCard.module.css';

interface PersonaCardProps {
  persona: PersonaData;
  rank: number;
  disabled: boolean;
  locale: string;
  onToggle: () => void;
}

export default function PersonaCard({
  persona,
  rank,
  disabled,
  locale,
  onToggle,
}: PersonaCardProps) {
  const isSelected = rank > 0;

  return (
    <div className={cx(styles.card, isSelected && styles.selected)}>
      <button
        type="button"
        className={styles.mainBtn}
        onClick={onToggle}
        aria-pressed={isSelected}
        disabled={disabled}
        title={isSelected ? t('persona_btn_deselect', locale) : t('persona_btn_select', locale)}
      >
        <span className={styles.emoji} aria-hidden>{persona.emoji}</span>
        <span className={styles.name}>{persona.name}</span>
        <span className={styles.vibe}>{persona.vibe}</span>
      </button>

      {isSelected && (
        <div
          className={cx(styles.badge, rank > 1 && styles.badgeSoft)}
          aria-label={ti('persona_rank_label', locale, { rank: String(rank) })}
        >
          <span>{rank}</span>
        </div>
      )}
    </div>
  );
}
