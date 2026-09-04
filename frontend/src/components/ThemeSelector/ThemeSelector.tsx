import { t } from '../../i18n';
import { THEME_OPTIONS } from '../../constants';
import { useThemePreference } from '../../hooks/useThemePreference';
import { setThemePreference, type ThemePreference } from '../../lib/theme';
import SelectMenu from '../SelectMenu';

interface ThemeSelectorProps {
  locale: string;
  ariaLabel: string;
}

// Local-storage-driven for now (account sync arrives in a follow-up ticket,
// #247) — unlike LocaleSelector, the current value isn't threaded through
// props from a route-driven parent; the component owns it via
// useThemePreference()/lib/theme.ts directly, since theme has no URL
// dependency to stay in sync with.
export default function ThemeSelector({ locale, ariaLabel }: ThemeSelectorProps) {
  const preference = useThemePreference();
  return (
    <SelectMenu
      label=""
      value={preference}
      options={THEME_OPTIONS.map(({ value, labelKey }) => ({ value, label: t(labelKey, locale) }))}
      onChange={(next) => setThemePreference(next as ThemePreference)}
      ariaLabel={ariaLabel}
      variant="button"
    />
  );
}
