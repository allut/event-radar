import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import AuthCard from './AuthCard';

describe('AuthCard', () => {
  it('renders a spinner and status role for kind="pending"', () => {
    render(<AuthCard locale="en" kind="pending" message="Verifying your link…" />);
    const status = screen.getByRole('status');
    expect(status).toHaveAttribute('aria-live', 'polite');
    expect(screen.getByLabelText('Verifying your link…')).toBeInTheDocument();
    expect(screen.getByText('Verifying your link…')).toBeInTheDocument();
  });

  it('renders a check mark for kind="success"', () => {
    render(<AuthCard locale="en" kind="success" message="You're in!" />);
    expect(screen.getByRole('status')).toBeInTheDocument();
    expect(screen.getByText('✓')).toBeInTheDocument();
  });

  it('renders an alert role and cross mark for kind="error"', () => {
    render(<AuthCard locale="en" kind="error" message="Link expired" />);
    const alert = screen.getByRole('alert');
    expect(alert).not.toHaveAttribute('aria-live');
    expect(screen.getByText('✕')).toBeInTheDocument();
  });

  it('renders the brand name resolved for the given locale', () => {
    render(<AuthCard locale="et" kind="pending" message="…" />);
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(/./);
  });

  it('renders action content below the message when provided', () => {
    render(
      <AuthCard locale="en" kind="error" message="Link expired" action={<button>Resend</button>} />,
    );
    expect(screen.getByRole('button', { name: 'Resend' })).toBeInTheDocument();
  });

  it('does not render action content when omitted', () => {
    render(<AuthCard locale="en" kind="pending" message="…" />);
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });
});
