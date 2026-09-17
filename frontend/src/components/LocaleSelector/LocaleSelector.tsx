import { LOCALES } from '../../constants';
import SelectMenu from '../SelectMenu';

interface LocaleSelectorProps {
  locale: string;
  onChange: (code: string) => void;
  ariaLabel: string;
  disabled?: boolean;
}

// Hoisted — LOCALES is constant, so this never needs to be rebuilt per
// render (Big-O audit #5, item 3.6); also keeps SelectMenu's memo effective.
const LOCALE_OPTIONS = LOCALES.map(({ code, label }) => ({ value: code, label }));

export default function LocaleSelector({ locale, onChange, ariaLabel, disabled }: LocaleSelectorProps) {
  return (
    <SelectMenu
      label=""
      value={locale}
      options={LOCALE_OPTIONS}
      onChange={onChange}
      ariaLabel={ariaLabel}
      variant="button"
      disabled={disabled}
    />
  );
}
