import { createElement, type ReactNode } from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { useOrganizerEventForm } from './useOrganizerEventForm';
import { makeQueryWrapper } from '../test/utils';

vi.mock('../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/client')>()),
  organizerApi: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

import { organizerApi } from '../api/client';
const mockGet = vi.mocked(organizerApi.get);
const mockPost = vi.mocked(organizerApi.post);

beforeEach(() => {
  mockGet.mockReset();
  mockPost.mockReset();
});

function makeWrapper() {
  const { wrapper: queryWrapper } = makeQueryWrapper();
  function Wrapper({ children }: { children: ReactNode }) {
    return createElement(MemoryRouter, null, createElement(queryWrapper, null, children));
  }
  return Wrapper;
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
});
