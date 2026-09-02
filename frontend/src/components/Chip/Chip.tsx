import { cx } from '../../utils';
import styles from './Chip.module.css';

export interface ChipOption {
  value: string;
  label: string;
}

interface ChipProps {
  options: ChipOption[];
  selected: string[];
  onToggle: (value: string) => void;
  ariaLabel: string;
}

/** Generic multi-select pill group — modeled on LocaleSelector's pill pattern.
 * Used for category/vibe facets on /explore. */
export default function Chip({ options, selected, onToggle, ariaLabel }: ChipProps) {
  return (
    <div className={styles.chips} role="group" aria-label={ariaLabel}>
      {options.map(({ value, label }) => {
        const isActive = selected.includes(value);
        return (
          <button
            key={value}
            type="button"
            className={cx(styles.chip, isActive && styles.activeChip)}
            onClick={() => onToggle(value)}
            aria-pressed={isActive}
          >
            {label}
          </button>
        );
      })}
    </div>
  );
}
