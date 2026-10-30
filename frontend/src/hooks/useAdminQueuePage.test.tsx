// The admin queue paging layer (spec #551): mergeQueueRows as a pure
// function, and useAdminQueuePage driven through a tiny queue harness (a
// list, a note draft, an Approve action and the <Pager>) under the router and
// query wrapper, with the `api` module mocked as a live server-side queue.
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { LocationProbe, renderWithProviders } from '../test/utils';
import Pager from '../components/Pager';
import { mergeQueueRows, useAdminQueuePage, type ActionSpot } from './useAdminQueuePage';

vi.mock('../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/client')>()),
  api: { get: vi.fn(), post: vi.fn() },
}));

import { api } from '../api/client';
const mockGet = vi.mocked(api.get);
const mockPost = vi.mocked(api.post);

const PAGE_SIZE = 3;

interface Row {
  id: number;
}

interface QueueResponse {
  rows: Row[];
  total: number;
  offset: number;
}

const getId = (row: Row) => row.id;
const rowsOf = (...ids: number[]): Row[] => ids.map((id) => ({ id }));

describe('mergeQueueRows', () => {
  const tagged = (...entries: [id: number, slot: number][]) =>
    new Map(entries.map(([id, slot]) => [id, { item: { id }, slot }]));

  it('returns the server rows unchanged when nothing is tagged', () => {
    expect(mergeQueueRows(rowsOf(1, 2, 3), tagged(), getId)).toEqual(rowsOf(1, 2, 3));
  });

  it('keeps a resolved row in its slot once the server drops it, with the pulled-up row last', () => {
    expect(mergeQueueRows(rowsOf(1, 3, 4), tagged([2, 1]), getId)).toEqual(rowsOf(1, 2, 3, 4));
  });

  it('puts several tagged rows back in slot order whatever order they were tagged in', () => {
    expect(mergeQueueRows(rowsOf(2, 5, 6), tagged([4, 3], [1, 0], [3, 2]), getId)).toEqual(
      rowsOf(1, 2, 3, 4, 5, 6),
    );
  });

  it('does not duplicate a tagged row the server still returns', () => {
    expect(mergeQueueRows(rowsOf(1, 2, 3), tagged([2, 1]), getId)).toEqual(rowsOf(1, 2, 3));
  });

  it('keeps every tagged row of a page the server has emptied', () => {
    expect(mergeQueueRows([], tagged([8, 1], [7, 0]), getId)).toEqual(rowsOf(7, 8));
  });
});

/** The queue on the "server": ids still awaiting review, in order. */
let queue: number[] = [];
let pendingActions: Array<() => void> = [];

function serveQueue(ids: number[]) {
  queue = [...ids];
  mockGet.mockImplementation(async (url: string) => {
    const offset = Number(new URL(url, 'http://x').searchParams.get('offset'));
    return {
      rows: rowsOf(...queue.slice(offset, offset + PAGE_SIZE)),
      total: queue.length,
      offset,
    } as never;
  });
  // An action resolves only when the test releases it; the row then leaves
  // the queue, as the backend's approve does.
  mockPost.mockImplementation(
    (url: string) =>
      new Promise((resolve) => {
        const id = Number(url.split('/')[2]);
        pendingActions.push(() => {
          queue = queue.filter((queued) => queued !== id);
          resolve({} as never);
        });
      }),
  );
}

async function releaseActions() {
  const actions = pendingActions;
  pendingActions = [];
  await act(async () => {
    for (const release of actions) release();
  });
}

function QueueHarness() {
  const [note, setNote] = useState('');
  const queuePage = useAdminQueuePage<QueueResponse, Row, 'approved'>({
    queryKey: ['queue'],
    pageSize: PAGE_SIZE,
    fetchPage: ({ limit, offset }) => api.get<QueueResponse>(`/queue?limit=${limit}&offset=${offset}`),
    select: (data) => ({ items: data.rows, total: data.total, offset: data.offset }),
    getId,
    onPageSettled: () => setNote(''),
  });
  const { rows, tags, tagRow, actionSpot, selectedId, setSelectedId, listRef, pagerProps } = queuePage;
  const approve = useMutation({
    mutationFn: ({ item }: { item: Row; spot: ActionSpot }) => api.post(`/queue/${item.id}/approve`, {}),
    onSuccess: (_result, { item, spot }) => {
      if (tagRow(item, 'approved', spot)) setNote('');
    },
  });
  const currentId = selectedId ?? rows[0]?.id ?? null;
  return (
    <>
      <div ref={listRef}>
        {rows.map((row) => (
          <button
            key={row.id}
            type="button"
            aria-pressed={row.id === currentId}
            onClick={() => setSelectedId(row.id)}
          >
            {`Row ${row.id}${tags.has(row.id) ? ' approved' : ''}`}
          </button>
        ))}
      </div>
      <textarea aria-label="Note" value={note} onChange={(event) => setNote(event.target.value)} />
      <button
        type="button"
        onClick={() => {
          const item = rows.find((row) => row.id === currentId);
          if (item) approve.mutate({ item, spot: actionSpot(item) });
        }}
      >
        Approve
      </button>
      <button type="button" onClick={() => void queuePage.refetch()}>
        Refetch
      </button>
      <Pager {...pagerProps} locale="en" liveNoun="items" />
      <LocationProbe />
    </>
  );
}

const location = () => screen.getByTestId('location-probe').textContent;
const rowLabels = () =>
  screen.getAllByRole('button', { name: /^Row / }).map((button) => button.textContent);

beforeEach(() => {
  mockGet.mockReset();
  mockPost.mockReset();
  pendingActions = [];
});

describe('useAdminQueuePage', () => {
  it('keeps an approved row in place and pulls the next row up from the following page', async () => {
    serveQueue([1, 2, 3, 4, 5]);
    renderWithProviders(<QueueHarness />, { route: '/queue' });
    await waitFor(() => expect(rowLabels()).toEqual(['Row 1', 'Row 2', 'Row 3']));

    await userEvent.click(screen.getByRole('button', { name: 'Row 2' }));
    await userEvent.type(screen.getByLabelText('Note'), 'ok');
    await userEvent.click(screen.getByRole('button', { name: 'Approve' }));
    await releaseActions();

    await waitFor(() => expect(rowLabels()).toEqual(['Row 1', 'Row 2 approved', 'Row 3', 'Row 4']));
    expect(screen.getByLabelText('Note')).toHaveValue('');
  });

  it('still tags the row in its slot and clears the note when a refetch dropped it before the action returned', async () => {
    serveQueue([1, 2, 3, 4, 5]);
    renderWithProviders(<QueueHarness />, { route: '/queue' });
    await waitFor(() => expect(rowLabels()).toEqual(['Row 1', 'Row 2', 'Row 3']));
    await userEvent.click(screen.getByRole('button', { name: 'Row 2' }));
    await userEvent.type(screen.getByLabelText('Note'), 'ok');
    await userEvent.click(screen.getByRole('button', { name: 'Approve' }));
    // The server commits the approve and a focus refetch lands before the
    // POST response does.
    queue = queue.filter((id) => id !== 2);
    await userEvent.click(screen.getByRole('button', { name: 'Refetch' }));
    await waitFor(() => expect(rowLabels()).toEqual(['Row 1', 'Row 3', 'Row 4']));

    await releaseActions();

    await waitFor(() => expect(rowLabels()).toEqual(['Row 1', 'Row 2 approved', 'Row 3', 'Row 4']));
    expect(screen.getByLabelText('Note')).toHaveValue('');
  });

  it('holds a last page the admin has cleared instead of clamping it away', async () => {
    serveQueue([1, 2, 3, 4]);
    renderWithProviders(<QueueHarness />, { route: '/queue?page=2' });
    await waitFor(() => expect(rowLabels()).toEqual(['Row 4']));

    await userEvent.click(screen.getByRole('button', { name: 'Approve' }));
    await releaseActions();

    await waitFor(() => expect(screen.getByRole('button', { name: 'Row 4 approved' })).toBeInTheDocument());
    await waitFor(() => expect(mockGet).toHaveBeenCalledTimes(2));
    await act(async () => {});
    expect(location()).toBe('/queue?page=2');
  });

  it('an action still pending when the admin changes page never lands on the new page', async () => {
    serveQueue([1, 2, 3, 4, 5, 6, 7]);
    renderWithProviders(<QueueHarness />, { route: '/queue' });
    await waitFor(() => expect(rowLabels()).toEqual(['Row 1', 'Row 2', 'Row 3']));

    await userEvent.type(screen.getByLabelText('Note'), 'ok');
    await userEvent.click(screen.getByRole('button', { name: 'Approve' }));
    await userEvent.click(screen.getByRole('link', { name: 'Page 2' }));
    await waitFor(() => expect(rowLabels()).toEqual(['Row 4', 'Row 5', 'Row 6']));
    await userEvent.type(screen.getByLabelText('Note'), 'draft for 4');

    await releaseActions();

    // The page refetches (row 1 left, so row 4 moved up to page 1) but row 1
    // is never tagged onto page 2, and the draft typed there survives.
    await waitFor(() => expect(rowLabels()).toEqual(['Row 5', 'Row 6', 'Row 7']));
    expect(screen.getByLabelText('Note')).toHaveValue('draft for 4');
  });

  it('a silent clamp to another page selects its first row and resets the note without moving focus', async () => {
    serveQueue([1, 2, 3, 4, 5]);
    renderWithProviders(<QueueHarness />, { route: '/queue?page=2' });
    await waitFor(() => expect(rowLabels()).toEqual(['Row 4', 'Row 5']));
    await userEvent.click(screen.getByRole('button', { name: 'Row 5' }));
    await userEvent.type(screen.getByLabelText('Note'), 'note for 5');

    // Another admin clears page 2; the refetch empties it and it clamps.
    queue = [1, 2, 3];
    await userEvent.click(screen.getByRole('button', { name: 'Refetch' }));

    await waitFor(() => expect(location()).toBe('/queue'));
    await waitFor(() => expect(rowLabels()).toEqual(['Row 1', 'Row 2', 'Row 3']));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Row 1' })).toHaveAttribute('aria-pressed', 'true'));
    expect(screen.getByLabelText('Note')).toHaveValue('');
    expect(screen.getByRole('button', { name: 'Refetch' })).toHaveFocus();
  });
});
