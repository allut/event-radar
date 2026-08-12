import { useEffect, useLayoutEffect, useRef, useState, type Dispatch, type RefObject, type SetStateAction } from 'react';
import { DROPDOWN_DEFAULT_FOCUS_SELECTOR, MOBILE_BREAKPOINT_PX } from '../constants';
import { shouldFlipPopover } from '../utils';

export interface UseDropdownResult {
  open: boolean;
  setOpen: Dispatch<SetStateAction<boolean>>;
  flip: boolean;
  rootRef: RefObject<HTMLDivElement>;
  popRef: RefObject<HTMLDivElement>;
  triggerRef: RefObject<HTMLButtonElement>;
  close: () => void;
}

/**
 * Shared open/close + outside-click + Escape + focus behavior for a
 * trigger-button + popover dropdown (FacetMenu, SelectMenu, DatePicker).
 *
 * @param initialFocusSelector CSS selector for the element to focus when the
 *   popover opens. Defaults to the popover's first `<button>` (FacetMenu/
 *   SelectMenu behavior). DatePicker passes a selector for the selected-day
 *   cell instead, so opening the calendar doesn't land focus on the
 *   previous-month arrow.
 */
export function useDropdown(initialFocusSelector = DROPDOWN_DEFAULT_FOCUS_SELECTOR): UseDropdownResult {
  const [open, setOpen] = useState(false);
  const [flip, setFlip] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const popRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  function close() {
    setOpen(false);
    triggerRef.current?.focus();
  }

  useEffect(() => {
    if (!open) return;

    popRef.current?.querySelector<HTMLElement>(initialFocusSelector)?.focus();

    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') close();
    }
    function handleClickOutside(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    }

    document.addEventListener('keydown', handleKeyDown);
    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [open, initialFocusSelector]);

  // Flip the popover to right-anchor when it would overflow the viewport's
  // right edge — desktop only, mobile has its own fixed-position layout
  // (FacetMenu.module.css's mobile media query) that must not be touched.
  useLayoutEffect(() => {
    function measure(): boolean {
      if (!open || !popRef.current || !triggerRef.current) return false;
      if (window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT_PX}px)`).matches) return false;
      // --space-5 is a rem token (index.css); getPropertyValue on a custom
      // property returns the raw specified value ("1.5rem"), not a resolved
      // px length, so it must be scaled by the root font-size manually.
      const spaceRem = parseFloat(getComputedStyle(popRef.current).getPropertyValue('--space-5'));
      const rootFontPx = parseFloat(getComputedStyle(document.documentElement).fontSize);
      const marginPx = spaceRem * rootFontPx;
      return shouldFlipPopover(
        triggerRef.current.getBoundingClientRect().left,
        popRef.current.getBoundingClientRect().width,
        window.innerWidth,
        marginPx,
      );
    }

    setFlip(measure());
    if (!open) return;

    function handleResize() {
      setFlip(measure());
    }
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, [open]);

  return { open, setOpen, flip, rootRef, popRef, triggerRef, close };
}
