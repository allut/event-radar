import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ClaimEventEdit from './ClaimEventEdit';
import { renderWithProviders } from '../../test/utils';

vi.mock('../../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/client')>()),
  organizerApi: { get: vi.fn(), patch: vi.fn() },
}));

vi.mock('../../hooks/useOrganizerLogout', () => ({
  useOrganizerLogout: () => vi.fn(),
}));

import { organizerApi, ApiError } from '../../api/client';
const mockGet = vi.mocked(organizerApi.get);
const mockPatch = vi.mocked(organizerApi.patch);

function baseEvent(overrides: Record<string, unknown> = {}) {
  return {
    id: 42,
    slug: 'test-event-42',
    title: 'Sügisõhtu jazziklubis',
    title_localized: { et: 'Sügisõhtu jazziklubis', en: 'Autumn Evening' },
    description: 'Kirjeldus',
    description_localized: null,
    starts_at: '2026-10-14T19:00:00+03:00',
    ends_at: '2026-10-14T22:00:00+03:00',
    url: 'https://fienta.com/e/sugisohtu',
    image_url: null,
    price_min: 18,
    price_max: 24,
    currency: 'EUR',
    has_free_tier: false,
    categories: ['music'],
    pinned_fields: ['title:et'],
    price_mismatch: null,
    status: 'published',
    ...overrides,
  };
}

function renderEdit(route = '/organizer/claims/42/edit') {
  return renderWithProviders(<ClaimEventEdit />, {
    route,
    pathPattern: '/organizer/claims/:id/edit',
  });
}

beforeEach(() => {
  mockGet.mockReset();
  mockPatch.mockReset();
});

describe('ClaimEventEdit (#416)', () => {
  it('shows the locked state when the claim is not yet granted', async () => {
    mockGet.mockRejectedValueOnce(new ApiError(409, 'This claim is not yet granted — editing stays locked until then.'));
    renderEdit();

    await waitFor(() => expect(screen.getByText('Not yet editable')).toBeInTheDocument());
    expect(screen.queryByLabelText('Title')).not.toBeInTheDocument();
  });

  it('shows the dormant-specific lock copy when the claim lost a dedup collision (#444)', async () => {
    mockGet.mockRejectedValueOnce(
      new ApiError(
        409,
        "This claim is dormant — a duplicate claimed event now takes precedence, so editing stays locked until that's resolved.",
        'claim_dormant',
      ),
    );
    renderEdit();

    await waitFor(() =>
      expect(screen.getByText('Editing paused — duplicate takes precedence')).toBeInTheDocument(),
    );
    expect(screen.queryByText('Not yet editable')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Title')).not.toBeInTheDocument();
  });

  it('loads and saves against the event_id from the URL (#437)', async () => {
    mockGet.mockResolvedValueOnce(baseEvent({ id: 7 }));
    mockPatch.mockResolvedValueOnce(baseEvent({ id: 7, title: 'New title' }));
    renderEdit('/organizer/claims/42/edit?event_id=7');

    const titleInput = await screen.findByDisplayValue('Sügisõhtu jazziklubis');
    expect(mockGet).toHaveBeenCalledWith(expect.stringContaining('event_id=7'));

    await userEvent.clear(titleInput);
    await userEvent.type(titleInput, 'New title');
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }));

    await waitFor(() => expect(mockPatch).toHaveBeenCalledTimes(1));
    const [, body] = mockPatch.mock.calls[0];
    expect(body).toEqual({ event_id: 7, title: 'New title' });
  });

  it('renders loaded fields and marks a pinned field distinctly from a synced one', async () => {
    mockGet.mockResolvedValueOnce(baseEvent());
    renderEdit();

    await waitFor(() => expect(screen.getByDisplayValue('Sügisõhtu jazziklubis')).toBeInTheDocument());
    // title:et is pinned (per baseEvent) — Estonian title shows "Pinned" + Unpin.
    const pinnedTags = screen.getAllByText('Pinned');
    expect(pinnedTags.length).toBeGreaterThan(0);
    // title:en is not pinned — shows "Synced from source" instead.
    expect(screen.getAllByText('Synced from source').length).toBeGreaterThan(0);
  });

  it('save only sends fields the organizer actually touched', async () => {
    mockGet.mockResolvedValueOnce(baseEvent());
    mockPatch.mockResolvedValueOnce(baseEvent({ title: 'New title', title_localized: { et: 'New title' } }));
    renderEdit();

    const titleInput = await screen.findByDisplayValue('Sügisõhtu jazziklubis');
    await userEvent.clear(titleInput);
    await userEvent.type(titleInput, 'New title');

    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }));

    await waitFor(() => expect(mockPatch).toHaveBeenCalledTimes(1));
    const [path, body] = mockPatch.mock.calls[0];
    expect(path).toBe('/organizer/claims/42/event');
    expect(body).toEqual({ title: 'New title' });
  });

  it('unpin fires its own request without touching the field value', async () => {
    mockGet.mockResolvedValueOnce(baseEvent());
    mockPatch.mockResolvedValueOnce(baseEvent({ pinned_fields: [] }));
    renderEdit();

    await screen.findByDisplayValue('Sügisõhtu jazziklubis');
    await userEvent.click(screen.getAllByRole('button', { name: 'Unpin' })[0]);

    await waitFor(() => expect(mockPatch).toHaveBeenCalledWith(
      '/organizer/claims/42/event',
      { unpin: ['title:et'] },
    ));
  });

  it('shows the price-mismatch badge and accepts the fresh price', async () => {
    mockGet.mockResolvedValueOnce(baseEvent({
      price_mismatch: { price_min: 20, price_max: 28, currency: 'EUR', has_free_tier: false },
    }));
    mockPatch.mockResolvedValueOnce(baseEvent({ price_min: 20, price_max: 28 }));
    renderEdit();

    await waitFor(() => expect(screen.getByText('Source price has changed')).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: 'Accept new price' }));

    await waitFor(() => expect(mockPatch).toHaveBeenCalledWith(
      '/organizer/claims/42/event',
      { accept_new_price: true },
    ));
  });

  it('editing the English title pins only that locale, not the Estonian one', async () => {
    mockGet.mockResolvedValueOnce(baseEvent());
    mockPatch.mockResolvedValueOnce(baseEvent());
    renderEdit();

    const enTitleInput = await screen.findByDisplayValue('Autumn Evening');
    await userEvent.clear(enTitleInput);
    await userEvent.type(enTitleInput, 'New autumn evening');
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }));

    await waitFor(() => expect(mockPatch).toHaveBeenCalledTimes(1));
    const [, body] = mockPatch.mock.calls[0];
    expect(body).toEqual({ title_en: 'New autumn evening' });
  });

  it('picking a category sends it alongside any other touched fields on save', async () => {
    mockGet.mockResolvedValueOnce(baseEvent());
    mockPatch.mockResolvedValueOnce(baseEvent({ categories: ['family_friendly', 'music'] }));
    renderEdit();

    await screen.findByDisplayValue('Sügisõhtu jazziklubis');
    await userEvent.click(screen.getByRole('button', { name: 'Categories' }));
    await userEvent.click(await screen.findByRole('option', { name: /Family/i }));
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }));

    await waitFor(() => expect(mockPatch).toHaveBeenCalledTimes(1));
    const [, body] = mockPatch.mock.calls[0] as [string, Record<string, unknown>];
    expect(body.category).toBeTruthy();
  });

  it('a failing edit surfaces the needs-fix message instead of success', async () => {
    mockGet.mockResolvedValueOnce(baseEvent());
    mockPatch.mockResolvedValueOnce(baseEvent({ status: 'classified' }));
    renderEdit();

    const urlInput = await screen.findByDisplayValue('https://fienta.com/e/sugisohtu');
    await userEvent.clear(urlInput);
    await userEvent.type(urlInput, 'https://fienta.com/e/updated');
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }));

    const status = await waitFor(() => screen.getByRole('status'));
    expect(status).toHaveTextContent(/didn't pass our publish checks/);
  });

  it('a failed save after a prior success hides the stale success status (#7)', async () => {
    mockGet.mockResolvedValueOnce(baseEvent());
    mockPatch.mockResolvedValueOnce(baseEvent({ title: 'New title' }));
    renderEdit();

    const titleInput = await screen.findByDisplayValue('Sügisõhtu jazziklubis');
    await userEvent.clear(titleInput);
    await userEvent.type(titleInput, 'New title');
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }));

    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent(/live on/i));

    mockPatch.mockRejectedValueOnce(new Error('network down'));
    const urlInput = screen.getByDisplayValue('https://fienta.com/e/sugisohtu');
    await userEvent.clear(urlInput);
    await userEvent.type(urlInput, 'https://fienta.com/e/broken');
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }));

    await waitFor(() => expect(mockPatch).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('mounts a RichTextEditor toolbar for Description on every locale, not a textarea', async () => {
    mockGet.mockResolvedValueOnce(baseEvent());
    renderEdit();

    await screen.findByDisplayValue('Sügisõhtu jazziklubis');
    expect(await screen.findByLabelText(/^description$/i)).toHaveAttribute('contenteditable', 'true');
    expect(screen.getByLabelText(/description \(en\)/i)).toHaveAttribute('contenteditable', 'true');
    expect(screen.getByLabelText(/description \(ru\)/i)).toHaveAttribute('contenteditable', 'true');
    expect(screen.getAllByRole('toolbar', { name: 'Formatting' })).toHaveLength(3);
    expect(document.querySelector('textarea')).not.toBeInTheDocument();
  });
});
