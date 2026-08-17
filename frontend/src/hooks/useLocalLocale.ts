import { useState } from 'react';
import { getLocale, setLocale } from '../lib/auth';

/** Local locale state paired with the global setLocale side effect — the
 * locale-switcher routes (Onboarding, OrganizerDashboard, EventSubmit) all
 * mirror the same value into local state so their own tree re-renders
 * immediately on a switch, not just on the next subscribeLocale tick. */
export function useLocalLocale(): [string, (code: string) => void] {
  const [locale, setLocaleState] = useState(getLocale());

  function handleLocaleChange(code: string): void {
    setLocaleState(code);
    setLocale(code);
  }

  return [locale, handleLocaleChange];
}
