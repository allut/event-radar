import { cx } from '../../utils';
import styles from './SegmentedControl.module.css';

export interface SegmentedOption {
  value: string;
  label: string;
}

interface SegmentedControlProps {
  options: SegmentedOption[];
  value: string;
  onChange: (value: string) => void;
  ariaLabel: string;
}

/** Two(+)-segment mode switch — used for Explore's All events / For you control. */
export default function SegmentedControl({ options, value, onChange, ariaLabel }: SegmentedControlProps) {
  return (
    <div className={styles.seg} role="group" aria-label={ariaLabel}>
      {options.map((opt) => {
        const isActive = opt.value === value;
        return (
          <button
            key={opt.value}
            type="button"
            className={cx(styles.segBtn, isActive && styles.active)}
            aria-pressed={isActive}
            onClick={() => onChange(opt.value)}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}
