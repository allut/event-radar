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
  /** C1-migrated surfaces (wayfinder #200): squares the pill. Additive,
   * defaults off so unmigrated consumers (AdminReports, SelectField) are unaffected. */
  sharp?: boolean;
}

/** Generic multi-select pill group — modeled on LocaleSelector's pill pattern.
 * Used for category/vibe facets on /explore. */
export default function Chip({ options, selected, onToggle, ariaLabel, sharp = false }: ChipProps) {
  return (
    <div className={styles.chips} role="group" aria-label={ariaLabel}>
      {options.map(({ value, label }) => {
        const isActive = selected.includes(value);
        return (
          <button
            key={value}
            type="button"
            className={cx(styles.chip, isActive && styles.activeChip, sharp && styles.sharp)}
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
