import { describe, it, expect } from 'vitest';
import privacyEn from './privacy.en';
import privacyEt from './privacy.et';
import privacyRu from './privacy.ru';
import termsEn from './terms.en';
import termsEt from './terms.et';
import termsRu from './terms.ru';
import rankingEn from './ranking.en';
import rankingEt from './ranking.et';
import rankingRu from './ranking.ru';
import organizerTermsEn from './organizerTerms.en';
import organizerTermsEt from './organizerTerms.et';
import organizerTermsRu from './organizerTerms.ru';
import type { LegalBlock, LegalDoc, LegalInline, LegalItem } from './types';

// Guards translation drift: every locale of a doc must share the same section
// count, the same per-section block count, AND the same per-block inline shape
// (paragraph run count / list item count) as the authoritative English — so a
// dropped inline link (e.g. a mailto/AKI link) in one translation is caught.
const docs: Record<string, { en: LegalDoc; et: LegalDoc; ru: LegalDoc }> = {
  privacy: { en: privacyEn, et: privacyEt, ru: privacyRu },
  terms: { en: termsEn, et: termsEt, ru: termsRu },
  ranking: { en: rankingEn, et: rankingEt, ru: rankingRu },
  organizerTerms: { en: organizerTermsEn, et: organizerTermsEt, ru: organizerTermsRu },
};

/** A run's shape minus its locale-specific text: text, a link and its target, or an Operator field. */
function runShape(run: LegalInline): string {
  if (typeof run === 'string') return 'text';
  if ('operator' in run) return `operator:${run.operator}`;
  return 'to' in run ? `to:${run.to}` : `href:${run.href}`;
}

const itemRuns = (item: LegalItem): LegalInline[] => (Array.isArray(item) ? item : item.content);
const itemGate = (item: LegalItem): string => (Array.isArray(item) ? '' : item.gate);

function assertBlocksParity(enBlocks: LegalBlock[], otherBlocks: LegalBlock[]): void {
  expect(otherBlocks.length).toBe(enBlocks.length);
  enBlocks.forEach((block, i) => {
    const other = otherBlocks[i];
    expect(other.kind).toBe(block.kind);
    // Same slots-flag gate, so a translation can't show paid copy while the flag is off.
    expect(other.gate).toBe(block.gate);
    if (block.kind === 'p' && other.kind === 'p') {
      // Same inline runs in the same order (text fragments, links and Operator
      // fields), so a link or placeholder can't change target or vanish.
      expect(other.content.map(runShape)).toEqual(block.content.map(runShape));
    }
    if (block.kind !== 'p' && other.kind !== 'p') {
      expect(other.items.length).toBe(block.items.length);
      block.items.forEach((item, j) => {
        expect(itemGate(other.items[j])).toBe(itemGate(item));
        expect(itemRuns(other.items[j]).map(runShape)).toEqual(itemRuns(item).map(runShape));
      });
    }
  });
}

describe('legal doc structure parity', () => {
  for (const [docId, { en, et, ru }] of Object.entries(docs)) {
    it(`${docId}: et/ru match en section, block, and inline shape`, () => {
      for (const other of [et, ru]) {
        expect(other.sections.length).toBe(en.sections.length);
        expect(other.lastUpdatedSlots === undefined).toBe(en.lastUpdatedSlots === undefined);
        expect(other.draft).toBe(en.draft);
        assertBlocksParity(en.intro, other.intro);
        en.sections.forEach((section, i) => {
          expect(other.sections[i].id).toBe(section.id);
          expect(other.sections[i].gate).toBe(section.gate);
          assertBlocksParity(section.blocks, other.sections[i].blocks);
        });
      }
    });
  }
});

describe('terms regulator links', () => {
  it('does not cite the shut-down EU ODR platform in any locale', () => {
    for (const doc of [termsEn, termsEt, termsRu]) {
      expect(JSON.stringify(doc)).not.toContain('ec.europa.eu/consumers/odr');
    }
  });
});
