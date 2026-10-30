import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { makeTestQueryClient, renderWithProviders } from '../../test/utils';
import VenuePicker, { type VenuePickerValue } from './VenuePicker';
import { QUERY_KEYS } from '../../constants/api';
import { LOCALE_ET, type ContentLang } from '../../constants/core';
import { LOCALE_EN } from '../../_generated/sharedConstants';

vi.mock('../../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/client')>()),
  organizerApi: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

import { organizerApi } from '../../api/client';
const mockGet = vi.mocked(organizerApi.get);
const mockPatch = vi.mocked(organizerApi.patch);

const VENUES = [
  { id: 1, name: 'Kultuurikatel', name_en: null, name_ru: null, address: 'Põhja pst 27a, Tallinn' },
  { id: 2, name: 'Telliskivi', name_en: null, name_ru: null, address: 'Telliskivi 60a, Tallinn' },
];

/** Controlled-component wrapper — mirrors how EventSubmit wires
 * VenuePicker's value/onChange (and the shared content-language tab) to
 * its own form state. */
function Harness({ initial, contentLang = LOCALE_ET }: { initial: VenuePickerValue; contentLang?: ContentLang }) {
  const [value, setValue] = useState<VenuePickerValue>(initial);
  return (
    <>
      <VenuePicker id="venue" value={value} onChange={setValue} locale="en" contentLang={contentLang} />
      <div data-testid="value">{JSON.stringify(value)}</div>
    </>
  );
}

const EMPTY: VenuePickerValue = {
  mode: 'oneoff', save: false,
  name: '', nameEn: '', nameRu: '', address: '',
};

beforeEach(() => {
  mockGet.mockReset();
  mockPatch.mockReset();
  mockGet.mockResolvedValue(VENUES);
});

describe('VenuePicker', () => {
  it('picks a saved venue and reports it via onChange', async () => {
    renderWithProviders(<Harness initial={EMPTY} />);
    await userEvent.click(screen.getByRole('combobox'));
    await userEvent.click(await screen.findByText('Kultuurikatel'));

    expect(screen.getByTestId('value')).toHaveTextContent(JSON.stringify({ mode: 'saved', venueId: 1 }));
  });

  it('edits a picked saved venue via the CRUD API', async () => {
    mockPatch.mockResolvedValueOnce({ id: 1, name: 'Kultuurikatel (renamed)', address: 'New address' });
    renderWithProviders(<Harness initial={{ mode: 'saved', venueId: 1 }} />);

    await userEvent.click(await screen.findByRole('button', { name: /edit venue/i }));
    const nameInput = screen.getByPlaceholderText('Venue name');
    await userEvent.clear(nameInput);
    await userEvent.type(nameInput, 'Kultuurikatel (renamed)');
    await userEvent.click(screen.getByRole('button', { name: /save venue/i }));

    await waitFor(() =>
      expect(mockPatch).toHaveBeenCalledWith('/organizer/venues/1', {
        name: 'Kultuurikatel (renamed)',
        name_en: null,
        name_ru: null,
        address: 'Põhja pst 27a, Tallinn',
      }),
    );
  });

  it('keeps in-progress edits when a background refetch returns changed data for the same venue', async () => {
    const queryClient = makeTestQueryClient();
    renderWithProviders(<Harness initial={{ mode: 'saved', venueId: 1 }} />, { queryClient });

    await userEvent.click(await screen.findByRole('button', { name: /edit venue/i }));
    const nameInput = screen.getByPlaceholderText('Venue name');
    await userEvent.clear(nameInput);
    await userEvent.type(nameInput, 'Half-typed');

    // Changed row => new object identity (react-query's structural sharing
    // would otherwise hand back the same reference for deep-equal data).
    mockGet.mockResolvedValue(VENUES.map((v) => (v.id === 1 ? { ...v, address: 'Moved 1, Tallinn' } : v)));
    await act(async () => {
      await queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.organizerVenues] });
      // Let the re-hydration effect's microtask (if any) run before asserting.
      await new Promise((resolve) => setTimeout(resolve, 20));
    });

    expect(screen.getByPlaceholderText('Venue name')).toHaveValue('Half-typed');
  });

  it('edits the EN name/address on the active content-language tab, independent of the base fields', async () => {
    mockPatch.mockResolvedValueOnce({ id: 1, name: 'Kultuurikatel', name_en: 'The Culture Cauldron' });
    renderWithProviders(<Harness initial={{ mode: 'saved', venueId: 1 }} contentLang={LOCALE_EN} />);

    await userEvent.click(await screen.findByRole('button', { name: /edit venue/i }));
    // On the EN tab the base ET name never appears in an EN-labeled field.
    const nameInput = screen.getByPlaceholderText(/venue name \(en\)/i);
    expect(nameInput).toHaveValue('');
    await userEvent.type(nameInput, 'The Culture Cauldron');
    await userEvent.click(screen.getByRole('button', { name: /save venue/i }));

    await waitFor(() =>
      expect(mockPatch).toHaveBeenCalledWith('/organizer/venues/1', expect.objectContaining({
        name: 'Kultuurikatel',
        name_en: 'The Culture Cauldron',
      })),
    );
  });

  it('free-typing without the save checkbox stays a plain one-off', async () => {
    renderWithProviders(<Harness initial={EMPTY} />);
    await userEvent.click(screen.getByRole('combobox'));
    await userEvent.type(screen.getByRole('combobox'), 'Pop-up Garden');
    await userEvent.click(await screen.findByText(/use "Pop-up Garden" as a one-off venue/i));

    expect(screen.getByTestId('value')).toHaveTextContent(
      JSON.stringify({ mode: 'oneoff', save: false, name: 'Pop-up Garden', nameEn: '', nameRu: '', address: '' }),
    );
    expect(screen.queryByRole('checkbox')).not.toBeChecked();
  });

  it('checking "save this venue" flips save on the one-off value', async () => {
    renderWithProviders(<Harness initial={EMPTY} />);
    await userEvent.click(screen.getByRole('combobox'));
    await userEvent.type(screen.getByRole('combobox'), 'Pop-up Garden');
    await userEvent.click(await screen.findByText(/use "Pop-up Garden" as a one-off venue/i));
    await userEvent.click(screen.getByRole('checkbox'));

    expect(screen.getByTestId('value')).toHaveTextContent(
      JSON.stringify({ mode: 'oneoff', save: true, name: 'Pop-up Garden', nameEn: '', nameRu: '', address: '' }),
    );
  });
});
