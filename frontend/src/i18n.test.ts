import { describe, it, expect } from 'vitest';
import { t, ti, tn, personaName, personaVibe } from './i18n';

describe('t', () => {
  it('returns translation for known key', () => {
    expect(t('brand', 'en')).toBe('Event Radar');
  });

  it('falls back to key for missing key', () => {
    expect(t('__nonexistent_key__', 'en')).toBe('__nonexistent_key__');
  });

  it('falls back to en for invalid locale', () => {
    expect(t('brand', 'zz')).toBe('Event Radar');
  });

  it('returns et translation when locale is et', () => {
    const etBrand = t('brand', 'et');
    expect(typeof etBrand).toBe('string');
    expect(etBrand.length).toBeGreaterThan(0);
  });
});

describe('ti', () => {
  it('interpolates variables', () => {
    const result = ti('link_expires', 'en', { minutes: '15' });
    expect(result).toContain('15');
    expect(result).not.toContain('{minutes}');
  });

  it('leaves unknown vars unreplaced', () => {
    const result = ti('brand', 'en', { unknown_var: 'x' });
    expect(result).toBe('Event Radar');
  });
});

describe('tn', () => {
  const summary = (locale: string, n: number) => tn('dashboard_claims_summary', locale, n, { count: String(n) });

  it('picks the English one/other form and fills the vars', () => {
    expect(summary('en', 1)).toBe('You have 1 claim');
    expect(summary('en', 37)).toBe('You have 37 claims');
  });

  it('picks the Estonian one/other form', () => {
    expect(summary('et', 1)).toBe('Sul on 1 nõudeõigus');
    expect(summary('et', 4)).toBe('Sul on 4 nõudeõigust');
  });

  it('picks the Russian one/few/many forms', () => {
    expect(summary('ru', 1)).toBe('У вас 1 заявка');
    expect(summary('ru', 21)).toBe('У вас 21 заявка');
    expect(summary('ru', 3)).toBe('У вас 3 заявки');
    expect(summary('ru', 11)).toBe('У вас 11 заявок');
    expect(summary('ru', 25)).toBe('У вас 25 заявок');
  });

  it('falls back to English forms for an unknown locale', () => {
    expect(summary('zz', 2)).toBe('You have 2 claims');
  });
});

describe('personaName', () => {
  it('returns en name for en locale', () => {
    const name = personaName('culture_buff', 'en');
    expect(name).toBe('Culture Buff');
  });

  it('returns en fallback for missing locale translation', () => {
    const name = personaName('culture_buff', 'zz');
    expect(name).toBe('Culture Buff');
  });

  it('returns et translation when available', () => {
    const name = personaName('culture_buff', 'et');
    expect(typeof name).toBe('string');
    expect(name.length).toBeGreaterThan(0);
  });
});

describe('personaVibe', () => {
  it('returns en vibe for en locale', () => {
    const vibe = personaVibe('culture_buff', 'en');
    expect(vibe).toContain('Museums');
  });

  it('returns en fallback for missing locale', () => {
    const vibe = personaVibe('culture_buff', 'zz');
    expect(typeof vibe).toBe('string');
  });
});
