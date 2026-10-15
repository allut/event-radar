import { describe, it, expect } from 'vitest';
import privacyEn from './privacy.en';
import privacyEt from './privacy.et';
import privacyRu from './privacy.ru';
import termsEn from './terms.en';
import termsEt from './terms.et';
import termsRu from './terms.ru';
import type { LegalBlock, LegalDoc } from './types';

// Guards translation drift: every locale of a doc must share the same section
// count, the same per-section block count, AND the same per-block inline shape
// (paragraph run count / list item count) as the authoritative English — so a
// dropped inline link (e.g. a mailto/AKI link) in one translation is caught.
const docs: Record<string, { en: LegalDoc; et: LegalDoc; ru: LegalDoc }> = {
  privacy: { en: privacyEn, et: privacyEt, ru: privacyRu },
  terms: { en: termsEn, et: termsEt, ru: termsRu },
};

function assertBlocksParity(enBlocks: LegalBlock[], otherBlocks: LegalBlock[]): void {
  expect(otherBlocks.length).toBe(enBlocks.length);
  enBlocks.forEach((block, i) => {
    const other = otherBlocks[i];
    expect(other.kind).toBe(block.kind);
    if (block.kind === 'p' && other.kind === 'p') {
      // Same number of inline runs (text fragments + links).
      expect(other.content.length).toBe(block.content.length);
    }
    if (block.kind === 'ul' && other.kind === 'ul') {
      expect(other.items.length).toBe(block.items.length);
    }
  });
}

describe('legal doc structure parity', () => {
  for (const [docId, { en, et, ru }] of Object.entries(docs)) {
    it(`${docId}: et/ru match en section, block, and inline shape`, () => {
      for (const other of [et, ru]) {
        expect(other.sections.length).toBe(en.sections.length);
        assertBlocksParity(en.intro, other.intro);
        en.sections.forEach((section, i) => {
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
