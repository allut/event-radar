import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import EventSubmit from './EventSubmit';
import { renderWithProviders } from '../../test/utils';

vi.mock('../../lib/auth', () => ({
  getLocale: vi.fn(() => 'en'),
  getStoredLocale: vi.fn(() => 'en'),
  setLocale: vi.fn(),
}));

vi.mock('../../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/client')>()),
  organizerApi: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

import { organizerApi } from '../../api/client';
const mockGet = vi.mocked(organizerApi.get);
const mockPost = vi.mocked(organizerApi.post);
const mockPatch = vi.mocked(organizerApi.patch);

beforeEach(() => {
  mockGet.mockReset();
  mockPost.mockReset();
  mockPatch.mockReset();
  // OrganizerProfileNudge (rendered on every EventSubmit view) fires its own
  // organizerApi.get('/organizer/profile') independent of edit-mode's
  // /organizer/events fetch — default it to a name set so the nudge banner
  // doesn't appear in tests that don't care about it.
  mockGet.mockImplementation((path: string) => {
    if (path.includes('/organizer/profile')) return Promise.resolve({ name: 'Test Organizer' });
    if (path.includes('/organizer/venues')) return Promise.resolve([]);
    return Promise.resolve(undefined);
  });
});

describe('EventSubmit (create)', () => {
  it('renders the create-mode title and required fields', () => {
    renderWithProviders(<EventSubmit />, { route: '/organizer/submit', pathPattern: '/organizer/submit' });
    expect(screen.getByText(/submit an event/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/^title \(et\)$/i)).toBeInTheDocument();
  });

  it('disables submit until title and start time are filled', () => {
    renderWithProviders(<EventSubmit />, { route: '/organizer/submit', pathPattern: '/organizer/submit' });
    expect(screen.getByRole('button', { name: /submit event/i })).toBeDisabled();
  });

  it('submits a POST to /organizer/events with the entered title', async () => {
    mockPost.mockResolvedValueOnce({ id: 5, slug: 'new-event', status: 'published' });
    renderWithProviders(<EventSubmit />, { route: '/organizer/submit', pathPattern: '/organizer/submit' });

    await userEvent.type(screen.getByLabelText(/^title \(et\)$/i), 'Jazz Night');
    const startsInput = screen.getByLabelText(/starts/i);
    await userEvent.type(startsInput, '2026-08-01 18:00');

    await waitFor(() => expect(screen.getByRole('button', { name: /submit event/i })).not.toBeDisabled());
    await userEvent.click(screen.getByRole('button', { name: /submit event/i }));

    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(1));
    const [path, body] = mockPost.mock.calls[0];
    expect(path).toBe('/organizer/events');
    expect(body).toMatchObject({ title: 'Jazz Night' });
  });

  it('picks categories as chips and submits them as a list', async () => {
    mockPost.mockResolvedValueOnce({ id: 7, slug: 'new-event-3', status: 'published' });
    renderWithProviders(<EventSubmit />, { route: '/organizer/submit', pathPattern: '/organizer/submit' });

    await userEvent.type(screen.getByLabelText(/^title \(et\)$/i), 'Jazz Night');
    await userEvent.type(screen.getByLabelText(/starts/i), '2026-08-01 18:00');

    const group = screen.getByRole('group', { name: 'Categories' });
    await userEvent.click(within(group).getByRole('button', { name: 'Music' }));
    await userEvent.click(within(group).getByRole('button', { name: 'Nightlife' }));

    await waitFor(() => expect(screen.getByRole('button', { name: /submit event/i })).not.toBeDisabled());
    await userEvent.click(screen.getByRole('button', { name: /submit event/i }));

    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(1));
    const [, body] = mockPost.mock.calls[0];
    expect(body).toMatchObject({ categories: ['music', 'nightlife'] });
  });

  it('ignores a fourth category once the cap is reached and allows removing one', async () => {
    renderWithProviders(<EventSubmit />, { route: '/organizer/submit', pathPattern: '/organizer/submit' });
    const group = screen.getByRole('group', { name: 'Categories' });

    for (const name of ['Music', 'Nightlife', 'Comedy']) {
      await userEvent.click(within(group).getByRole('button', { name }));
    }
    expect(screen.getByText(/3 of 3 picked/)).toBeInTheDocument();

    await userEvent.click(within(group).getByRole('button', { name: 'Family' }));
    expect(screen.getByText(/3 of 3 picked/)).toBeInTheDocument();
    expect(within(group).getByRole('button', { name: 'Family' })).toHaveAttribute('aria-disabled', 'true');

    await userEvent.click(within(group).getByRole('button', { name: 'Remove Comedy' }));
    expect(screen.getByText(/2 of 3 picked/)).toBeInTheDocument();
    await userEvent.click(within(group).getByRole('button', { name: 'Family' }));
    expect(screen.getByText(/3 of 3 picked/)).toBeInTheDocument();
  });

  it('shows the empty marker state on a lang tab with no content', () => {
    renderWithProviders(<EventSubmit />, { route: '/organizer/submit', pathPattern: '/organizer/submit' });
    const langTabs = screen.getByRole('group', { name: /content language/i });
    expect(within(langTabs).getByRole('button', { name: /^EN, empty$/ })).toBeInTheDocument();
  });

  it('shows the partial marker state when ET has a field EN lacks', async () => {
    renderWithProviders(<EventSubmit />, { route: '/organizer/submit', pathPattern: '/organizer/submit' });
    const langTabs = screen.getByRole('group', { name: /content language/i });

    await userEvent.type(screen.getByLabelText(/^title \(et\)$/i), 'Jazz Night');
    await userEvent.type(await screen.findByLabelText(/^description \(et\)$/i), 'ET description');
    await userEvent.click(within(langTabs).getByRole('button', { name: /^EN,/ }));
    await userEvent.type(screen.getByLabelText(/^title \(en\)$/i), 'Jazz Night');

    expect(within(langTabs).getByRole('button', { name: /^EN, partially translated$/ })).toBeInTheDocument();
  });

  it('shows the matched marker state once every ET field has an EN counterpart', async () => {
    renderWithProviders(<EventSubmit />, { route: '/organizer/submit', pathPattern: '/organizer/submit' });
    const langTabs = screen.getByRole('group', { name: /content language/i });

    await userEvent.type(screen.getByLabelText(/^title \(et\)$/i), 'Jazz Night');
    await userEvent.click(within(langTabs).getByRole('button', { name: /^EN,/ }));
    await userEvent.type(screen.getByLabelText(/^title \(en\)$/i), 'Jazz Night');

    expect(within(langTabs).getByRole('button', { name: /^EN, translated$/ })).toBeInTheDocument();
  });

  it('switches to the EN tab and submits description_en/important_info_en', async () => {
    mockPost.mockResolvedValueOnce({ id: 6, slug: 'new-event-2', status: 'published' });
    renderWithProviders(<EventSubmit />, { route: '/organizer/submit', pathPattern: '/organizer/submit' });

    await userEvent.type(screen.getByLabelText(/^title \(et\)$/i), 'Jazz Night');
    await userEvent.type(screen.getByLabelText(/starts/i), '2026-08-01 18:00');

    const langTabs = screen.getByRole('group', { name: /content language/i });
    await userEvent.click(within(langTabs).getByRole('button', { name: /^EN,/ }));
    await waitFor(() =>
      expect(within(langTabs).getByRole('button', { name: /^EN,/ })).toHaveAttribute('aria-pressed', 'true'),
    );
    await userEvent.type(await screen.findByLabelText(/^description \(en\)$/i), 'An English description');
    await userEvent.type(await screen.findByLabelText(/important info .*\(en\)$/i), 'English ticket info');

    await waitFor(() => expect(screen.getByRole('button', { name: /submit event/i })).not.toBeDisabled());
    await userEvent.click(screen.getByRole('button', { name: /submit event/i }));

    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(1));
    const [, body] = mockPost.mock.calls[0];
    expect(body).toMatchObject({
      title: 'Jazz Night',
      description_en: '<p>An English description</p>',
      important_info_en: '<p>English ticket info</p>',
    });
  });

  it('mounts a RichTextEditor toolbar for Description and Important-info instead of a textarea, on every locale tab', async () => {
    renderWithProviders(<EventSubmit />, { route: '/organizer/submit', pathPattern: '/organizer/submit' });
    const langTabs = screen.getByRole('group', { name: /content language/i });

    for (const tabName of [/^ET,/, /^EN,/, /^RU,/]) {
      await userEvent.click(within(langTabs).getByRole('button', { name: tabName }));
      expect(await screen.findByLabelText(/^description /i)).toHaveAttribute('contenteditable', 'true');
      expect(screen.getByLabelText(/important info /i)).toHaveAttribute('contenteditable', 'true');
      expect(screen.getAllByRole('toolbar', { name: 'Formatting' })).toHaveLength(2);
    }
    expect(document.querySelector('textarea')).not.toBeInTheDocument();
  });

  it('formats Description via the toolbar and submits the resulting HTML', async () => {
    mockPost.mockResolvedValueOnce({ id: 8, slug: 'new-event-4', status: 'published' });
    renderWithProviders(<EventSubmit />, { route: '/organizer/submit', pathPattern: '/organizer/submit' });

    await userEvent.type(screen.getByLabelText(/^title \(et\)$/i), 'Jazz Night');
    await userEvent.type(screen.getByLabelText(/starts/i), '2026-08-01 18:00');

    const description = await screen.findByLabelText(/^description \(et\)$/i);
    await userEvent.click(description);
    await userEvent.keyboard('Loud music');
    await userEvent.keyboard('{Control>}a{/Control}');
    await userEvent.click(screen.getAllByRole('button', { name: 'Bold' })[0]);

    await waitFor(() => expect(screen.getByRole('button', { name: /submit event/i })).not.toBeDisabled());
    await userEvent.click(screen.getByRole('button', { name: /submit event/i }));

    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(1));
    const [, body] = mockPost.mock.calls[0] as [string, Record<string, unknown>];
    expect(body.description).toMatch(/<strong>.*Loud music.*<\/strong>/);
  });

  it('keeps each locale tab\'s Description content independent when switching tabs', async () => {
    renderWithProviders(<EventSubmit />, { route: '/organizer/submit', pathPattern: '/organizer/submit' });
    const langTabs = screen.getByRole('group', { name: /content language/i });

    const etDescription = await screen.findByLabelText(/^description \(et\)$/i);
    await userEvent.click(etDescription);
    await userEvent.keyboard('ET only text');

    await userEvent.click(within(langTabs).getByRole('button', { name: /^EN,/ }));
    const enDescription = await screen.findByLabelText(/^description \(en\)$/i);
    expect(enDescription).toHaveTextContent('');
    await userEvent.click(enDescription);
    await userEvent.keyboard('EN only text');

    await userEvent.click(within(langTabs).getByRole('button', { name: /^ET,/ }));
    expect(await screen.findByLabelText(/^description \(et\)$/i)).toHaveTextContent('ET only text');

    await userEvent.click(within(langTabs).getByRole('button', { name: /^EN,/ }));
    expect(await screen.findByLabelText(/^description \(en\)$/i)).toHaveTextContent('EN only text');
  });
});

describe('EventSubmit (edit)', () => {
  it('prefills from the organizer\'s event list and submits a PATCH', async () => {
    const eventsResponse = {
      events: [
        {
          id: 9,
          title: 'Existing Event',
          description: null,
          important_info: null,
          starts_at: '2026-08-01T18:00:00Z',
          ends_at: null,
          venue_name: null,
          venue_address: null,
          venue_id: null,
          url: null,
          image_url: null,
          price_min: null,
          price_max: null,
          categories: [],
        },
      ],
      limit: 24,
      offset: 0,
    };
    mockGet.mockImplementation((path: string) => {
      if (path.includes('/organizer/profile')) return Promise.resolve({ name: 'Test Organizer' });
      if (path.includes('/organizer/venues')) return Promise.resolve([]);
      return Promise.resolve(eventsResponse);
    });
    mockPatch.mockResolvedValueOnce({ id: 9, slug: 'existing-event', status: 'published' });

    renderWithProviders(<EventSubmit />, {
      route: '/organizer/events/9/edit',
      pathPattern: '/organizer/events/:id/edit',
    });

    expect(await screen.findByDisplayValue('Existing Event')).toBeInTheDocument();
    expect(screen.getByText(/edit event/i)).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /save changes/i }));
    await waitFor(() => expect(mockPatch).toHaveBeenCalledWith('/organizer/events/9', expect.objectContaining({ title: 'Existing Event' })));
  });

  function editEventsResponse(categories: string[]) {
    return {
      events: [
        {
          id: 9, title: 'Existing Event', description: null, important_info: null,
          starts_at: '2026-08-01T18:00:00Z', ends_at: null,
          venue_name: null, venue_address: null, venue_id: null,
          url: null, image_url: null, price_min: null, price_max: null,
          categories,
        },
      ],
      limit: 24,
      offset: 0,
    };
  }

  function mountEdit(categories: string[]) {
    mockGet.mockImplementation((path: string) => {
      if (path.includes('/organizer/profile')) return Promise.resolve({ name: 'Test Organizer' });
      if (path.includes('/organizer/venues')) return Promise.resolve([]);
      return Promise.resolve(editEventsResponse(categories));
    });
    mockPatch.mockResolvedValueOnce({ id: 9, slug: 'existing-event', status: 'published' });
    renderWithProviders(<EventSubmit />, {
      route: '/organizer/events/9/edit',
      pathPattern: '/organizer/events/:id/edit',
    });
  }

  it('prefills every existing category (up to the cap) and omits them from an untouched PATCH', async () => {
    mountEdit(['music', 'family', 'comedy', 'cinema']);
    await screen.findByDisplayValue('Existing Event');

    const group = screen.getByRole('group', { name: 'Categories' });
    expect(within(group).getByRole('button', { name: 'Remove Music' })).toBeInTheDocument();
    expect(within(group).getByRole('button', { name: 'Remove Family' })).toBeInTheDocument();
    expect(within(group).getByRole('button', { name: 'Remove Comedy' })).toBeInTheDocument();
    expect(within(group).queryByRole('button', { name: 'Remove Cinema' })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /save changes/i }));
    await waitFor(() => expect(mockPatch).toHaveBeenCalledTimes(1));
    expect(mockPatch.mock.calls[0][1]).not.toHaveProperty('categories');
  });

  it('sends the changed category set in a PATCH', async () => {
    mountEdit(['music', 'family']);
    await screen.findByDisplayValue('Existing Event');

    const group = screen.getByRole('group', { name: 'Categories' });
    await userEvent.click(within(group).getByRole('button', { name: 'Remove Family' }));
    await userEvent.click(within(group).getByRole('button', { name: 'Theatre' }));
    await userEvent.click(screen.getByRole('button', { name: /save changes/i }));

    await waitFor(() => expect(mockPatch).toHaveBeenCalledTimes(1));
    expect(mockPatch.mock.calls[0][1]).toMatchObject({ categories: ['music', 'theater'] });
  });

  it('does not send categories when the organizer clears them all', async () => {
    mountEdit(['music']);
    await screen.findByDisplayValue('Existing Event');

    const group = screen.getByRole('group', { name: 'Categories' });
    await userEvent.click(within(group).getByRole('button', { name: 'Remove Music' }));
    await userEvent.click(screen.getByRole('button', { name: /save changes/i }));

    await waitFor(() => expect(mockPatch).toHaveBeenCalledTimes(1));
    expect(mockPatch.mock.calls[0][1]).not.toHaveProperty('categories');
  });

  it('round-trips a formatted description into the editor and back out on save', async () => {
    const eventsResponse = {
      events: [
        {
          id: 10,
          title: 'Existing Event',
          description: '<p><strong>Bold</strong> description</p>',
          important_info: null,
          starts_at: '2026-08-01T18:00:00Z',
          ends_at: null,
          venue_name: null,
          venue_address: null,
          venue_id: null,
          url: null,
          image_url: null,
          price_min: null,
          price_max: null,
          categories: [],
        },
      ],
      limit: 24,
      offset: 0,
    };
    mockGet.mockImplementation((path: string) => {
      if (path.includes('/organizer/profile')) return Promise.resolve({ name: 'Test Organizer' });
      if (path.includes('/organizer/venues')) return Promise.resolve([]);
      return Promise.resolve(eventsResponse);
    });
    mockPatch.mockResolvedValueOnce({ id: 10, slug: 'existing-event', status: 'published' });

    renderWithProviders(<EventSubmit />, {
      route: '/organizer/events/10/edit',
      pathPattern: '/organizer/events/:id/edit',
    });

    const description = await screen.findByLabelText(/^description \(et\)$/i);
    await waitFor(() => expect(description.querySelector('strong')).toHaveTextContent('Bold'));

    await userEvent.click(screen.getByRole('button', { name: /save changes/i }));
    await waitFor(() => expect(mockPatch).toHaveBeenCalledWith(
      '/organizer/events/10',
      expect.objectContaining({ description: '<p><strong>Bold</strong> description</p>' }),
    ));
  });
});
