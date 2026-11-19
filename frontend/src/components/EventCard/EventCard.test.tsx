import { describe, it, expect, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ComponentProps } from 'react';
import EventCardBase from './EventCard';
import { useFeedback } from '../../hooks/useFeedback';
import { useEventCardNav } from '../../hooks/useEventCardNav';
import { renderWithProviders, makeEvent } from '../../test/utils';
import { SPONSORED_SLOT_ATTR } from '../../_generated/sharedConstants';
import { t } from '../../i18n';

const mockNavigate = vi.fn();
vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>();
  return { ...actual, useNavigate: () => mockNavigate };
});

vi.mock('../../lib/auth', () => ({
  getLocale: vi.fn(() => 'en'),
  getStoredLocale: vi.fn(() => null),
  setLocale: vi.fn(),
  clearLocale: vi.fn(),
  isAuthenticated: vi.fn(() => true),
  subscribeAuth: vi.fn(() => () => undefined),
}));

vi.mock('../../hooks/useFeedback', () => ({
  useFeedback: vi.fn(() => ({
    activeSignal: null,
    pending: false,
    sendFeedback: vi.fn(),
  })),
}));

vi.mock('../../utils/eventActions', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../utils/eventActions')>();
  return {
    ...actual,
    trackExternalClick: vi.fn(),
  };
});

import { isAuthenticated } from '../../lib/auth';
const mockIsAuthenticated = vi.mocked(isAuthenticated);

// Stands in for the parent list, which resolves router/auth context once.
function EventCard(props: Omit<ComponentProps<typeof EventCardBase>, 'nav'>) {
  return <EventCardBase {...props} nav={useEventCardNav()} />;
}

describe('EventCard', () => {
  it('renders title as link to event detail', () => {
    const event = makeEvent({ id: 42, title: 'Cool Concert' });
    renderWithProviders(<EventCard event={event} index={0} locale="en" />);
    const link = screen.getByRole('link', { name: 'Cool Concert' });
    expect(link).toHaveAttribute('href', '/events/42');
  });

  it('carries the current locale prefix into the event detail link under a prefixed route', () => {
    const event = makeEvent({ id: 42, title: 'Cool Concert' });
    renderWithProviders(<EventCard event={event} index={0} locale="ru" />, { route: '/ru/explore' });
    const link = screen.getByRole('link', { name: 'Cool Concert' });
    expect(link).toHaveAttribute('href', '/ru/events/42');
  });

  it('shows gradient placeholder when no image', () => {
    const event = makeEvent({ image_url: null });
    const { container } = renderWithProviders(<EventCard event={event} index={0} locale="en" />);
    expect(container.querySelector('[class*="placeholder"]')).toBeInTheDocument();
  });

  it('shows image when image_url present', () => {
    const event = makeEvent({ image_url: 'https://example.com/img.jpg', title: 'Art Show' });
    renderWithProviders(<EventCard event={event} index={0} locale="en" />);
    const imgs = screen.getAllByRole('img', { hidden: true });
    const mainImg = imgs.find((img) => img.getAttribute('alt') === 'Art Show');
    expect(mainImg).toBeInTheDocument();
  });

  it('renders why_go bullets when non-empty', () => {
    const event = makeEvent({ why_go: ['Great music', 'Amazing venue'] });
    renderWithProviders(<EventCard event={event} index={0} locale="en" />);
    expect(screen.getByText('Great music')).toBeInTheDocument();
    expect(screen.getByText('Amazing venue')).toBeInTheDocument();
  });

  it('does not render bullets list when why_go is empty', () => {
    const event = makeEvent({ why_go: [] });
    renderWithProviders(<EventCard event={event} index={0} locale="en" />);
    expect(screen.queryByRole('list')).not.toBeInTheDocument();
  });

  it('shows price when price_min present', () => {
    const event = makeEvent({ price_min: 10, price_max: null, currency: 'EUR' });
    renderWithProviders(<EventCard event={event} index={0} locale="en" />);
    expect(screen.getByText('€10')).toBeInTheDocument();
  });

  it('renders tickets link when url present', () => {
    const event = makeEvent({ url: 'https://tickets.example.com' });
    renderWithProviders(<EventCard event={event} index={0} locale="en" />);
    const link = screen.getByRole('link', { name: /tickets/i });
    expect(link).toHaveAttribute('href', 'https://tickets.example.com');
  });

  it('does not render tickets link when url is null', () => {
    const event = makeEvent({ url: null });
    renderWithProviders(<EventCard event={event} index={0} locale="en" />);
    expect(screen.queryByRole('link', { name: /tickets/i })).not.toBeInTheDocument();
  });

  it('calls trackExternalClick on tickets link click', async () => {
    const { trackExternalClick } = await import('../../utils/eventActions');
    const event = makeEvent({ id: 99, url: 'https://tickets.example.com' });
    renderWithProviders(<EventCard event={event} index={0} locale="en" />);
    await userEvent.click(screen.getByRole('link', { name: /tickets/i }));
    expect(trackExternalClick).toHaveBeenCalledWith(99);
  });

  it('featured variant: applies featured class', () => {
    const event = makeEvent();
    const { container } = renderWithProviders(<EventCard event={event} index={0} locale="en" variant="featured" />);
    expect(container.querySelector('[class*="featured"]')).toBeInTheDocument();
  });

  it('standard variant does not apply featured class on card', () => {
    const event = makeEvent();
    const { container } = renderWithProviders(<EventCard event={event} index={0} locale="en" variant="standard" />);
    const card = container.querySelector('article');
    expect(card?.className).not.toMatch(/featured/);
  });

  it('stretches the title link over the image/body region so the whole card body is clickable', () => {
    const event = makeEvent({ id: 7, title: 'Cool Concert', why_go: ['Great music'] });
    const { container } = renderWithProviders(<EventCard event={event} index={0} locale="en" />);
    const link = screen.getByRole('link', { name: 'Cool Concert' });
    expect(link.className).toMatch(/stretched/);
    const clickable = container.querySelector('[class*="clickable"]');
    expect(clickable).toBeInTheDocument();
    expect(clickable?.contains(screen.getByText('Great music'))).toBe(true);
    expect(clickable?.contains(link)).toBe(true);
  });

  it('keeps the actions row (feedback + tickets) outside the clickable region', () => {
    const event = makeEvent({ url: 'https://tickets.example.com' });
    const { container } = renderWithProviders(<EventCard event={event} index={0} locale="en" />);
    const clickable = container.querySelector('[class*="clickable"]');
    const ticketsLink = screen.getByRole('link', { name: /tickets/i });
    expect(clickable?.contains(ticketsLink)).toBe(false);
  });

  describe('overflow menu', () => {
    it('shows Share and Report event on an interactive card', async () => {
      const event = makeEvent();
      renderWithProviders(<EventCard event={event} index={0} locale="en" />);
      await userEvent.click(screen.getByRole('button', { name: 'More options' }));
      expect(screen.getByRole('menuitem', { name: 'Share' })).toBeInTheDocument();
      expect(screen.getByRole('menuitem', { name: 'Report event' })).toBeInTheDocument();
    });

    it('renders no kebab on a read-only card', () => {
      const event = makeEvent();
      renderWithProviders(<EventCard event={event} index={0} locale="en" readOnly />);
      expect(screen.queryByRole('button', { name: 'More options' })).not.toBeInTheDocument();
    });

    it('shows a disabled Reported row when the event was already reported', async () => {
      const event = makeEvent({ reported: true });
      renderWithProviders(<EventCard event={event} index={0} locale="en" />);
      await userEvent.click(screen.getByRole('button', { name: 'More options' }));
      expect(screen.getByRole('menuitem', { name: 'Reported' })).toBeDisabled();
    });

    it('opens the report modal when Report event is clicked while authenticated', async () => {
      const event = makeEvent({ id: 5 });
      renderWithProviders(<EventCard event={event} index={0} locale="en" />);
      await userEvent.click(screen.getByRole('button', { name: 'More options' }));
      await userEvent.click(screen.getByRole('menuitem', { name: 'Report event' }));
      expect(screen.getByRole('dialog', { name: 'Report event' })).toBeInTheDocument();
    });

    it('redirects to /login instead of opening the modal when signed out', async () => {
      mockIsAuthenticated.mockReturnValue(false);
      try {
        const event = makeEvent({ id: 5 });
        renderWithProviders(<EventCard event={event} index={0} locale="en" />);
        await userEvent.click(screen.getByRole('button', { name: 'More options' }));
        await userEvent.click(screen.getByRole('menuitem', { name: 'Report event' }));
        expect(mockNavigate).toHaveBeenCalledWith('/login', undefined);
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
      } finally {
        mockIsAuthenticated.mockReturnValue(true);
      }
    });
  });

  describe('onFeedbackBlocked (issue #235)', () => {
    it('routes a bookmark press through onFeedbackBlocked instead of useFeedback when set', async () => {
      const { useFeedback } = await import('../../hooks/useFeedback');
      const sendFeedback = vi.fn();
      vi.mocked(useFeedback).mockReturnValueOnce({ activeSignal: null, pending: false, sendFeedback });
      const onFeedbackBlocked = vi.fn();
      const event = makeEvent();
      renderWithProviders(<EventCard event={event} index={0} locale="en" onFeedbackBlocked={onFeedbackBlocked} />);

      await userEvent.click(screen.getByRole('button', { name: 'Bookmark' }));

      expect(onFeedbackBlocked).toHaveBeenCalledWith('bookmark');
      expect(sendFeedback).not.toHaveBeenCalled();
    });

    it('calls sendFeedback directly when onFeedbackBlocked is not set', async () => {
      const { useFeedback } = await import('../../hooks/useFeedback');
      const sendFeedback = vi.fn();
      vi.mocked(useFeedback).mockReturnValueOnce({ activeSignal: null, pending: false, sendFeedback });
      const event = makeEvent();
      renderWithProviders(<EventCard event={event} index={0} locale="en" />);

      await userEvent.click(screen.getByRole('button', { name: 'Like' }));

      expect(sendFeedback).toHaveBeenCalledWith('like');
    });
  });

  describe('sponsored caption slot (issue #603)', () => {
    const sponsored = { advertiser: 'Example Society MTÜ', explanation: 'filters' } as const;

    it('renders no caption, marker or sponsored rel on an organic card', () => {
      const { container } = renderWithProviders(<EventCard event={makeEvent({ id: 7 })} index={0} locale="en" />);
      expect(container.querySelector(`[${SPONSORED_SLOT_ATTR}]`)).toBeNull();
      expect(screen.queryByRole('button', { name: 'Why?' })).not.toBeInTheDocument();
      expect(screen.getByRole('link', { name: 'Test Event' })).not.toHaveAttribute('rel');
    });

    it('adds ?ref=ad to the stretched link of a sponsored card only', () => {
      const { unmount } = renderWithProviders(<EventCard event={makeEvent({ id: 7 })} index={0} locale="en" sponsored={sponsored} />);
      expect(screen.getByRole('link', { name: 'Test Event' })).toHaveAttribute('href', '/events/7?ref=ad');
      unmount();
      renderWithProviders(<EventCard event={makeEvent({ id: 7 })} index={0} locale="en" />);
      expect(screen.getByRole('link', { name: 'Test Event' })).toHaveAttribute('href', '/events/7');
    });

    it('passes ref ad to useFeedback on a sponsored card only', () => {
      renderWithProviders(<EventCard event={makeEvent({ id: 7 })} index={0} locale="en" sponsored={sponsored} />);
      expect(vi.mocked(useFeedback)).toHaveBeenLastCalledWith(7, expect.objectContaining({ ref: 'ad' }));
      renderWithProviders(<EventCard event={makeEvent({ id: 8 })} index={0} locale="en" />);
      expect(vi.mocked(useFeedback)).toHaveBeenLastCalledWith(8, expect.objectContaining({ ref: undefined }));
    });

    it.each([
      ['et', 'Reklaam', 'Miks?'],
      ['en', 'Ad', 'Why?'],
      ['ru', 'Реклама', 'Почему?'],
    ])('shows the label, advertiser and why-button in %s', (locale, label, why) => {
      renderWithProviders(<EventCard event={makeEvent()} index={0} locale={locale} sponsored={sponsored} />);
      expect(screen.getByText(label)).toBeInTheDocument();
      expect(screen.getByText(/Example Society MTÜ/)).toBeInTheDocument();
      expect(screen.getByRole('button', { name: why })).toHaveAttribute('aria-expanded', 'false');
    });

    it('carries the slot DOM marker on the card', () => {
      const { container } = renderWithProviders(<EventCard event={makeEvent()} index={0} locale="en" sponsored={sponsored} />);
      expect(container.querySelector(`article[${SPONSORED_SLOT_ATTR}]`)).toBeInTheDocument();
    });

    it('shows no position numeral on an imageless sponsored card, so it never reads as a pick', () => {
      renderWithProviders(<EventCard event={makeEvent({ image_url: null })} index={5} locale="en" sponsored={sponsored} />);
      expect(screen.queryByText('06')).not.toBeInTheDocument();
      renderWithProviders(<EventCard event={makeEvent({ id: 2, image_url: null })} index={5} locale="en" />);
      expect(screen.getByText('06')).toBeInTheDocument();
    });

    it('marks the stretched link rel="sponsored" and the ticket link sponsored noopener noreferrer', () => {
      renderWithProviders(<EventCard event={makeEvent({ url: 'https://example.com/t' })} index={0} locale="en" sponsored={sponsored} />);
      expect(screen.getByRole('link', { name: 'Test Event' })).toHaveAttribute('rel', 'sponsored');
      expect(screen.getByRole('link', { name: 'Tickets →' })).toHaveAttribute('rel', 'sponsored noopener noreferrer');
    });

    it.each([
      ['filters', 'only by your filters and search'],
      ['none', 'by the day and page'],
      ['daily5', 'not one of your five'],
    ] as const)('opens the %s explanation panel with a plain link to /ranking#paid-slots, and closes it', async (explanation, snippet) => {
      renderWithProviders(<EventCard event={makeEvent()} index={0} locale="en" sponsored={{ advertiser: 'Acme', explanation }} />);
      await userEvent.click(screen.getByRole('button', { name: 'Why?' }));
      expect(screen.getByText(new RegExp(snippet))).toBeInTheDocument();
      const link = screen.getByRole('link', { name: 'How results are ordered' });
      expect(link).toHaveAttribute('href', '/ranking#paid-slots');
      expect(link).not.toHaveAttribute('rel');
      expect(screen.getByRole('button', { name: 'Why?' })).toHaveAttribute('aria-expanded', 'true');
      await userEvent.click(screen.getByRole('button', { name: 'Close' }));
      expect(screen.queryByText(new RegExp(snippet))).not.toBeInTheDocument();
    });

    it.each([
      ['en', 'Why?', 'How results are ordered', '/ranking#paid-slots'],
      ['et', 'Miks?', 'Kuidas tulemused järjestatakse', '/ranking#paid-slots'],
      ['ru', 'Почему?', 'Как упорядочены результаты', '/ranking#paid-slots'],
    ] as const)('words every explanation in %s and links the disclosure', async (locale, why, rankingLabel, href) => {
      for (const explanation of ['filters', 'none', 'daily5'] as const) {
        const { unmount } = renderWithProviders(
          <EventCard event={makeEvent()} index={0} locale={locale} sponsored={{ advertiser: 'Acme', explanation }} />,
          { route: locale === 'ru' ? '/ru/explore' : locale === 'en' ? '/en/explore' : '/explore' },
        );
        await userEvent.click(screen.getByRole('button', { name: why }));
        expect(screen.getByText(t(`sponsored_explain_${explanation}`, locale))).toBeInTheDocument();
        const link = screen.getByRole('link', { name: rankingLabel });
        expect(link.getAttribute('href')).toBe(locale === 'ru' ? `/ru${href}` : locale === 'en' ? `/en${href}` : href);
        expect(link).not.toHaveAttribute('rel');
        unmount();
      }
    });

    it('keeps the locale prefix on the ranking link', async () => {
      renderWithProviders(<EventCard event={makeEvent()} index={0} locale="ru" sponsored={sponsored} />, { route: '/ru/explore' });
      await userEvent.click(screen.getByRole('button', { name: 'Почему?' }));
      expect(screen.getByRole('link', { name: 'Как упорядочены результаты' })).toHaveAttribute('href', '/ru/ranking#paid-slots');
    });
  });
});
