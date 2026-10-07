import { describe, it, expect } from 'vitest';
import faqEn from './faq.en';
import faqEt from './faq.et';
import faqRu from './faq.ru';
import type { FaqBlock, FaqDoc, FaqInline } from './types';

// Guards translation drift, as legal/structure.test.ts does: ET and RU must match
// the canonical English on section ids/order, item ids/order, answer block count
// and kind, and per-block inline shape (paragraph runs / list item count) — so a
// link dropped from one translation, or a renamed #slug anchor, is caught.
const translations: Record<string, FaqDoc> = { et: faqEt, ru: faqRu };

/** A run's shape minus its locale-specific text: plain text, or a link and its target. */
function runShape(run: FaqInline): string {
  if (typeof run === 'string') return 'text';
  return 'to' in run ? `to:${run.to}` : `href:${run.href}`;
}

function assertBlocksParity(enBlocks: FaqBlock[], otherBlocks: FaqBlock[]): void {
  expect(otherBlocks.length).toBe(enBlocks.length);
  enBlocks.forEach((block, i) => {
    const other = otherBlocks[i];
    expect(other.kind).toBe(block.kind);
    if (block.kind === 'p' && other.kind === 'p') {
      // Same inline runs in the same order, so a link can't turn into plain
      // text or point somewhere else while the run count still matches.
      expect(other.content.map(runShape)).toEqual(block.content.map(runShape));
    }
    if (block.kind === 'ul' && other.kind === 'ul') {
      expect(other.items.length).toBe(block.items.length);
    }
  });
}

describe('faq doc structure parity', () => {
  for (const [locale, other] of Object.entries(translations)) {
    it(`${locale}: matches en section ids and order`, () => {
      expect(other.sections.map((s) => s.id)).toEqual(faqEn.sections.map((s) => s.id));
    });

    it(`${locale}: matches en item ids and order per section`, () => {
      faqEn.sections.forEach((section, i) => {
        expect(other.sections[i].items.map((item) => item.id)).toEqual(
          section.items.map((item) => item.id),
        );
      });
    });

    it(`${locale}: matches en answer block and inline shape`, () => {
      faqEn.sections.forEach((section, i) => {
        section.items.forEach((item, j) => {
          assertBlocksParity(item.answer, other.sections[i].items[j].answer);
        });
      });
    });
  }
});
