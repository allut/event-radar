import { LOCALES } from '../../constants';
import SelectMenu from '../SelectMenu';

interface LocaleSelectorProps {
  locale: string;
  onChange: (code: string) => void;
  ariaLabel: string;
  disabled?: boolean;
  /** C1-migrated surfaces (wayfinder #202): squares the trigger/popover. */
  sharp?: boolean;
}

export default function LocaleSelector({ locale, onChange, ariaLabel, disabled, sharp }: LocaleSelectorProps) {
  return (
    <SelectMenu
      label=""
      value={locale}
      options={LOCALES.map(({ code, label }) => ({ value: code, label }))}
      onChange={onChange}
      ariaLabel={ariaLabel}
      variant="button"
      disabled={disabled}
      sharp={sharp}
    />
  );
}
