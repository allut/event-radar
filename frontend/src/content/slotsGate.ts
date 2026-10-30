import type { LegalDoc, SlotsGate } from './legal/types';

function isGate(value: unknown): value is SlotsGate {
  return value === 'slotsOn' || value === 'slotsOff';
}

function keeps(gate: unknown, slotsOn: boolean): boolean {
  if (!isGate(gate)) return true;
  return gate === 'slotsOn' ? slotsOn : !slotsOn;
}

/** Resolves a content tree for the Sponsored slots flag: drops every array
 * element whose `gate` does not match, unwraps `{ content, gate }` list items to
 * bare inline runs and strips the remaining `gate` markers. Pure; the input is
 * never mutated. */
export function resolveSlotsGate<T>(node: T, slotsOn: boolean): T {
  if (Array.isArray(node)) {
    return node
      .filter((el) => keeps((el as { gate?: unknown } | null)?.gate, slotsOn))
      .map((el) => {
        if (el && typeof el === 'object' && !Array.isArray(el)) {
          const keys = Object.keys(el);
          if (keys.length === 2 && keys.includes('content') && keys.includes('gate')) {
            return resolveSlotsGate((el as { content: unknown }).content, slotsOn);
          }
        }
        return resolveSlotsGate(el, slotsOn);
      }) as T;
  }
  if (node && typeof node === 'object') {
    const out: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(node)) {
      if (key !== 'gate') out[key] = resolveSlotsGate(value, slotsOn);
    }
    return out as T;
  }
  return node;
}

/** A legal doc as the page shows it: gated copy resolved and the date that goes with it. */
export function resolveLegalDoc(doc: LegalDoc, slotsOn: boolean): LegalDoc {
  const resolved = resolveSlotsGate(doc, slotsOn);
  const lastUpdated = slotsOn && doc.lastUpdatedSlots ? doc.lastUpdatedSlots : doc.lastUpdated;
  const out: LegalDoc = { ...resolved, lastUpdated };
  delete out.lastUpdatedSlots;
  return out;
}
