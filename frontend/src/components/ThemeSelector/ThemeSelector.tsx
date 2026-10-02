import { useCallback, useMemo } from 'react';
import { t } from '../../i18n';
import { THEME_OPTIONS } from '../../constants';
import { useResolvedTheme } from '../../hooks/useResolvedTheme';
import { setThemeOverride, type ResolvedTheme } from '../../lib/theme';
import SelectMenu from '../SelectMenu';

interface ThemeSelectorProps {
  locale: string;
  ariaLabel: string;
}

// Shared between consumer (TopBar) and organizer (OrganizerTopBar) surfaces
// — the current value isn't threaded through props from a route-driven
// parent; the component owns it via useResolvedTheme()/lib/theme.ts
// directly, since theme has no URL dependency to stay in sync with.
//
// The override is scoped to this browser only, never an account (ADR
// 0003) — signing in on either track neither reads nor writes a theme, so
// there's no PATCH branch here to keep in sync with an auth track.
export default function ThemeSelector({ locale, ariaLabel }: ThemeSelectorProps) {
  const resolved = useResolvedTheme();

  const handleChange = useCallback((next: string) => {
    setThemeOverride(next as ResolvedTheme);
  }, []);

  // Stable per locale — rebuilding on every render defeats SelectMenu's
  // memo (Big-O audit #5, item 3.6).
  const options = useMemo(
    () => THEME_OPTIONS.map(({ value, labelKey }) => ({ value, label: t(labelKey, locale) })),
    [locale],
  );

  return (
    <SelectMenu
      label=""
      value={resolved}
      options={options}
      onChange={handleChange}
      ariaLabel={ariaLabel}
      variant="button"
    />
  );
}
