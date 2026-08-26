import { t } from '../../i18n';
import { useDropdown } from '../../hooks/useDropdown';
import { cx } from '../../utils';
import { DROPDOWN_DEFAULT_FOCUS_SELECTOR } from '../../constants';
import menuStyles from '../shared/Menu.module.css';
import styles from './EventOverflowMenu.module.css';

const KebabIcon = () => (
  <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden focusable="false">
    <circle cx="12" cy="5" r="1.8" />
    <circle cx="12" cy="12" r="1.8" />
    <circle cx="12" cy="19" r="1.8" />
  </svg>
);

const ShareIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden focusable="false">
    <path d="M12 15V3" />
    <path d="M8 7l4-4 4 4" />
    <path d="M4 13v6a2 2 0 002 2h12a2 2 0 002-2v-6" />
  </svg>
);

const FlagIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden focusable="false">
    <path d="M4 21V4" />
    <path d="M4 4h13l-2.5 4L17 12H4" />
  </svg>
);

interface EventOverflowMenuProps {
  locale: string;
  reported: boolean;
  onShare: () => void;
  onReport: () => void;
  /** Extra class on the trigger button — lets EventDetail (inline action bar)
   * and EventCard (absolute corner) each apply their own positioning. */
  triggerClassName?: string;
}

/** Kebab trigger + popover holding Share and Report event — the first Modal-
 * adjacent menu pattern shared by EventDetail and EventCard (issue #128). */
export default function EventOverflowMenu({ locale, reported, onShare, onReport, triggerClassName }: EventOverflowMenuProps) {
  // The mobile fixed-position popover escapes the card's `overflow: hidden`
  // (see .pop's mobile override).
  const { open, setOpen, flip, rootRef, popRef, triggerRef, close } = useDropdown(
    DROPDOWN_DEFAULT_FOCUS_SELECTOR,
    '--overflow-pop-top',
  );

  return (
    <div className={menuStyles.menu} ref={rootRef}>
      <button
        ref={triggerRef}
        type="button"
        className={cx(styles.trigger, triggerClassName)}
        aria-expanded={open}
        aria-haspopup="menu"
        aria-label={t('more_options', locale)}
        onClick={(e) => { e.preventDefault(); setOpen((v) => !v); }}
      >
        <KebabIcon />
      </button>
      {open && (
        <div className={styles.pop} ref={popRef} data-flip={flip || undefined} role="menu">
          <button
            type="button"
            role="menuitem"
            className={styles.item}
            onClick={() => { close(); onShare(); }}
          >
            <ShareIcon />
            {t('share', locale)}
          </button>
          <button
            type="button"
            role="menuitem"
            className={styles.item}
            disabled={reported}
            onClick={() => { close(); onReport(); }}
          >
            <FlagIcon />
            {reported ? t('reported', locale) : t('report_event', locale)}
          </button>
        </div>
      )}
    </div>
  );
}
