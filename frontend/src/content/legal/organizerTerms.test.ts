import { describe, expect, it } from 'vitest';
import { ORGANIZER_TERMS_VERSION } from '../../_generated/sharedConstants';
import { OPERATOR_FIELD_LABELS, OPERATOR_IDENTITY, ORGANIZER_TERMS_IS_DRAFT, type OperatorField } from '../../constants/operator';
import { inlineText } from '../../utils';
import { LEGAL_LOADERS } from './loaders';
import type { LegalBlock, LegalInline } from './types';

const LOCALES = ['en', 'et', 'ru'];
const SECTION_IDS = [
  'operator', 'promotion', 'ranking', 'price', 'buying', 'invoices', 'no-cancel',
  'reasons', 'refunds', 'content-policy', 'data', 'liability', 'changes', 'law',
];

function operatorFields(blocks: LegalBlock[]): Set<string> {
  const found = new Set<string>();
  const scan = (runs: LegalInline[]) => runs.forEach((r) => typeof r !== 'string' && 'operator' in r && found.add(r.operator));
  blocks.forEach((b) => {
    if (b.kind === 'p') scan(b.content);
    else b.items.forEach((i) => scan(Array.isArray(i) ? i : i.content));
  });
  return found;
}

describe('Operator identity placeholders', () => {
  const fields = Object.keys(OPERATOR_IDENTITY) as OperatorField[];

  it('has a label in every locale for every field', () => {
    for (const field of fields) for (const locale of LOCALES) expect(OPERATOR_FIELD_LABELS[field][locale]).toBeTruthy();
  });

  it('ships unfilled, so every field renders as a placeholder', () => {
    for (const field of fields) expect(OPERATOR_IDENTITY[field]).toBeNull();
  });
});

describe.each(LOCALES)('Organizer terms (%s)', (locale) => {
  it('carries every section the PRD lists, in order, and the draft flag', async () => {
    const doc = (await LEGAL_LOADERS.organizerTerms[locale]()).default;
    expect(doc.sections.map((s) => s.id)).toEqual(SECTION_IDS);
    expect(doc.draft).toBe(ORGANIZER_TERMS_IS_DRAFT);
    expect(ORGANIZER_TERMS_IS_DRAFT).toBe(true);
  });

  it('labels the version from the shared constant that the backend records', async () => {
    const doc = (await LEGAL_LOADERS.organizerTerms[locale]()).default;
    const label = { en: 'Version', et: 'Versioon', ru: 'Версия' }[locale];
    expect(inlineText((doc.intro[1] as { content: LegalInline[] }).content)).toContain(`${label} ${ORGANIZER_TERMS_VERSION},`);
  });

  it('uses every Operator field at least once', async () => {
    const doc = (await LEGAL_LOADERS.organizerTerms[locale]()).default;
    const used = operatorFields([...doc.intro, ...doc.sections.flatMap((s) => s.blocks)]);
    expect([...used].sort()).toEqual(Object.keys(OPERATOR_IDENTITY).sort());
  });

  it('includes the Ranking disclosure by reference', async () => {
    const doc = (await LEGAL_LOADERS.organizerTerms[locale]()).default;
    const intro = doc.intro[0] as { content: LegalInline[] };
    expect(intro.content.some((r) => typeof r !== 'string' && 'to' in r && r.to === '/ranking')).toBe(true);
  });
});
