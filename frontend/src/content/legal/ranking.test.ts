import { describe, expect, it } from 'vitest';
import { RANKING_TIERS_SIGNED_IN, RANKING_TIERS_SIGNED_OUT } from '../../_generated/sharedConstants';
import { inlineText } from '../../utils';
import { LEGAL_LOADERS } from './loaders';
import type { LegalDoc } from './types';

// A phrase per signal and locale that the Relevance list item must carry.
const SIGNAL_WORDS: Record<string, Record<string, string>> = {
  en: {
    affinity: 'tastes',
    recency: 'starts',
    feedback: 'likes',
    quality: 'quality',
    locality: 'central Tallinn',
  },
  et: {
    affinity: 'maitse',
    recency: 'algab',
    feedback: 'meeldimised',
    quality: 'kvaliteet',
    locality: 'kesklinna',
  },
  ru: {
    affinity: 'предпочтения',
    recency: 'начинается',
    feedback: 'Нравится',
    quality: 'Качество',
    locality: 'центре Таллина',
  },
};

async function relevanceLists(locale: string): Promise<string[][]> {
  const doc: LegalDoc = (await LEGAL_LOADERS.ranking[locale]()).default;
  const section = doc.sections.find((s) => s.id === 'relevance');
  if (!section) throw new Error(`no #relevance section in ${locale}`);
  return section.blocks
    .filter((b) => b.kind === 'ol')
    .map((b) => (b.kind === 'ol' ? b.items.map(inlineText) : []));
}

describe.each(['en', 'et', 'ru'])('ranking page (%s)', (locale) => {
  it('names the Relevance signals in the shared tier order', async () => {
    const [signedIn, signedOut] = await relevanceLists(locale);
    const words = SIGNAL_WORDS[locale];
    for (const [items, tiers] of [
      [signedIn, RANKING_TIERS_SIGNED_IN],
      [signedOut, RANKING_TIERS_SIGNED_OUT],
    ] as const) {
      expect(items).toHaveLength(tiers.length);
      tiers.forEach((tier, i) => {
        for (const signal of tier) expect(items[i]).toContain(words[signal]);
      });
    }
  });

  it('carries every anchor the disclosure promises', async () => {
    const doc = (await LEGAL_LOADERS.ranking[locale]()).default;
    expect(doc.sections.map((s) => s.id)).toEqual(['eligible', 'relevance', 'sorts', 'daily-5', 'organizers']);
  });
});
