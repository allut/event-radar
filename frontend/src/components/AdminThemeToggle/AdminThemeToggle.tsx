import { ADMIN_THEME_OPTIONS } from '../../constants';
import { useThemePreference } from '../../hooks/useThemePreference';
import { setThemePreference, type ThemePreference } from '../../lib/theme';
import SelectMenu from '../SelectMenu';

// Hoisted — neither closes over props/state, so both are referentially
// stable forever (Big-O audit #5, item 3.6); keeps SelectMenu's memo effective.
const ADMIN_THEME_SELECT_OPTIONS = ADMIN_THEME_OPTIONS.map(({ value, label }) => ({ value, label }));
function handleAdminThemeChange(next: string): void {
  setThemePreference(next as ThemePreference);
}

// Admin console's own theme control (#255) — localStorage-only, no account
// sync (the console has no accounts), unlike ThemeSelector (TopBar/
// OrganizerTopBar), which also PATCHes a signed-in account. Reuses the same
// SelectMenu + lib/theme.ts resolution engine, just without ThemeSelector's
// auth-track PATCH branches.
// openUpward — the trigger sits at the bottom of AdminShell's foot area, so
// a default downward popover would spill past the viewport and get clipped.
export default function AdminThemeToggle() {
  const preference = useThemePreference();

  return (
    <SelectMenu
      label=""
      value={preference}
      options={ADMIN_THEME_SELECT_OPTIONS}
      onChange={handleAdminThemeChange}
      ariaLabel="Theme"
      variant="button"
      openUpward
    />
  );
}
