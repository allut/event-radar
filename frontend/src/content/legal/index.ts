import type { LegalDoc } from './types';

type LegalLoader = () => Promise<{ default: LegalDoc }>;

/** Locale → dynamic-import loader maps. Each import() becomes its own lazy Vite
 * chunk, so long-form legal prose never lands in the main bundle — it is fetched
 * only when a visitor opens /privacy or /terms. */
export const LEGAL_LOADERS: Record<'privacy' | 'terms', Record<string, LegalLoader>> = {
  privacy: {
    en: () => import('./privacy.en'),
    et: () => import('./privacy.et'),
    ru: () => import('./privacy.ru'),
  },
  terms: {
    en: () => import('./terms.en'),
    et: () => import('./terms.et'),
    ru: () => import('./terms.ru'),
  },
};

export type LegalDocId = keyof typeof LEGAL_LOADERS;
