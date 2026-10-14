// The shared paging layer tested as one seam (spec #551, ticket #552):
// usePageParam + usePagedQuery + <Pager>, driven through a tiny harness list
// under the router and query wrapper, with the `api` module mocked and the
// location probe reading the URL.
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Link, useNavigate, useNavigationType, useSearchParams } from 'react-router-dom';
import { LocationProbe, renderWithProviders } from '../../test/utils';
import { usePageParam } from '../../hooks/usePageParam';
import { usePagedQuery } from '../../hooks/usePagedQuery';
import Pager, { type PagerProps } from './Pager';

vi.mock('../../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/client')>()),
  api: { get: vi.fn() },
}));

import { api } from '../../api/client';
const mockGet = vi.mocked(api.get);

const PAGE_SIZE = 10;

interface Row {
  id: number;
}

interface ListResponse {
  rows: Row[];
  total: number;
  limit: number;
  offset: number;
  total_is_lower_bound?: boolean;
}

function requestedOffset(url: string): number {
  return Number(new URL(url, 'http://x').searchParams.get('offset'));
}

/** Serves a list of `total` rows (ids 1..total), sliced by the request offset. */
function serve(total: number, extra: Partial<ListResponse> = {}) {
  mockGet.mockImplementation(async (url: string) => {
    const offset = requestedOffset(url);
    const rows: Row[] = [];
    for (let id = offset + 1; id <= Math.min(offset + PAGE_SIZE, total); id++) rows.push({ id });
    return { rows, total, limit: PAGE_SIZE, offset, ...extra } as never;
  });
}

function NavTypeProbe() {
  return <div data-testid="nav-type">{useNavigationType()}</div>;
}

function BackButton() {
  const navigate = useNavigate();
  return (
    <button type="button" onClick={() => navigate(-1)}>
      Back
    </button>
  );
}

interface HarnessProps {
  onPageSettled?: () => void;
  holdEmptyPage?: boolean;
  dropOnPageChange?: string[];
}

function Harness({ onPageSettled, holdEmptyPage, dropOnPageChange }: HarnessProps) {
  // `?off=1` disables the query, as Explore does for an emptied facet.
  const [enabledParams] = useSearchParams();
  const enabled = enabledParams.get('off') !== '1';
  const { setListParams } = usePageParam({ defaults: { sort: 'relevance' } });
  const [searchParams] = useSearchParams();
  const q = searchParams.get('q') ?? '';
  const paged = usePagedQuery({
    queryKey: ['harness', q, enabled],
    pageSize: PAGE_SIZE,
    fetchPage: ({ limit, offset }) =>
      api.get<ListResponse>(`/list?limit=${limit}&offset=${offset}&q=${q}`),
    select: (data) => ({
      items: data.rows,
      total: data.total,
      offset: data.offset,
      totalIsLowerBound: data.total_is_lower_bound,
    }),
    onPageSettled,
    holdEmptyPage,
    enabled,
  });
  return (
    <>
      <div data-testid="paged-state">
        {paged.isPlaceholderData ? 'placeholder' : 'settled'} total={paged.total}
      </div>
      <ul>
        {paged.items.map((row) => (
          <li key={row.id}>Row {row.id}</li>
        ))}
      </ul>
      <button
        type="button"
        onClick={() =>
          setListParams((params) => {
            params.set('q', 'jazz');
            return params;
          })
        }
      >
        Search jazz
      </button>
      <button
        type="button"
        onClick={() =>
          setListParams((params) => {
            params.set('sort', 'relevance');
            return params;
          })
        }
      >
        Default sort
      </button>
      <button
        type="button"
        onClick={() =>
          setListParams((params) => {
            params.set('off', '1');
            return params;
          })
        }
      >
        Disable
      </button>
      <button type="button" onClick={() => void paged.refetch()}>
        Refetch
      </button>
      <BackButton />
      {/* An app link to the list (a nav or preset chip), not a pager link. */}
      <Link to="/list">List home</Link>
      <Pager {...paged.pagerProps} locale="en" dropOnPageChange={dropOnPageChange} />
      <LocationProbe />
      <NavTypeProbe />
    </>
  );
}

function renderHarness(route: string, props: HarnessProps = {}) {
  return renderWithProviders(<Harness {...props} />, { route });
}

const location = () => screen.getByTestId('location-probe').textContent;
const navType = () => screen.getByTestId('nav-type').textContent;
const liveRegion = () => screen.getByRole('status');

beforeEach(() => {
  mockGet.mockReset();
});

describe('usePageParam', () => {
  it.each(['0', '-2', '1.5', 'abc', '1'])(
    'replaces a malformed ?page=%s with page 1 and drops the param before any fetch',
    async (raw) => {
      serve(25);
      renderHarness(`/list?q=a&page=${raw}`);

      await waitFor(() => expect(location()).toBe('/list?q=a'));
      expect(navType()).toBe('REPLACE');
      await waitFor(() => expect(screen.getByText('Row 1')).toBeInTheDocument());
      expect(mockGet.mock.calls.map(([url]) => requestedOffset(url))).toEqual([0]);
    },
  );

  it('setListParams drops page and lands as one push', async () => {
    serve(25);
    renderHarness('/list?q=a&page=3');
    await waitFor(() => expect(screen.getByText('Row 21')).toBeInTheDocument());

    await userEvent.click(screen.getByRole('button', { name: 'Search jazz' }));
    expect(location()).toBe('/list?q=jazz');
    expect(navType()).toBe('PUSH');

    await userEvent.click(screen.getByRole('button', { name: 'Back' }));
    expect(location()).toBe('/list?q=a&page=3');
  });

  it('setListParams omits params left at their default', async () => {
    serve(25);
    renderHarness('/list?sort=date&page=2');
    await waitFor(() => expect(screen.getByText('Row 11')).toBeInTheDocument());

    await userEvent.click(screen.getByRole('button', { name: 'Default sort' }));
    expect(location()).toBe('/list');
  });

  it('setListParams is a no-op when nothing but the page would change', async () => {
    serve(25);
    renderHarness('/list?q=jazz&page=3');
    await waitFor(() => expect(screen.getByText('Row 21')).toBeInTheDocument());

    await userEvent.click(screen.getByRole('button', { name: 'Search jazz' }));
    await userEvent.click(screen.getByRole('button', { name: 'Default sort' }));

    expect(location()).toBe('/list?q=jazz&page=3');
    expect(navType()).toBe('POP');
    expect(screen.getByText('Row 21')).toBeInTheDocument();
  });
});

describe('usePagedQuery', () => {
  it('requests the page offset at the page size', async () => {
    serve(25);
    renderHarness('/list?page=2');
    await waitFor(() => expect(screen.getByText('Row 11')).toBeInTheDocument());
    expect(mockGet).toHaveBeenCalledWith('/list?limit=10&offset=10&q=');
  });

  it('replaces a past-end page with the last page', async () => {
    serve(25);
    renderHarness('/list?page=7');

    await waitFor(() => expect(location()).toBe('/list?page=3'));
    expect(navType()).toBe('REPLACE');
    await waitFor(() => expect(screen.getByText('Row 21')).toBeInTheDocument());
  });

  it('stays on page 1 when the list is empty', async () => {
    serve(0);
    renderHarness('/list');
    await waitFor(() => expect(mockGet).toHaveBeenCalledTimes(1));
    await act(async () => {});
    expect(location()).toBe('/list');
    expect(navType()).toBe('POP');
  });

  it('clamps to the new last page when a refetch empties the current one', async () => {
    serve(25);
    renderHarness('/list?page=3');
    await waitFor(() => expect(screen.getByText('Row 21')).toBeInTheDocument());

    serve(20);
    await userEvent.click(screen.getByRole('button', { name: 'Refetch' }));

    await waitFor(() => expect(location()).toBe('/list?page=2'));
    expect(navType()).toBe('REPLACE');
    await waitFor(() => expect(screen.getByText('Row 11')).toBeInTheDocument());
  });

  it('holdEmptyPage keeps an emptied page and renders it past the last page', async () => {
    serve(25);
    renderHarness('/list?page=3', { holdEmptyPage: true });
    await waitFor(() => expect(screen.getByText('Row 21')).toBeInTheDocument());

    serve(20);
    await userEvent.click(screen.getByRole('button', { name: 'Refetch' }));

    await waitFor(() =>
      expect(screen.getByText('No items on this page · 20 total')).toBeInTheDocument(),
    );
    expect(location()).toBe('/list?page=3');
    const nav = screen.getByRole('navigation', { name: 'Pages' });
    expect(within(nav).getByRole('link', { name: 'Page 1' })).toHaveAttribute('href', '/list');
    expect(within(nav).getByRole('link', { name: 'Page 2' })).toHaveAttribute('href', '/list?page=2');
    expect(within(nav).getByRole('link', { name: 'Page 3' })).toHaveAttribute('aria-current', 'page');
    expect(within(nav).queryByRole('link', { name: 'Next page' })).not.toBeInTheDocument();
  });

  it('replaces to the matching page when the server places a different offset', async () => {
    mockGet.mockImplementation(async (url: string) => {
      const offset = requestedOffset(url);
      // A server-side locate: the page-less request comes back at offset 20.
      const placed = offset === 0 ? 20 : offset;
      return { rows: [{ id: placed + 1 }], total: 25, limit: PAGE_SIZE, offset: placed } as never;
    });
    const onPageSettled = vi.fn();
    renderHarness('/list?q=a', { onPageSettled });

    await waitFor(() => expect(location()).toBe('/list?q=a&page=3'));
    expect(navType()).toBe('REPLACE');
    await waitFor(() => expect(screen.getByText('Row 21')).toBeInTheDocument());
    expect(onPageSettled).not.toHaveBeenCalled();
    expect(liveRegion()).toHaveTextContent('');
  });

  it('runs onPageSettled after a pager click once the new page has rendered', async () => {
    serve(25);
    const sawNewRows: boolean[] = [];
    const onPageSettled = vi.fn(() => {
      sawNewRows.push(screen.queryByText('Row 11') !== null);
    });
    renderHarness('/list', { onPageSettled });
    await waitFor(() => expect(screen.getByText('Row 1')).toBeInTheDocument());
    expect(onPageSettled).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole('link', { name: 'Page 2' }));

    await waitFor(() => expect(onPageSettled).toHaveBeenCalledTimes(1));
    expect(sawNewRows).toEqual([true]);
    expect(location()).toBe('/list?page=2');
    expect(liveRegion()).toHaveTextContent('Page 2 of 3. Events 11 to 20 of 25.');
  });

  it('runs onPageSettled on back/forward (POP) navigation too', async () => {
    serve(25);
    const onPageSettled = vi.fn();
    renderHarness('/list', { onPageSettled });
    await waitFor(() => expect(screen.getByText('Row 1')).toBeInTheDocument());
    await userEvent.click(screen.getByRole('link', { name: 'Next page' }));
    await waitFor(() => expect(onPageSettled).toHaveBeenCalledTimes(1));

    await userEvent.click(screen.getByRole('button', { name: 'Back' }));

    await waitFor(() => expect(onPageSettled).toHaveBeenCalledTimes(2));
    expect(location()).toBe('/list');
    expect(liveRegion()).toHaveTextContent('Page 1 of 3. Events 1 to 10 of 25.');
  });

  it('never runs onPageSettled on first mount, a silent replace or a filter change', async () => {
    serve(25);
    const onPageSettled = vi.fn();
    renderHarness('/list?page=9', { onPageSettled });
    await waitFor(() => expect(location()).toBe('/list?page=3'));
    await waitFor(() => expect(screen.getByText('Row 21')).toBeInTheDocument());

    await userEvent.click(screen.getByRole('button', { name: 'Search jazz' }));
    await waitFor(() => expect(screen.getByText('Row 1')).toBeInTheDocument());
    await act(async () => {});

    expect(onPageSettled).not.toHaveBeenCalled();
    expect(liveRegion()).toHaveTextContent('');
  });

  it('keeps a filter change silent when it lands before a pending page change loaded', async () => {
    serve(25);
    const onPageSettled = vi.fn();
    renderHarness('/list?page=2', { onPageSettled });
    await waitFor(() => expect(screen.getByText('Row 11')).toBeInTheDocument());
    const held: Array<() => void> = [];
    const served = mockGet.getMockImplementation()!;
    mockGet.mockImplementation((url: string) => new Promise((resolve) => held.push(() => resolve(served(url)))));

    await userEvent.click(screen.getByRole('link', { name: 'Page 1' }));
    await userEvent.click(screen.getByRole('button', { name: 'Search jazz' }));
    expect(location()).toBe('/list?q=jazz');
    await act(async () => {
      for (const release of held) release();
    });

    await waitFor(() => expect(screen.getByText('Row 1')).toBeInTheDocument());
    await act(async () => {});
    expect(onPageSettled).not.toHaveBeenCalled();
    expect(liveRegion()).toHaveTextContent('');
  });

  it('settles on the clamp target when a pager click lands on a page that has since emptied', async () => {
    serve(35);
    const onPageSettled = vi.fn();
    renderHarness('/list?page=3', { onPageSettled });
    await waitFor(() => expect(screen.getByText('Row 21')).toBeInTheDocument());
    serve(25);

    await userEvent.click(screen.getByRole('link', { name: 'Page 4' }));

    await waitFor(() => expect(location()).toBe('/list?page=3'));
    await waitFor(() => expect(onPageSettled).toHaveBeenCalledTimes(1));
    expect(liveRegion()).toHaveTextContent(/^Page 3 of \d\./);
  });

  it('treats an ordinary app link to page 1 as silent, not a page change', async () => {
    serve(25);
    const onPageSettled = vi.fn();
    renderHarness('/list', { onPageSettled });
    await waitFor(() => expect(screen.getByText('Row 1')).toBeInTheDocument());
    await userEvent.click(screen.getByRole('link', { name: 'Page 3' }));
    await waitFor(() => expect(onPageSettled).toHaveBeenCalledTimes(1));

    await userEvent.click(screen.getByRole('link', { name: 'List home' }));

    await waitFor(() => expect(screen.getByText('Row 1')).toBeInTheDocument());
    await act(async () => {});
    expect(location()).toBe('/list');
    expect(onPageSettled).toHaveBeenCalledTimes(1);
    expect(liveRegion()).toHaveTextContent('');
  });

  it('replaces a stale page past an empty list with page 1, silently', async () => {
    serve(0);
    renderHarness('/list?page=5');

    await waitFor(() => expect(location()).toBe('/list'));
    expect(navType()).toBe('REPLACE');
    expect(liveRegion()).toHaveTextContent('');
  });

  it('holdEmptyPage keeps a stale page on an empty list', async () => {
    serve(0);
    renderHarness('/list?page=5', { holdEmptyPage: true });
    await waitFor(() => expect(mockGet).toHaveBeenCalledTimes(1));
    await act(async () => {});
    expect(location()).toBe('/list?page=5');
  });

  it('clears the announcement on a filter push that stays on the same page', async () => {
    serve(25);
    renderHarness('/list');
    await waitFor(() => expect(screen.getByText('Row 1')).toBeInTheDocument());
    await userEvent.click(screen.getByRole('link', { name: 'Page 2' }));
    await waitFor(() => expect(liveRegion()).toHaveTextContent('Page 2 of 3.'));
    await userEvent.click(screen.getByRole('link', { name: 'Page 1' }));
    await waitFor(() => expect(liveRegion()).toHaveTextContent('Page 1 of 3.'));

    await userEvent.click(screen.getByRole('button', { name: 'Search jazz' }));
    await waitFor(() => expect(location()).toBe('/list?q=jazz'));
    await act(async () => {});
    expect(liveRegion()).toHaveTextContent('');
  });

  it('clears the announcement on a later silent page change', async () => {
    serve(25);
    renderHarness('/list');
    await waitFor(() => expect(screen.getByText('Row 1')).toBeInTheDocument());
    await userEvent.click(screen.getByRole('link', { name: 'Page 3' }));
    await waitFor(() => expect(liveRegion()).toHaveTextContent('Page 3 of 3.'));

    serve(15);
    await userEvent.click(screen.getByRole('button', { name: 'Refetch' }));

    await waitFor(() => expect(location()).toBe('/list?page=2'));
    expect(liveRegion()).toHaveTextContent('');
  });

  it('announces the lower-bound total as "more than"', async () => {
    mockGet.mockImplementation(async (url: string) => {
      const offset = requestedOffset(url);
      const rows = Array.from({ length: PAGE_SIZE }, (_, i) => ({ id: offset + i + 1 }));
      return { rows, total: 2000, limit: PAGE_SIZE, offset, total_is_lower_bound: true } as never;
    });
    renderHarness('/list');
    await waitFor(() => expect(screen.getByText('Row 1')).toBeInTheDocument());
    expect(document.querySelector('p')?.textContent).toBe('1–10 of 2,000+');

    await userEvent.click(screen.getByRole('link', { name: 'Next page' }));

    await waitFor(() =>
      expect(liveRegion()).toHaveTextContent('Page 2 of 200. Events 11 to 20 of more than 2,000.'),
    );
  });

  it('never announces the no-items form, even on a POP back to a held empty page', async () => {
    serve(25);
    const onPageSettled = vi.fn();
    renderHarness('/list?page=3', { holdEmptyPage: true, onPageSettled });
    await waitFor(() => expect(screen.getByText('Row 21')).toBeInTheDocument());
    await userEvent.click(screen.getByRole('link', { name: 'Page 1' }));
    await waitFor(() => expect(onPageSettled).toHaveBeenCalledTimes(1));

    serve(20);
    await userEvent.click(screen.getByRole('button', { name: 'Back' }));

    await waitFor(() => expect(onPageSettled).toHaveBeenCalledTimes(2));
    expect(location()).toBe('/list?page=3');
    expect(screen.getByText('No items on this page · 20 total')).toBeInTheDocument();
    expect(liveRegion()).toHaveTextContent('');
  });

  describe('the backend offset ceiling (PAGINATION_MAX_OFFSET = 5,000)', () => {
    // At 10 per page the deepest page whose offset the backend accepts is
    // page 501 (offset 5,000), so 5,010 rows are reachable.

    it('caps the last page at the deepest reachable one and labels the total as a lower bound', async () => {
      serve(6000);
      renderHarness('/list');
      await waitFor(() => expect(screen.getByText('Row 1')).toBeInTheDocument());

      expect(document.querySelector('p')?.textContent).toBe('1–10 of 5,010+');
      const nav = screen.getByRole('navigation', { name: 'Pages' });
      expect(within(nav).getByRole('link', { name: 'Page 501' })).toHaveAttribute('href', '/list?page=501');
      expect(within(nav).queryByRole('link', { name: 'Page 600' })).not.toBeInTheDocument();
    });

    it('announces the capped total as "more than" the reachable count', async () => {
      serve(6000);
      renderHarness('/list');
      await waitFor(() => expect(screen.getByText('Row 1')).toBeInTheDocument());

      await userEvent.click(screen.getByRole('link', { name: 'Next page' }));

      await waitFor(() =>
        expect(liveRegion()).toHaveTextContent('Page 2 of 501. Events 11 to 20 of more than 5,010.'),
      );
    });

    it('has no next link on the capped last page', async () => {
      serve(6000);
      renderHarness('/list?page=501');
      await waitFor(() => expect(screen.getByText('Row 5001')).toBeInTheDocument());

      expect(document.querySelector('p')?.textContent).toBe('5,001–5,010 of 5,010+');
      expect(screen.queryByRole('link', { name: 'Next page' })).not.toBeInTheDocument();
    });

    it('silently clamps a stale deeper link to the capped last page without requesting past the ceiling', async () => {
      serve(6000);
      const onPageSettled = vi.fn();
      renderHarness('/list?page=600', { onPageSettled });

      await waitFor(() => expect(location()).toBe('/list?page=501'));
      expect(navType()).toBe('REPLACE');
      await waitFor(() => expect(screen.getByText('Row 5001')).toBeInTheDocument());
      expect(mockGet.mock.calls.map(([url]) => requestedOffset(url))).toEqual([5000]);
      expect(onPageSettled).not.toHaveBeenCalled();
    });

    it('keeps the exact total when every row is reachable', async () => {
      serve(5005);
      renderHarness('/list?page=501');
      await waitFor(() => expect(screen.getByText('Row 5001')).toBeInTheDocument());
      expect(document.querySelector('p')?.textContent).toBe('5,001–5,005 of 5,005');
    });
  });

  it('shows no previous rows once the query is disabled after loading', async () => {
    serve(25);
    renderHarness('/list');
    await waitFor(() => expect(screen.getByText('Row 1')).toBeInTheDocument());

    await userEvent.click(screen.getByRole('button', { name: 'Disable' }));

    await waitFor(() => expect(location()).toBe('/list?off=1'));
    expect(screen.queryByText('Row 1')).not.toBeInTheDocument();
    expect(screen.getByTestId('paged-state')).toHaveTextContent('settled total=0');
  });

  it('does not prefetch the next page', async () => {
    serve(25);
    renderHarness('/list');
    await waitFor(() => expect(screen.getByText('Row 1')).toBeInTheDocument());
    await act(async () => {});
    expect(mockGet.mock.calls.map(([url]) => requestedOffset(url))).toEqual([0]);
  });
});

describe('Pager', () => {
  const base = { page: 1, lastPage: 1, offset: 0, itemCount: 0, total: 0, locale: 'en' };

  function renderPager(props: Partial<PagerProps>, route = '/list') {
    return renderWithProviders(<Pager {...base} {...props} />, { route });
  }

  const rangeText = (container: HTMLElement) => container.querySelector('p')?.textContent;
  // Link text as assistive tech reads it: the aria-hidden ‹/› glyphs drop out.
  const linkNames = () =>
    screen.getAllByRole('link').map((a) =>
      Array.from(a.childNodes)
        .filter((node) => !(node instanceof Element && node.getAttribute('aria-hidden') === 'true'))
        .map((node) => node.textContent)
        .join(''),
    );

  it('labels the range from offset, item count and total', () => {
    const { container } = renderPager({ page: 2, lastPage: 9, offset: 50, itemCount: 50, total: 430 });
    expect(rangeText(container)).toBe('51–100 of 430');
  });

  it('labels a lower-bound total with "+" after the formatted number', () => {
    const { container } = renderPager({
      page: 1,
      lastPage: 84,
      offset: 0,
      itemCount: 24,
      total: 2000,
      totalIsLowerBound: true,
    });
    expect(rangeText(container)).toBe('1–24 of 2,000+');
  });

  it('labels an empty held page as "No items on this page"', () => {
    const { container } = renderPager({ page: 9, lastPage: 8, offset: 400, itemCount: 0, total: 400 });
    expect(rangeText(container)).toBe('No items on this page · 400 total');
  });

  it('formats numbers and strings in the active locale', () => {
    const { container } = renderPager({
      page: 2,
      lastPage: 200,
      offset: 1000,
      itemCount: 10,
      total: 2000,
      locale: 'ru',
    });
    expect(screen.getByRole('navigation', { name: 'Страницы' })).toBeInTheDocument();
    expect(rangeText(container)?.replace(/\s/g, ' ')).toBe('1 001–1 010 из 2 000');
  });

  it('hides the page buttons but keeps the label when everything fits on one page', () => {
    const { container } = renderPager({ lastPage: 1, itemCount: 5, total: 5 });
    expect(rangeText(container)).toBe('1–5 of 5');
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
  });

  it('hides the whole bar at total 0 but keeps the live region mounted', () => {
    const { container } = renderPager({});
    expect(container.querySelector('p')).toBeNull();
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveAttribute('aria-live', 'polite');
  });

  it('renders 1 … p-1 p p+1 … last with hidden gaps and the current page marked', () => {
    renderPager({ page: 5, lastPage: 9, offset: 40, itemCount: 10, total: 90 }, '/list?page=5');
    expect(linkNames()).toEqual([
      'Previous page',
      'Page 1',
      'Page 4',
      'Page 5',
      'Page 6',
      'Page 9',
      'Next page',
    ]);
    expect(screen.getByRole('link', { name: 'Page 5' })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByRole('link', { name: 'Page 4' })).not.toHaveAttribute('aria-current');
    // Every gap (including the collapsed-form-only one before p) is aria-hidden.
    const gaps = Array.from(document.querySelectorAll('li')).filter((li) => li.textContent === '…');
    expect(gaps.length).toBeGreaterThanOrEqual(2);
    for (const gap of gaps) expect(gap).toHaveAttribute('aria-hidden', 'true');
  });

  it('renders dead ‹ and › at the ends as aria-hidden spans, not links', () => {
    const { container, unmount } = renderPager({ page: 1, lastPage: 3, itemCount: 10, total: 25 });
    expect(screen.queryByRole('link', { name: 'Previous page' })).not.toBeInTheDocument();
    const firstEnd = container.querySelector('ol > li:first-child > span');
    expect(firstEnd).toHaveAttribute('aria-hidden', 'true');
    expect(firstEnd).toHaveTextContent('‹');
    unmount();

    const last = renderPager({ page: 3, lastPage: 3, offset: 20, itemCount: 5, total: 25 }, '/list?page=3');
    expect(screen.queryByRole('link', { name: 'Next page' })).not.toBeInTheDocument();
    const lastEnd = last.container.querySelector('ol > li:last-child > span');
    expect(lastEnd).toHaveAttribute('aria-hidden', 'true');
    expect(lastEnd).toHaveTextContent('›');
  });

  it('keeps current params in every href, omits page 1 and drops dropOnPageChange names', () => {
    renderPager(
      { page: 2, lastPage: 3, offset: 10, itemCount: 10, total: 25, dropOnPageChange: ['report'] },
      '/admin/reports?report=7&reason=spam&page=2',
    );
    expect(screen.getByRole('link', { name: 'Page 1' })).toHaveAttribute('href', '/admin/reports?reason=spam');
    expect(screen.getByRole('link', { name: 'Page 3' })).toHaveAttribute(
      'href',
      '/admin/reports?reason=spam&page=3',
    );
    expect(screen.getByRole('link', { name: 'Previous page' })).toHaveAttribute(
      'href',
      '/admin/reports?reason=spam',
    );
  });

  it('announces with the items noun when asked', () => {
    renderPager({
      page: 2,
      lastPage: 3,
      offset: 50,
      itemCount: 50,
      total: 130,
      liveNoun: 'items',
      announcement: { page: 2, lastPage: 3, from: 51, to: 100, total: 130, totalIsLowerBound: false },
    });
    expect(screen.getByRole('status')).toHaveTextContent('Page 2 of 3. Items 51 to 100 of 130.');
  });
});
