import { describe, it, expect } from 'vitest';
import faqEn from './faq.en';
import faqEt from './faq.et';
import faqRu from './faq.ru';
import type { FaqBlock, FaqDoc, FaqInline } from './types';
import { resolveSlotsGate } from '../slotsGate';
import {
  CLAIM_ADMIN_REVIEW_EXPIRY_DAYS,
  CLAIM_EXPIRY_DAYS,
  MAGIC_LINK_EXPIRY_MINUTES,
  PERSONA_MAX_SELECTABLE,
  SESSION_TTL_DAYS,
} from '../../_generated/sharedConstants';

// Keeps the FAQ copy in step with the product: an answer that quotes a shared
// config value (link expiry, session length, persona cap, claim expiry) must
// still quote it after the value changes. Fails until every locale is updated.
const docs: Record<string, FaqDoc> = {
  en: resolveSlotsGate(faqEn, true),
  et: resolveSlotsGate(faqEt, true),
  ru: resolveSlotsGate(faqRu, true),
};

const QUOTED_VALUES: Record<string, Record<string, number>> = {
  'sign-in': { MAGIC_LINK_EXPIRY_MINUTES, SESSION_TTL_DAYS },
  'change-tastes': { PERSONA_MAX_SELECTABLE },
  'claim-event': { CLAIM_EXPIRY_DAYS, CLAIM_ADMIN_REVIEW_EXPIRY_DAYS },
};

function inlineText(run: FaqInline): string {
  return typeof run === 'string' ? run : run.text;
}

function blockText(block: FaqBlock): string {
  const runs = block.kind === 'p' ? block.content : (block.items as FaqInline[][]).flat();
  return runs.map(inlineText).join(' ');
}

function answerText(doc: FaqDoc, slug: string): string {
  const item = doc.sections.flatMap((s) => s.items).find((i) => i.id === slug);
  if (!item) throw new Error(`FAQ item #${slug} not found`);
  return item.answer.map(blockText).join(' ');
}

describe('faq answers quote current config values', () => {
  for (const [locale, doc] of Object.entries(docs)) {
    for (const [slug, constants] of Object.entries(QUOTED_VALUES)) {
      for (const [name, value] of Object.entries(constants)) {
        it(`${locale} #${slug} quotes ${name} (${value})`, () => {
          // Digit-bounded, not a bare substring: "15 minutes" must not satisfy
          // a SESSION_TTL_DAYS of 1 or 5.
          expect(answerText(doc, slug)).toMatch(new RegExp(`(?<!\\d)${String(value)}(?!\\d)`));
        });
      }
    }
  }
});
