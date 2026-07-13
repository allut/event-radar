import { LOCALES } from '../../constants';
import SelectMenu from '../SelectMenu';

interface LocaleSelectorProps {
  locale: string;
  onChange: (code: string) => void;
  ariaLabel: string;
  disabled?: boolean;
}

export default function LocaleSelector({ locale, onChange, ariaLabel, disabled }: LocaleSelectorProps) {
  return (
    <SelectMenu
      label=""
      value={locale}
      options={LOCALES.map(({ code, label }) => ({ value: code, label }))}
      onChange={onChange}
      ariaLabel={ariaLabel}
      variant="button"
      disabled={disabled}
    />
  );
}
