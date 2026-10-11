import { useEffect, useState } from 'react';
import { BAR_CONDENSE_SCROLL_PX, BAR_EXPAND_SCROLL_PX } from '../constants/core';

/**
 * Whether the top bar should be condensed. Hysteresis (condense past 24px,
 * expand back under 4px) keeps the bar's 18px height change from oscillating
 * at a single threshold. Starts false, so the prerendered HTML is always the
 * unscrolled bar.
 */
export function useBarScrolled(): boolean {
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    function onScroll() {
      const y = window.scrollY;
      setScrolled((was) => (was ? y > BAR_EXPAND_SCROLL_PX : y > BAR_CONDENSE_SCROLL_PX));
    }
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);
  return scrolled;
}
