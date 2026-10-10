import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { QueryClient } from '@tanstack/react-query';
import { renderWithProviders } from '../../test/utils';
import PulseChip from './PulseChip';

vi.mock('../../api/client', () => ({ api: { get: vi.fn() } }));
import { api } from '../../api/client';

const mockGet = vi.mocked(api.get);
beforeEach(() => mockGet.mockReset());

describe('PulseChip', () => {
  it('renders the exact count (no cap) linking to /explore?date=today', async () => {
    mockGet.mockResolvedValue({ today_count: 57 });
    renderWithProviders(<PulseChip locale="en" />);

    const chip = await screen.findByRole('link');
    expect(chip).toHaveTextContent('57 on today');
    expect(chip).toHaveAttribute('href', '/explore?date=today');
  });

  it('keeps the slot but renders no chip at zero, and when the field is missing', async () => {
    mockGet.mockResolvedValue({ today_count: 0 });
    const { container } = renderWithProviders(<PulseChip locale="en" />);
    await waitFor(() => expect(mockGet).toHaveBeenCalled());

    expect(screen.queryByRole('link')).not.toBeInTheDocument();
    expect(container.firstElementChild).toBeInTheDocument(); // slot stays rendered
  });

  it('reuses the Landing [counts, locale] cache entry instead of refetching', async () => {
    const queryClient = new QueryClient();
    queryClient.setQueryData(['counts', 'et'], { today_count: 3 });
    renderWithProviders(<PulseChip locale="et" />, { queryClient });

    expect(await screen.findByRole('link', { name: 'täna 3' })).toBeInTheDocument();
  });
});
