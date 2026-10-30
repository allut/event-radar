import { describe, it, expect, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ReportModal from './ReportModal';
import { renderWithProviders } from '../../test/utils';

vi.mock('../../api/client', () => ({
  api: { post: vi.fn() },
  ApiError: class ApiError extends Error {
    constructor(public status: number, message: string) {
      super(message);
    }
  },
}));

import { api } from '../../api/client';
const mockPost = vi.mocked(api.post);

describe('ReportModal', () => {
  it('offers the report reasons in their fixed order, "Other" last', () => {
    renderWithProviders(
      <ReportModal open onClose={vi.fn()} eventId={1} locale="en" onSubmitted={vi.fn()} />,
    );
    expect(screen.getAllByRole('radio').map(r => (r as HTMLInputElement).value)).toEqual([
      'spam_or_scam',
      'sexual_or_explicit',
      'not_an_event',
      'hateful_or_violent',
      'misleading_info',
      'event_ended_or_cancelled',
      'wrong_location',
      'other',
    ]);
  });

  it('requires a reason before submitting', async () => {
    const onSubmitted = vi.fn();
    renderWithProviders(
      <ReportModal open onClose={vi.fn()} eventId={1} locale="en" onSubmitted={onSubmitted} />,
    );
    await userEvent.click(screen.getByRole('button', { name: 'Submit report' }));
    expect(screen.getByText('Please choose a reason.')).toBeInTheDocument();
    expect(mockPost).not.toHaveBeenCalled();
  });

  it('requires detail when reason is "other"', async () => {
    renderWithProviders(
      <ReportModal open onClose={vi.fn()} eventId={1} locale="en" onSubmitted={vi.fn()} />,
    );
    await userEvent.click(screen.getByRole('radio', { name: /Other/ }));
    await userEvent.click(screen.getByRole('button', { name: 'Submit report' }));
    expect(screen.getByText('Please add details for this report.')).toBeInTheDocument();
    expect(mockPost).not.toHaveBeenCalled();
  });

  it('requires detail when the illegal-content checkbox is checked', async () => {
    renderWithProviders(
      <ReportModal open onClose={vi.fn()} eventId={1} locale="en" onSubmitted={vi.fn()} />,
    );
    await userEvent.click(screen.getByRole('radio', { name: /Spam or scam/ }));
    await userEvent.click(screen.getByRole('checkbox'));
    await userEvent.click(screen.getByRole('button', { name: 'Submit report' }));
    expect(screen.getByText('Please add details for this report.')).toBeInTheDocument();
    expect(mockPost).not.toHaveBeenCalled();
  });

  it('submits and shows the confirmation on success', async () => {
    mockPost.mockResolvedValueOnce({ ok: true });
    const onSubmitted = vi.fn();
    renderWithProviders(
      <ReportModal open onClose={vi.fn()} eventId={7} locale="en" onSubmitted={onSubmitted} />,
    );
    await userEvent.click(screen.getByRole('radio', { name: /Spam or scam/ }));
    await userEvent.click(screen.getByRole('button', { name: 'Submit report' }));
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/reports', {
      event_id: 7,
      reason: 'spam_or_scam',
      is_illegal_allegation: false,
      detail: undefined,
    }));
    expect(onSubmitted).toHaveBeenCalled();
    expect(await screen.findByText("Report received. We'll review it and follow up by email.")).toBeInTheDocument();
  });

  it('closes without submitting on cancel', async () => {
    const onClose = vi.fn();
    renderWithProviders(
      <ReportModal open onClose={onClose} eventId={1} locale="en" onSubmitted={vi.fn()} />,
    );
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(onClose).toHaveBeenCalled();
    expect(mockPost).not.toHaveBeenCalled();
  });
});
