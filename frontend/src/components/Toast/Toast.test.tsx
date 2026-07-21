import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import Toast from './Toast';

describe('Toast', () => {
  it('renders success with role=status', () => {
    render(<Toast status="success" message="Saved" />);
    const el = screen.getByRole('status');
    expect(el).toHaveTextContent('Saved');
  });

  it('renders error with role=alert', () => {
    render(<Toast status="error" message="Failed" />);
    const el = screen.getByRole('alert');
    expect(el).toHaveTextContent('Failed');
  });
});
