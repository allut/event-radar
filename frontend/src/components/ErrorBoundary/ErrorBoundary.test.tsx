import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ErrorBoundary from './ErrorBoundary';

function BrokenChild(): never {
  throw new Error('Test error from child');
}

describe('ErrorBoundary', () => {
  beforeEach(() => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
  });

  it('renders children when no error', () => {
    render(
      <ErrorBoundary>
        <div>Safe content</div>
      </ErrorBoundary>,
    );
    expect(screen.getByText('Safe content')).toBeInTheDocument();
  });

  it('shows fallback UI when child throws', () => {
    render(
      <ErrorBoundary>
        <BrokenChild />
      </ErrorBoundary>,
    );
    expect(screen.getByRole('button')).toBeInTheDocument();
  });

  it('reload button calls window.location.reload', async () => {
    const reload = vi.fn();
    vi.stubGlobal('location', { ...window.location, reload });
    render(
      <ErrorBoundary>
        <BrokenChild />
      </ErrorBoundary>,
    );
    await userEvent.click(screen.getByRole('button'));
    expect(reload).toHaveBeenCalled();
    vi.unstubAllGlobals();
  });
});
