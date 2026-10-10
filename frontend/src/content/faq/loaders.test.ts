import { describe, it, expect } from 'vitest';
import { FAQ_LOADERS } from './loaders';
import faqEn from './faq.en';
import faqEt from './faq.et';
import faqRu from './faq.ru';

describe('FAQ_LOADERS', () => {
  it.each([
    ['en', faqEn],
    ['et', faqEt],
    ['ru', faqRu],
  ])('%s loads its own doc', async (locale, doc) => {
    expect((await FAQ_LOADERS[locale]()).default).toBe(doc);
  });
});
