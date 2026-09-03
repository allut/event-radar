import { describe, it, expect, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import SignInModal from './SignInModal';
import { renderWithProviders } from '../../test/utils';

vi.mock('../../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/client')>()),
  api: { post: vi.fn(() => new Promise(() => undefined)) },
}));

vi.mock('../../lib/gtag', () => ({
  trackEvent: vi.fn(),
}));

import { trackEvent } from '../../lib/gtag';
const mockTrackEvent = vi.mocked(trackEvent);

describe('SignInModal', () => {
  it('renders nothing when trigger is null', () => {
    renderWithProviders(<SignInModal open={false} trigger={null} onClose={vi.fn()} locale="en" />);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('shows the save/thumbs copy variant with a static "Sign in" title for the save trigger', () => {
    renderWithProviders(<SignInModal open trigger="save" onClose={vi.fn()} locale="en" />);
    expect(screen.getByRole('dialog', { name: 'Sign in' })).toBeInTheDocument();
    expect(screen.getByText('Sign in to save this')).toBeInTheDocument();
    expect(screen.getByText(/We'll remember it's yours/)).toBeInTheDocument();
  });

  it('shows the same save/thumbs copy variant for the thumbs trigger', () => {
    renderWithProviders(<SignInModal open trigger="thumbs" onClose={vi.fn()} locale="en" />);
    expect(screen.getByText('Sign in to save this')).toBeInTheDocument();
  });

  it('shows the for_you copy variant for the for_you trigger', () => {
    renderWithProviders(<SignInModal open trigger="for_you" onClose={vi.fn()} locale="en" />);
    expect(screen.getByText('Sign in for your picks')).toBeInTheDocument();
    expect(screen.getByText(/For-you ranks events/)).toBeInTheDocument();
  });

  it('renders MagicLinkForm unchanged inside the modal', () => {
    renderWithProviders(<SignInModal open trigger="save" onClose={vi.fn()} locale="en" />);
    expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /send/i })).toBeInTheDocument();
  });

  it('tracks signin_modal_dismiss with the trigger on close without submitting', async () => {
    const onClose = vi.fn();
    renderWithProviders(<SignInModal open trigger="save" onClose={onClose} locale="en" />);
    await userEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(mockTrackEvent).toHaveBeenCalledWith('signin_modal_dismiss', { trigger: 'save' });
    expect(onClose).toHaveBeenCalled();
  });

  it('tracks signin_modal_submit on form submit, and does not track dismiss on a later close', async () => {
    const onClose = vi.fn();
    renderWithProviders(<SignInModal open trigger="for_you" onClose={onClose} locale="en" />);
    await userEvent.type(screen.getByLabelText(/email/i), 'jane@example.com');
    await userEvent.click(screen.getByRole('button', { name: /send/i }));

    expect(mockTrackEvent).toHaveBeenCalledWith('signin_modal_submit', { trigger: 'for_you' });

    mockTrackEvent.mockClear();
    await userEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(mockTrackEvent).not.toHaveBeenCalledWith('signin_modal_dismiss', expect.anything());
    expect(onClose).toHaveBeenCalled();
  });
});
