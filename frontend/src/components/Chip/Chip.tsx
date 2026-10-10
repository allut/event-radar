import { useMemo } from 'react';
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

/** Generic multi-select pill group — joined-pill pattern.
 * Used for category/vibe facets on /explore. */
export default function Chip({ options, selected, onToggle, ariaLabel }: ChipProps) {
  // Explore's category facet renders 14x14 options.includes(selected) per
  // render — a Set turns that into O(1) membership (Big-O audit #5, item 3.4).
  const selectedSet = useMemo(() => new Set(selected), [selected]);
  return (
    <div className={styles.chips} role="group" aria-label={ariaLabel}>
      {options.map(({ value, label }) => {
        const isActive = selectedSet.has(value);
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
