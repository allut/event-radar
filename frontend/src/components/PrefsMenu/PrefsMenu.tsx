import { LOCALES } from '../../_generated/sharedConstants';
import { THEME_OPTIONS } from '../../constants/theme';
import { t } from '../../i18n';
import { cx } from '../../utils';
import { useDropdown } from '../../hooks/useDropdown';
import { useResolvedTheme } from '../../hooks/useResolvedTheme';
import { setThemeOverride, type ResolvedTheme } from '../../lib/theme';
import styles from '../shared/Bar.module.css';

interface PrefsRowsProps {
  locale: string;
  onLocaleChange: (code: string) => void;
  localeDisabled?: boolean;
  onPicked?: () => void;
}

/** Language + Theme rows of joined square buttons — shared by the popover and the phone drawer. */
export function PrefsRows({ locale, onLocaleChange, localeDisabled, onPicked }: PrefsRowsProps) {
  const resolved = useResolvedTheme();
  return (
    <>
      <div className={styles.popLabel}>{t('section_language', locale)}</div>
      <div className={styles.seg} role="group" aria-label={t('section_language', locale)}>
        {LOCALES.map(({ code, label }) => (
          <button
            key={code}
            type="button"
            aria-pressed={code === locale}
            disabled={localeDisabled}
            onClick={() => {
              onLocaleChange(code);
              onPicked?.();
            }}
          >
            {label}
          </button>
        ))}
      </div>
      <div className={styles.popLabel}>{t('section_theme', locale)}</div>
      <div className={styles.seg} role="group" aria-label={t('section_theme', locale)}>
        {THEME_OPTIONS.map(({ value, labelKey }) => (
          <button
            key={value}
            type="button"
            aria-pressed={value === resolved}
            onClick={() => {
              setThemeOverride(value as ResolvedTheme);
              onPicked?.();
            }}
          >
            {t(labelKey, locale)}
          </button>
        ))}
      </div>
    </>
  );
}

interface PrefsMenuProps {
  locale: string;
  onLocaleChange: (code: string) => void;
  localeDisabled?: boolean;
}

// The trigger glyph is a fixed half-filled circle that never reflects the
// current theme, so the prerendered HTML (built under whatever theme the build
// machine has) can't show the wrong one.
export default function PrefsMenu({ locale, onLocaleChange, localeDisabled }: PrefsMenuProps) {
  const { open, setOpen, rootRef, popRef, triggerRef } = useDropdown('button[aria-pressed="true"]');
  return (
    <div className={styles.anchor} ref={rootRef}>
      <button
        ref={triggerRef}
        type="button"
        className={styles.trigger}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={t('prefs_menu', locale)}
        onClick={() => setOpen((v) => !v)}
      >
        {locale.toUpperCase()}
        <svg className={styles.glyph} viewBox="0 0 16 16" aria-hidden="true">
          <circle cx="8" cy="8" r="6.25" fill="none" stroke="currentColor" strokeWidth="1.25" />
          <path d="M8 1.75A6.25 6.25 0 0 1 8 14.25Z" fill="currentColor" />
        </svg>
      </button>
      {open && (
        <div className={cx(styles.pop, styles.prefsPop)} ref={popRef} role="dialog" aria-label={t('prefs_menu', locale)}>
          <PrefsRows locale={locale} onLocaleChange={onLocaleChange} localeDisabled={localeDisabled} />
        </div>
      )}
    </div>
  );
}
