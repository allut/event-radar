import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import EmptyState from './EmptyState';

describe('EmptyState', () => {
  it('renders icon, title, and message', () => {
    render(<EmptyState icon="◉" title="Nothing here" message="Come back later" />);
    expect(screen.getByText('◉')).toBeInTheDocument();
    expect(screen.getByText('Nothing here')).toBeInTheDocument();
    expect(screen.getByText('Come back later')).toBeInTheDocument();
  });

  it('renders hint when provided', () => {
    render(<EmptyState icon="◉" title="T" message="M" hint="Helpful hint" />);
    expect(screen.getByText('Helpful hint')).toBeInTheDocument();
  });

  it('does not render hint when not provided', () => {
    render(<EmptyState icon="◉" title="T" message="M" />);
    expect(screen.queryByText('Helpful hint')).not.toBeInTheDocument();
  });
});
