import { BROWSE_PAGE_SIZE } from '../_generated/sharedConstants';
import { CARD_ANIMATION_DELAY_STEP_MS, CARD_ANIMATION_MAX_STEPS } from '../constants/core';
import { type Signal, SIGNAL_TO_CLASS } from '../constants/feedback';
import { CATEGORY_GRADIENTS, FALLBACK_GRADIENT } from '../constants/theme';

export function cx(...classes: (string | false | null | undefined)[]): string {
  return classes.filter(Boolean).join(' ');
}

export function categoryGradient(categories: string[]): string {
  const key = categories[0]?.toLowerCase().replace(/\s+/g, '_') ?? '';
  return CATEGORY_GRADIENTS[key] ?? FALLBACK_GRADIENT;
}

export function makeActiveClassMap(styles: Record<string, string>): Record<Signal, string> {
  const result = {} as Record<Signal, string>;
  for (const [signal, cssKey] of Object.entries(SIGNAL_TO_CLASS) as [Signal, string][]) {
    const cls = styles[cssKey];
    if (!cls) throw new Error(`makeActiveClassMap: CSS class "${cssKey}" is missing from styles module`);
    result[signal] = cls;
  }
  return result;
}

/** True when a popover of `popWidth` left-anchored at `triggerLeft` (viewport-relative
 * px) would overflow the viewport's right edge. `marginPx` matches the --space-5
 * gutter .menuPop's max-width already reserves, for consistency. */
export function shouldFlipPopover(triggerLeft: number, popWidth: number, viewportWidth: number, marginPx: number): boolean {
  return triggerLeft + popWidth > viewportWidth - marginPx;
}

/** Mirror of shouldFlipPopover for a popover that's right-anchored to the
 * trigger by default (extends leftward) — flips to left-anchored when that
 * would overflow the viewport's left edge. */
export function shouldFlipPopoverLeft(triggerRight: number, popWidth: number, marginPx: number): boolean {
  return triggerRight - popWidth < marginPx;
}

/** `animation-delay` for the card at global list `index`: the stagger restarts
 * on every page and plateaus after CARD_ANIMATION_MAX_STEPS cards, instead of
 * growing linearly with the count of everything loaded so far. */
export function cardAnimationDelayMs(index: number): number {
  return Math.min(index % BROWSE_PAGE_SIZE, CARD_ANIMATION_MAX_STEPS) * CARD_ANIMATION_DELAY_STEP_MS;
}
