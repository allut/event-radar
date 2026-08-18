import { describe, it, expect, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import EventCard from './EventCard';
import { renderWithProviders, makeEvent } from '../../test/utils';

vi.mock('../../hooks/useFeedback', () => ({
  useFeedback: vi.fn(() => ({
    activeSignal: null,
    pending: false,
    sendFeedback: vi.fn(),
  })),
}));

vi.mock('../../utils', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../utils')>();
  return {
    ...actual,
    trackExternalClick: vi.fn(),
  };
});

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
    const { trackExternalClick } = await import('../../utils');
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
});
