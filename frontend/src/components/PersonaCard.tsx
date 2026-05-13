import { type PersonaData } from '../constants';
import styles from './PersonaCard.module.css';

export type { PersonaData };

interface Props {
  persona: PersonaData;
  role: 'none' | 'primary' | 'secondary';
  primaryTaken: boolean;
  onClickPrimary: () => void;
  onClickSecondary: () => void;
}

export default function PersonaCard({
  persona,
  role,
  primaryTaken,
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
        title={isPrimary ? 'Deselect' : 'Set as primary'}
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
          title="Set as secondary"
        >
          + 2nd
        </button>
      )}

      {isPrimary && (
        <div className={styles.badge} aria-label="Primary">
          <span>Primary</span>
        </div>
      )}

      {isSecondary && (
        <button
          type="button"
          className={styles.secondaryBadge}
          onClick={onClickSecondary}
          title="Remove secondary"
          aria-label="Secondary — click to remove"
        >
          2nd ×
        </button>
      )}
    </div>
  );
}
