

/** Toggle `value` in a capped pick list: removes it when present, appends it
 * when absent and there is room, otherwise returns the list unchanged. Shared
 * by the organizer submit form and the claim edit's category pickers. */
export function toggleCapped(list: string[], value: string, max: number): string[] {
  if (list.includes(value)) return list.filter((v) => v !== value);
  return list.length < max ? [...list, value] : list;
}

/** Constrains `n` to the inclusive [lo, hi] range. */
export function clamp(n: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, n));
}
