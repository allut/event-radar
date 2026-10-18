import { describe, it, expect } from 'vitest';
import { resolveLegalDoc, resolveSlotsGate } from './slotsGate';
import type { LegalDoc } from './legal/types';

const doc: LegalDoc = {
  title: 'T',
  lastUpdated: '2026-10-17',
  lastUpdatedSlots: '2026-10-18',
  intro: [{ kind: 'p', content: ['Always.'] }, { kind: 'p', content: ['Only with slots.'], gate: 'slotsOn' }],
  sections: [
    {
      id: 'base',
      heading: 'Base',
      blocks: [
        { kind: 'p', content: ['Old wording.'], gate: 'slotsOff' },
        { kind: 'p', content: ['New wording.'], gate: 'slotsOn' },
        { kind: 'ul', items: [['Plain item'], { content: ['Slots item'], gate: 'slotsOn' }] },
      ],
    },
    { id: 'paid-slots', heading: 'Paid', gate: 'slotsOn', blocks: [{ kind: 'p', content: ['x'] }] },
  ],
};

describe('resolveSlotsGate', () => {
  it('keeps slotsOn copy, drops slotsOff copy and unwraps gated items while the flag is on', () => {
    const out = resolveLegalDoc(doc, true);
    expect(out.intro).toHaveLength(2);
    expect(out.sections.map((s) => s.id)).toEqual(['base', 'paid-slots']);
    expect(out.sections[0].blocks).toEqual([
      { kind: 'p', content: ['New wording.'] },
      { kind: 'ul', items: [['Plain item'], ['Slots item']] },
    ]);
    expect(out.lastUpdated).toBe('2026-10-18');
    expect(out).not.toHaveProperty('lastUpdatedSlots');
  });

  it('keeps slotsOff copy and drops every slotsOn element while the flag is off', () => {
    const out = resolveLegalDoc(doc, false);
    expect(out.intro).toEqual([{ kind: 'p', content: ['Always.'] }]);
    expect(out.sections.map((s) => s.id)).toEqual(['base']);
    expect(out.sections[0].blocks).toEqual([
      { kind: 'p', content: ['Old wording.'] },
      { kind: 'ul', items: [['Plain item']] },
    ]);
    expect(out.lastUpdated).toBe('2026-10-17');
  });

  it('never mutates its input', () => {
    const before = JSON.stringify(doc);
    resolveSlotsGate(doc, true);
    resolveSlotsGate(doc, false);
    expect(JSON.stringify(doc)).toBe(before);
  });
});
