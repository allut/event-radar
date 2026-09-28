import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import { useOrganizerEventForm } from './useOrganizerEventForm';
import { makeRouterQueryWrapper } from '../test/utils';

vi.mock('../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/client')>()),
  organizerApi: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

import { organizerApi } from '../api/client';
const mockGet = vi.mocked(organizerApi.get);
const mockPost = vi.mocked(organizerApi.post);
const mockPatch = vi.mocked(organizerApi.patch);

beforeEach(() => {
  mockGet.mockReset();
  mockPost.mockReset();
  mockPatch.mockReset();
});

function makeWrapper() {
  return makeRouterQueryWrapper().wrapper;
}

describe('useOrganizerEventForm — buildBody', () => {
  it('emits description_en/description_ru/important_info_en/important_info_ru when set', async () => {
    mockPost.mockResolvedValueOnce({ id: 1, slug: 's', status: 'published' });
    const { result } = renderHook(() => useOrganizerEventForm('en'), { wrapper: makeWrapper() });

    act(() => {
      result.current.setTitle('Jazz Night');
      result.current.setStartsAt('2026-08-01T18:00');
      result.current.setDescriptionEn('EN desc');
      result.current.setDescriptionRu('RU desc');
      result.current.setImportantInfoEn('EN info');
      result.current.setImportantInfoRu('RU info');
    });

    act(() => {
      result.current.submit({ preventDefault: () => {} } as React.FormEvent);
    });

    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(1));
    const [, body] = mockPost.mock.calls[0];
    expect(body).toMatchObject({
      description_en: 'EN desc',
      description_ru: 'RU desc',
      important_info_en: 'EN info',
      important_info_ru: 'RU info',
    });
  });
});

describe('useOrganizerEventForm — venue picker submit resolution (#178)', () => {
  it('submits venue_id as-is when a saved venue is picked', async () => {
    mockPost.mockResolvedValueOnce({ id: 1, slug: 's', status: 'published' });
    const { result } = renderHook(() => useOrganizerEventForm('en'), { wrapper: makeWrapper() });

    act(() => {
      result.current.setTitle('Jazz Night');
      result.current.setStartsAt('2026-08-01T18:00');
      result.current.setVenue({ mode: 'saved', venueId: 7 });
    });
    act(() => {
      result.current.submit({ preventDefault: () => {} } as React.FormEvent);
    });

    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(1));
    const [path, body] = mockPost.mock.calls[0];
    expect(path).toBe('/organizer/events');
    expect(body).toMatchObject({ venue_id: 7 });
    expect(body).not.toHaveProperty('venue_name');
  });

  it('creates the venue first when a one-off has "save this venue" checked, then submits with the new venue_id', async () => {
    mockPost
      .mockResolvedValueOnce({ id: 99, name: 'Pop-up Garden', address: 'Some St 1' })
      .mockResolvedValueOnce({ id: 1, slug: 's', status: 'published' });
    const { result } = renderHook(() => useOrganizerEventForm('en'), { wrapper: makeWrapper() });

    act(() => {
      result.current.setTitle('Jazz Night');
      result.current.setStartsAt('2026-08-01T18:00');
      result.current.setVenue({
        mode: 'oneoff', save: true,
        name: 'Pop-up Garden', nameEn: '', nameRu: '', address: 'Some St 1',
      });
    });
    act(() => {
      result.current.submit({ preventDefault: () => {} } as React.FormEvent);
    });

    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(2));
    expect(mockPost.mock.calls[0]).toEqual(['/organizer/venues', { name: 'Pop-up Garden', address: 'Some St 1' }]);
    const [eventPath, eventBody] = mockPost.mock.calls[1];
    expect(eventPath).toBe('/organizer/events');
    expect(eventBody).toMatchObject({ venue_id: 99 });
  });

  it('submits legacy venue_name/venue_address for an unsaved one-off, unchanged from today', async () => {
    mockPost.mockResolvedValueOnce({ id: 1, slug: 's', status: 'published' });
    const { result } = renderHook(() => useOrganizerEventForm('en'), { wrapper: makeWrapper() });

    act(() => {
      result.current.setTitle('Jazz Night');
      result.current.setStartsAt('2026-08-01T18:00');
      result.current.setVenue({
        mode: 'oneoff', save: false,
        name: 'Pop-up Garden', nameEn: '', nameRu: '', address: 'Some St 1',
      });
    });
    act(() => {
      result.current.submit({ preventDefault: () => {} } as React.FormEvent);
    });

    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(1));
    const [path, body] = mockPost.mock.calls[0];
    expect(path).toBe('/organizer/events');
    expect(body).toMatchObject({ venue_name: 'Pop-up Garden', venue_address: 'Some St 1' });
    expect(body).not.toHaveProperty('venue_id');
  });

  it('explicitly unlinks venue_id in edit mode when switching a linked event to an empty one-off', async () => {
    // Regression: the PATCH handler only clears venue_id when the key is
    // present in the request at all — omitting it (as an empty body would)
    // leaves the event silently still linked to its old saved venue.
    mockGet.mockResolvedValueOnce({
      events: [{
        id: 9, title: 'Existing Event', description: null, important_info: null,
        starts_at: '2026-08-01T18:00:00Z', ends_at: null,
        venue_name: null, venue_address: null, venue_id: 7,
        url: null, image_url: null, price_min: null, price_max: null, categories: [],
      }],
      limit: 24, offset: 0,
    });
    mockPatch.mockResolvedValueOnce({ id: 9, slug: 'existing-event', status: 'published' });
    const { result } = renderHook(() => useOrganizerEventForm('en', 9), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.venue).toEqual({ mode: 'saved', venueId: 7 }));

    act(() => {
      result.current.setVenue({
        mode: 'oneoff', save: false,
        name: '', nameEn: '', nameRu: '', address: '',
      });
    });
    act(() => {
      result.current.submit({ preventDefault: () => {} } as React.FormEvent);
    });

    await waitFor(() => expect(mockPatch).toHaveBeenCalledTimes(1));
    const [, body] = mockPatch.mock.calls[0];
    expect(body).toMatchObject({ venue_id: null });
  });

  it('sends locale= on the edit-mode prefill list request (#454)', async () => {
    mockGet.mockResolvedValueOnce({
      events: [{
        id: 9, title: 'Existing Event', description: null, important_info: null,
        starts_at: '2026-08-01T18:00:00Z', ends_at: null,
        venue_name: null, venue_address: null, venue_id: 7,
        url: null, image_url: null, price_min: null, price_max: null, categories: [],
      }],
      limit: 24, offset: 0,
    });
    renderHook(() => useOrganizerEventForm('ru', 9), { wrapper: makeWrapper() });

    await waitFor(() => expect(mockGet).toHaveBeenCalled());
    expect(mockGet).toHaveBeenCalledWith(expect.stringMatching(/\/organizer\/events\?.*[?&]locale=ru/));
  });
});

describe('useOrganizerEventForm — edit-mode prefill', () => {
  it('prefills ET slot from the raw *_localized.et value, not the display-locale-resolved field', async () => {
    // Organizer's display locale is 'en', so `title`/`description`/`important_info`
    // in the list response are English-resolved — but the ET form slot must
    // still show the Estonian base text from title_localized.et.
    mockGet.mockResolvedValueOnce({
      events: [
        {
          id: 9,
          title: 'English Display Title',
          description: 'English Display Description',
          important_info: 'English Display Info',
          starts_at: '2026-08-01T18:00:00Z',
          ends_at: null,
          venue_name: null,
          venue_address: null,
          url: null,
          image_url: null,
          price_min: null,
          price_max: null,
          categories: [],
          title_localized: { et: 'Eesti Pealkiri', en: 'English Title' },
          description_localized: { et: 'Eesti Kirjeldus', en: 'English Desc' },
          important_info_localized: { et: 'Eesti Info' },
        },
      ],
      limit: 24,
      offset: 0,
    });

    const { result } = renderHook(() => useOrganizerEventForm('en', 9), { wrapper: makeWrapper() });

    await waitFor(() => expect(result.current.title).toBe('Eesti Pealkiri'));
    expect(result.current.titleEn).toBe('English Title');
    expect(result.current.titleRu).toBe('');
    expect(result.current.description).toBe('Eesti Kirjeldus');
    expect(result.current.descriptionEn).toBe('English Desc');
    expect(result.current.importantInfo).toBe('Eesti Info');
    expect(result.current.importantInfoEn).toBe('');
  });

  it('prefills the picker in saved mode when the event has a venue_id', async () => {
    mockGet.mockResolvedValueOnce({
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
          venue_id: 7,
          url: null,
          image_url: null,
          price_min: null,
          price_max: null,
          categories: [],
        },
      ],
      limit: 24,
      offset: 0,
    });

    const { result } = renderHook(() => useOrganizerEventForm('en', 9), { wrapper: makeWrapper() });

    await waitFor(() => expect(result.current.venue).toEqual({ mode: 'saved', venueId: 7 }));
  });
});
