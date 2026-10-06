import type { FaqDoc } from './types';

type FaqLoader = () => Promise<{ default: FaqDoc }>;

/** Locale → dynamic-import loader map. Each import() becomes its own lazy Vite
 * chunk, so the FAQ copy never lands in the main bundle. A locale missing here
 * falls back to English (see the Faq route's loader effect). */
export const FAQ_LOADERS: Record<string, FaqLoader> = {
  en: () => import('./faq.en'),
};
