import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import EmptyState from './EmptyState';

describe('EmptyState', () => {
  it('renders title and message', () => {
    render(<EmptyState title="Nothing here" message="Come back later" />);
    expect(screen.getByText('Nothing here')).toBeInTheDocument();
    expect(screen.getByText('Come back later')).toBeInTheDocument();
  });

  it('renders hint when provided', () => {
    render(<EmptyState title="T" message="M" hint="Helpful hint" />);
    expect(screen.getByText('Helpful hint')).toBeInTheDocument();
  });

  it('does not render hint when not provided', () => {
    render(<EmptyState title="T" message="M" />);
    expect(screen.queryByText('Helpful hint')).not.toBeInTheDocument();
  });

  it('renders eyebrow when provided', () => {
    render(<EmptyState title="T" message="M" eyebrow="Explore" />);
    expect(screen.getByText('Explore')).toBeInTheDocument();
  });

  it('does not render eyebrow when not provided', () => {
    render(<EmptyState title="T" message="M" />);
    expect(screen.queryByText('Explore')).not.toBeInTheDocument();
  });
});
