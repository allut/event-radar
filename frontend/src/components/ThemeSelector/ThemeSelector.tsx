import { t } from '../../i18n';
import { THEME_OPTIONS, API } from '../../constants';
import { useThemePreference } from '../../hooks/useThemePreference';
import { setThemePreference, type ThemePreference } from '../../lib/theme';
import { isAuthenticated } from '../../lib/auth';
import { api } from '../../api/client';
import SelectMenu from '../SelectMenu';

interface ThemeSelectorProps {
  locale: string;
  ariaLabel: string;
}

// Shared between consumer (TopBar) and organizer (OrganizerTopBar) surfaces
// — the current value isn't threaded through props from a route-driven
// parent; the component owns it via useThemePreference()/lib/theme.ts
// directly, since theme has no URL dependency to stay in sync with.
//
// Once signed in as a consumer, a change also persists to the account (#253)
// via the same PATCH /users/me used for locale changes — isAuthenticated()
// only reflects the consumer session, so an organizer-only session (no
// account sync built yet, out of scope here) never fires this PATCH.
// The account column only ever holds "light"/"dark"/NULL (see #247's
// storage-shape decision) — "System" has no value of its own to send, so
// picking it sends an explicit `null` to clear back to "no preference"
// (#257), letting a prior Light/Dark account choice be durably undone.
export default function ThemeSelector({ locale, ariaLabel }: ThemeSelectorProps) {
  const preference = useThemePreference();

  function handleChange(next: ThemePreference) {
    setThemePreference(next);
    if (isAuthenticated()) {
      void api.patch(API.me, { theme_preference: next === 'system' ? null : next }).catch(() => {
        // Non-fatal — the device already applied the choice locally regardless.
      });
    }
  }

  return (
    <SelectMenu
      label=""
      value={preference}
      options={THEME_OPTIONS.map(({ value, labelKey }) => ({ value, label: t(labelKey, locale) }))}
      onChange={(next) => handleChange(next as ThemePreference)}
      ariaLabel={ariaLabel}
      variant="button"
    />
  );
}
