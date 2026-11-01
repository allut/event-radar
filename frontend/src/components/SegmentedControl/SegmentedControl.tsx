import { memo } from 'react';
import { cx } from '../../utils/style';
import type { ContentMarkerState } from '../../constants/core';
import styles from './SegmentedControl.module.css';

export interface SegmentedOption {
  value: string;
  label: string;
  /** Renders a three-state translation-progress marker after the label, plus
   * visually-hidden state text folded into the button's accessible name. */
  marker?: { state: ContentMarkerState; stateLabel: string };
}

interface SegmentedControlProps {
  options: SegmentedOption[];
  value: string;
  onChange: (value: string) => void;
  ariaLabel: string;
  /** 'plain' (default) is today's bare-hairline look. 'dial' is the gold sliding-pill treatment. */
  variant?: 'plain' | 'dial';
}

/** Two(+)-segment mode switch — used for Explore's All events / For you control.
 * memo'd — a caller re-rendering for unrelated reasons (e.g. Explore on every
 * search-box keystroke) shouldn't re-render this when its own props are
 * unchanged (Big-O audit #5, item 3.6). Requires callers to keep onChange
 * referentially stable (useCallback) for the memo to actually pay off. */
const SegmentedControl = memo(function SegmentedControl({ options, value, onChange, ariaLabel, variant = 'plain' }: SegmentedControlProps) {
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
            className={cx(styles.segBtn, opt.marker && styles.hasMarker, isActive && styles.active)}
            aria-pressed={isActive}
            onClick={() => onChange(opt.value)}
          >
            {opt.label}
            {opt.marker && (
              <>
                <span className={cx(styles.marker, styles[opt.marker.state])} aria-hidden="true" />
                <span className={styles.srOnly}>, {opt.marker.stateLabel}</span>
              </>
            )}
          </button>
        );
      })}
    </div>
  );
});

export default SegmentedControl;
