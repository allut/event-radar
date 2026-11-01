import { describe, it, expect, vi, beforeEach } from 'vitest';
import { trackExternalClick } from './eventActions';
import { api } from '../api/client';

vi.mock('../api/client', () => ({
  api: {
    post: vi.fn().mockResolvedValue(undefined),
  },
}));

describe('trackExternalClick', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('calls api.post with correct path and body', async () => {
    const mockPost = vi.mocked(api.post);
    trackExternalClick(42);
    expect(mockPost).toHaveBeenCalledWith('/feedback', { event_id: 42, signal: 'click_external' });
  });

  it('swallows API errors', async () => {
    vi.mocked(api.post).mockRejectedValueOnce(new Error('network error'));
    await expect(async () => {
      trackExternalClick(1);
      await new Promise((r) => setTimeout(r, 10));
    }).not.toThrow();
  });
});
