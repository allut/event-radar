import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/utils';
import AccountMenu from './AccountMenu';

vi.mock('../../api/client', () => ({
  api: { get: vi.fn() },
  organizerApi: { get: vi.fn() },
}));
import { api, organizerApi } from '../../api/client';

const items = [{ route: '/settings', labelKey: 'nav_settings' }];

beforeEach(() => {
  vi.mocked(api.get).mockReset().mockResolvedValue({ email: 'ada@example.com' });
  vi.mocked(organizerApi.get).mockReset().mockResolvedValue({ email: 'org@example.com', name: 'Jazz Club' });
});

describe('AccountMenu', () => {
  it('declares the menu pattern and fetches nothing until opened', () => {
    renderWithProviders(<AccountMenu locale="en" track="consumer" items={items} onLogout={vi.fn()} />);

    const trigger = screen.getByRole('button', { name: 'Account' });
    expect(trigger).toHaveAttribute('aria-haspopup', 'menu');
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
    expect(api.get).not.toHaveBeenCalled();
  });

  it('focuses the first item on open; Escape closes and returns focus to the trigger', async () => {
    renderWithProviders(<AccountMenu locale="en" track="consumer" items={items} onLogout={vi.fn()} />);
    const trigger = screen.getByRole('button', { name: 'Account' });

    await userEvent.click(trigger);
    expect(screen.getByRole('menuitem', { name: 'Settings' })).toHaveFocus();

    await userEvent.keyboard('{Escape}');
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it('closes on an outside click', async () => {
    renderWithProviders(<AccountMenu locale="en" track="consumer" items={items} onLogout={vi.fn()} />);
    await userEvent.click(screen.getByRole('button', { name: 'Account' }));

    await userEvent.click(document.body);

    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
  });

  it('consumer identity is the email, fetched from /auth/me once (staleTime Infinity)', async () => {
    renderWithProviders(<AccountMenu locale="en" track="consumer" items={items} onLogout={vi.fn()} />);

    await userEvent.click(screen.getByRole('button', { name: 'Account' }));
    expect(await screen.findByText('ada@example.com')).toBeInTheDocument();
    expect(screen.getByText('Signed in as')).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith('/auth/me');
    expect(organizerApi.get).not.toHaveBeenCalled();
  });

  it('organizer identity is the name with the email on the next line', async () => {
    renderWithProviders(<AccountMenu locale="en" track="organizer" items={items} onLogout={vi.fn()} />);

    await userEvent.click(screen.getByRole('button', { name: 'Account' }));
    expect(await screen.findByText('Jazz Club')).toBeInTheDocument();
    expect(screen.getByText('org@example.com')).toBeInTheDocument();
    expect(organizerApi.get).toHaveBeenCalledWith('/organizer/profile');
    expect(api.get).not.toHaveBeenCalled();
  });
});
