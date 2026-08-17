import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import RadarHero from './RadarHero';
import { RADAR_BLIPS } from '../../constants';
import { t } from '../../i18n';

describe('RadarHero', () => {
  it('renders one labeled blip per RADAR_BLIPS entry, translated for the given locale', () => {
    render(<RadarHero locale="en" />);

    for (const blip of RADAR_BLIPS) {
      expect(screen.getByText(t(`category_${blip.slug}`, 'en'))).toBeInTheDocument();
    }
  });

  it('re-translates blip labels when the locale changes', () => {
    const { rerender } = render(<RadarHero locale="en" />);
    expect(screen.getByText(t('category_music', 'en'))).toBeInTheDocument();

    rerender(<RadarHero locale="et" />);
    expect(screen.getByText(t('category_music', 'et'))).toBeInTheDocument();
  });

  it('is decorative — hidden from assistive tech via aria-hidden', () => {
    const { container } = render(<RadarHero locale="en" />);
    expect(container.firstElementChild).toHaveAttribute('aria-hidden');
  });
});
