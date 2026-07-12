import { cx } from '../../utils';
import styles from './Toggle.module.css';

interface ToggleProps {
  on: boolean;
  onChange: (next: boolean) => void;
  ariaLabel: string;
  disabled?: boolean;
}

export default function Toggle({ on, onChange, ariaLabel, disabled }: ToggleProps) {
  return (
    <button
      type="button"
      className={cx(styles.toggle, on ? styles.toggleOn : styles.toggleOff)}
      onClick={() => onChange(!on)}
      disabled={disabled}
      aria-pressed={on}
      aria-label={ariaLabel}
    >
      <span className={styles.toggleKnob} />
    </button>
  );
}
