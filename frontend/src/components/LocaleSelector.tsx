import { LOCALES } from '../constants';
import { cx } from '../utils';
import styles from './LocaleSelector.module.css';

interface LocaleSelectorProps {
  locale: string;
  onChange: (code: string) => void;
  ariaLabel: string;
  disabled?: boolean;
}

export default function LocaleSelector({ locale, onChange, ariaLabel, disabled }: LocaleSelectorProps) {
  return (
    <div className={styles.localePills} role="group" aria-label={ariaLabel}>
      {LOCALES.map(({ code, label }) => (
        <button
          key={code}
          type="button"
          className={cx(styles.localePill, locale === code && styles.activeLocale)}
          onClick={() => onChange(code)}
          aria-pressed={locale === code}
          disabled={disabled}
        >
          {label}
        </button>
      ))}
    </div>
  );
}
