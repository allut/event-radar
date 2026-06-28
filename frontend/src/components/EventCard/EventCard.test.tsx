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

vi.mock('../../lib/auth', () => ({
  getLocale: vi.fn(() => 'en'),
}));

describe('EventCard', () => {
  it('renders title as link to event detail', () => {
    const event = makeEvent({ id: 42, title: 'Cool Concert' });
    renderWithProviders(<EventCard event={event} index={0} />);
    const link = screen.getByRole('link', { name: 'Cool Concert' });
    expect(link).toHaveAttribute('href', '/events/42');
  });

  it('shows gradient placeholder when no image', () => {
    const event = makeEvent({ image_url: null });
    const { container } = renderWithProviders(<EventCard event={event} index={0} />);
    expect(container.querySelector('[class*="placeholder"]')).toBeInTheDocument();
  });

  it('shows image when image_url present', () => {
    const event = makeEvent({ image_url: 'https://example.com/img.jpg', title: 'Art Show' });
    renderWithProviders(<EventCard event={event} index={0} />);
    const imgs = screen.getAllByRole('img', { hidden: true });
    const mainImg = imgs.find((img) => img.getAttribute('alt') === 'Art Show');
    expect(mainImg).toBeInTheDocument();
  });

  it('renders why_go bullets when non-empty', () => {
    const event = makeEvent({ why_go: ['Great music', 'Amazing venue'] });
    renderWithProviders(<EventCard event={event} index={0} />);
    expect(screen.getByText('Great music')).toBeInTheDocument();
    expect(screen.getByText('Amazing venue')).toBeInTheDocument();
  });

  it('does not render bullets list when why_go is empty', () => {
    const event = makeEvent({ why_go: [] });
    renderWithProviders(<EventCard event={event} index={0} />);
    expect(screen.queryByRole('list')).not.toBeInTheDocument();
  });

  it('shows price when price_min present', () => {
    const event = makeEvent({ price_min: 10, price_max: null, currency: 'EUR' });
    renderWithProviders(<EventCard event={event} index={0} />);
    expect(screen.getByText('€10')).toBeInTheDocument();
  });

  it('renders tickets link when url present', () => {
    const event = makeEvent({ url: 'https://tickets.example.com' });
    renderWithProviders(<EventCard event={event} index={0} />);
    const link = screen.getByRole('link', { name: /tickets/i });
    expect(link).toHaveAttribute('href', 'https://tickets.example.com');
  });

  it('does not render tickets link when url is null', () => {
    const event = makeEvent({ url: null });
    renderWithProviders(<EventCard event={event} index={0} />);
    expect(screen.queryByRole('link', { name: /tickets/i })).not.toBeInTheDocument();
  });

  it('calls trackExternalClick on tickets link click', async () => {
    const { trackExternalClick } = await import('../../utils');
    const event = makeEvent({ id: 99, url: 'https://tickets.example.com' });
    renderWithProviders(<EventCard event={event} index={0} />);
    await userEvent.click(screen.getByRole('link', { name: /tickets/i }));
    expect(trackExternalClick).toHaveBeenCalledWith(99);
  });

  it('featured variant: applies featured class', () => {
    const event = makeEvent();
    const { container } = renderWithProviders(<EventCard event={event} index={0} variant="featured" />);
    expect(container.querySelector('[class*="featured"]')).toBeInTheDocument();
  });

  it('standard variant does not apply featured class on card', () => {
    const event = makeEvent();
    const { container } = renderWithProviders(<EventCard event={event} index={0} variant="standard" />);
    const card = container.querySelector('article');
    expect(card?.className).not.toMatch(/featured/);
  });
});
