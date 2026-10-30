import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { usePageSettledFocus } from './usePageSettledFocus';

function List() {
  const { resultsHeadingRef, onPageSettled } = usePageSettledFocus();
  return (
    <>
      <h2 ref={resultsHeadingRef} tabIndex={-1} style={{ scrollMarginTop: '88px' }}>
        Results
      </h2>
      <button type="button" onClick={onPageSettled}>
        Settle
      </button>
    </>
  );
}

afterEach(() => {
  Object.defineProperty(window, 'scrollY', { value: 0, configurable: true });
  vi.restoreAllMocks();
});

describe('usePageSettledFocus', () => {
  it('instant-scrolls the results heading to just below its scroll-margin-top, then focuses it without scrolling', async () => {
    render(<List />);
    const heading = screen.getByRole('heading', { name: 'Results' });
    Object.defineProperty(window, 'scrollY', { value: 1200, configurable: true });
    vi.spyOn(heading, 'getBoundingClientRect').mockReturnValue({ top: -300 } as DOMRect);
    const focus = vi.spyOn(heading, 'focus');

    await userEvent.click(screen.getByRole('button', { name: 'Settle' }));

    // Document top of the heading is 1200 - 300 = 900; minus the 88px margin.
    expect(window.scrollTo).toHaveBeenCalledWith({ top: 812, behavior: 'instant' });
    expect(focus).toHaveBeenCalledWith({ preventScroll: true });
    expect(document.activeElement).toBe(heading);
  });

  it('never scrolls above the top of the page', async () => {
    render(<List />);
    const heading = screen.getByRole('heading', { name: 'Results' });
    vi.spyOn(heading, 'getBoundingClientRect').mockReturnValue({ top: 40 } as DOMRect);

    await userEvent.click(screen.getByRole('button', { name: 'Settle' }));

    expect(window.scrollTo).toHaveBeenCalledWith({ top: 0, behavior: 'instant' });
    expect(document.activeElement).toBe(heading);
  });
});
