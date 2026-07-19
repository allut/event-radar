import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import PageState from './PageState';

describe('PageState', () => {
  it('shows spinner with aria-label when loading', () => {
    render(<PageState kind="loading" message="Loading…" />);
    expect(screen.getByLabelText('Loading…')).toBeInTheDocument();
    expect(screen.queryByText('Loading…')).not.toBeInTheDocument();
  });

  it('shows error message when kind is error', () => {
    render(<PageState kind="error" message="Something broke" />);
    expect(screen.getByText('Something broke')).toBeInTheDocument();
  });

  it('renders action when provided', () => {
    render(<PageState kind="error" message="Oops" action={<button>Retry</button>} />);
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  });

  it('does not render action when not provided', () => {
    render(<PageState kind="error" message="Oops" />);
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });

  it('renders spinner via aria-label when inline', () => {
    render(<PageState kind="loading" message="Loading…" inline />);
    expect(screen.getByLabelText('Loading…')).toBeInTheDocument();
  });
});
