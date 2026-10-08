import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { EXPLORE_PARAM, ROUTES, SEARCH_MAX_LEN } from '../../constants';
import { t } from '../../i18n';
import { cx } from '../../utils';
import { useDropdown } from '../../hooks/useDropdown';
import { useLocalePath } from '../../hooks/useLocalePath';
import styles from '../shared/Bar.module.css';

export function SearchGlyph() {
  return (
    <svg className={styles.glyph} viewBox="0 0 16 16" aria-hidden="true">
      <circle cx="7" cy="7" r="5" fill="none" stroke="currentColor" strokeWidth="1.5" />
      <path d="M11 11 14.5 14.5" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  );
}

interface SearchFieldProps {
  locale: string;
  className?: string;
  onDone?: () => void;
}

/** Underline field that submits to /explore?q=… under the current locale prefix. */
export function SearchField({ locale, className, onDone }: SearchFieldProps) {
  const navigate = useNavigate();
  const localePath = useLocalePath();
  const [query, setQuery] = useState('');

  function submit(e: FormEvent) {
    e.preventDefault();
    const trimmed = query.trim();
    const qs = trimmed ? `?${EXPLORE_PARAM.q}=${encodeURIComponent(trimmed)}` : '';
    navigate(`${localePath(ROUTES.explore)}${qs}`);
    setQuery('');
    onDone?.();
  }

  return (
    <form role="search" className={cx(styles.search, className)} onSubmit={submit}>
      <SearchGlyph />
      <input
        type="search"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        maxLength={SEARCH_MAX_LEN}
        placeholder={t('explore_search_placeholder', locale)}
        aria-label={t('explore_search_placeholder', locale)}
      />
    </form>
  );
}

interface SearchPopoverProps {
  locale: string;
  className?: string;
}

/** Icon button (below 1280px, and the signed-in phone primary action) that opens the same field in a popover. */
export function SearchPopover({ locale, className }: SearchPopoverProps) {
  const { open, setOpen, rootRef, popRef, triggerRef, close } = useDropdown('input');
  return (
    <div className={cx(styles.anchor, className)} ref={rootRef}>
      <button
        ref={triggerRef}
        type="button"
        className={styles.iconBtn}
        aria-label={t('explore_search_placeholder', locale)}
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <SearchGlyph />
      </button>
      {open && (
        <div className={cx(styles.pop, styles.searchPop)} ref={popRef}>
          <SearchField locale={locale} onDone={close} />
        </div>
      )}
    </div>
  );
}
