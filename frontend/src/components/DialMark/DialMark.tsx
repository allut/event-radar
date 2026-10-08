import { cx } from '../../utils';
import styles from './DialMark.module.css';

interface DialMarkProps {
  /** Play the one-time intro (hand turns once, rim draws in). Static otherwise. */
  animated?: boolean;
  className?: string;
}

/**
 * The brand mark — a dial with a gold hand. Not an icon: Footer and AuthCard
 * render it static, the bars play the intro once per page load, and AdminShell
 * keeps its plain `◉`. Size comes from `--dial-size`, rim colour from
 * `--dial-color` (both set by the host).
 */
export default function DialMark({ animated = false, className }: DialMarkProps) {
  return (
    <svg className={cx(styles.dial, animated && styles.intro, className)} viewBox="0 0 24 24" aria-hidden="true">
      <circle className={styles.rim} cx="12" cy="12" r="10.25" fill="none" stroke="currentColor" strokeWidth="1.25" transform="rotate(-90 12 12)" />
      <circle cx="12" cy="12" r="5" fill="none" stroke="currentColor" strokeOpacity=".4" strokeWidth="1" />
      <g className={styles.hand}>
        <path d="M12 12 18.6 5.4" stroke="var(--accent-ink)" strokeWidth="1.5" />
        <circle cx="19.25" cy="4.75" r="2" fill="var(--accent-ink)" />
      </g>
      <circle cx="12" cy="12" r="1.4" fill="currentColor" />
    </svg>
  );
}
