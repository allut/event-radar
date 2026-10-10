import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useDropdown } from './useDropdown';

function Harness() {
  const { open, setOpen, rootRef, popRef, triggerRef } = useDropdown();
  return (
    <div>
      <div ref={rootRef}>
        <button ref={triggerRef} onClick={() => setOpen((o) => !o)}>Trigger</button>
        {open && (
          <div ref={popRef}>
            <button>Inside option</button>
          </div>
        )}
      </div>
      <button>Outside</button>
    </div>
  );
}

describe('useDropdown', () => {
  it('starts closed', () => {
    render(<Harness />);
    expect(screen.queryByText('Inside option')).not.toBeInTheDocument();
  });

  it('opens when the trigger is clicked', async () => {
    render(<Harness />);
    await userEvent.click(screen.getByText('Trigger'));
    expect(screen.getByText('Inside option')).toBeInTheDocument();
  });

  it('closes on Escape and refocuses the trigger', async () => {
    render(<Harness />);
    const trigger = screen.getByText('Trigger');
    await userEvent.click(trigger);
    expect(screen.getByText('Inside option')).toBeInTheDocument();

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByText('Inside option')).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it('closes when clicking outside the root', async () => {
    render(<Harness />);
    await userEvent.click(screen.getByText('Trigger'));
    expect(screen.getByText('Inside option')).toBeInTheDocument();

    fireEvent.mouseDown(screen.getByText('Outside'));
    expect(screen.queryByText('Inside option')).not.toBeInTheDocument();
  });

  it('does not close when clicking inside the popover', () => {
    render(<Harness />);
    fireEvent.click(screen.getByText('Trigger'));
    fireEvent.mouseDown(screen.getByText('Inside option'));
    expect(screen.getByText('Inside option')).toBeInTheDocument();
  });
});

function MobileHarness() {
  const { open, setOpen, rootRef, popRef, triggerRef } = useDropdown(undefined, '--pop-top');
  return (
    <div ref={rootRef}>
      <button ref={triggerRef} onClick={() => setOpen((o) => !o)}>Trigger</button>
      {open && (
        <div ref={popRef} data-testid="pop">
          <button>Inside option</button>
        </div>
      )}
    </div>
  );
}

describe('useDropdown — mobile top sync', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('coalesces a burst of scroll events into one position sync per frame', () => {
    vi.spyOn(window, 'matchMedia').mockImplementation(
      (query: string) => ({ matches: true, media: query }) as MediaQueryList,
    );
    const frames: FrameRequestCallback[] = [];
    vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => frames.push(cb));
    vi.stubGlobal('cancelAnimationFrame', () => {});

    render(<MobileHarness />);
    fireEvent.click(screen.getByText('Trigger'));
    const pop = screen.getByTestId('pop');
    const setProperty = vi.spyOn(pop.style, 'setProperty');
    setProperty.mockClear();

    for (let i = 0; i < 5; i++) fireEvent.scroll(window);
    expect(frames).toHaveLength(1); // five scrolls, one scheduled frame
    expect(setProperty).not.toHaveBeenCalled(); // no layout read until the frame

    frames[0](0);
    expect(setProperty).toHaveBeenCalledTimes(1);
  });
});
