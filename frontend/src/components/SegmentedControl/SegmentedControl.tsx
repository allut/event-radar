import { cx } from '../../utils';
import styles from './SegmentedControl.module.css';

export interface SegmentedOption {
  value: string;
  label: string;
  /** Renders a small filled dot after the label — e.g. to signal an
   * optional-but-filled-in language tab has content. */
  dot?: boolean;
}

interface SegmentedControlProps {
  options: SegmentedOption[];
  value: string;
  onChange: (value: string) => void;
  ariaLabel: string;
  /** 'plain' (default) is today's bare-hairline look. 'dial' is the gold sliding-pill treatment. */
  variant?: 'plain' | 'dial';
}

/** Two(+)-segment mode switch — used for Explore's All events / For you control. */
export default function SegmentedControl({ options, value, onChange, ariaLabel, variant = 'plain' }: SegmentedControlProps) {
  const isDial = variant === 'dial';
  const activeIndex = options.findIndex((o) => o.value === value);
  return (
    <div
      className={cx(styles.seg, isDial && styles.segDial)}
      role="group"
      aria-label={ariaLabel}
      style={isDial ? ({ '--seg-count': options.length, '--seg-index': activeIndex } as React.CSSProperties) : undefined}
    >
      {isDial && activeIndex >= 0 && <span className={styles.indicator} aria-hidden />}
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
            {opt.dot && <span className={cx(styles.dot, isDial && styles.blip)} aria-hidden="true" />}
          </button>
        );
      })}
    </div>
  );
}
