import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import PersonaCard from './PersonaCard';
import { type PersonaData } from '../../constants';

const persona: PersonaData = {
  slug: 'culture_buff',
  emoji: '🎭',
  name: 'Culture Buff',
  vibe: 'Museums and theatre',
};

describe('PersonaCard', () => {
  it('renders persona name and emoji', () => {
    render(
      <PersonaCard
        persona={persona}
        rank={0}
        disabled={false}
        locale="en"
        onToggle={vi.fn()}
      />,
    );
    expect(screen.getByText('Culture Buff')).toBeInTheDocument();
    expect(screen.getByText('🎭')).toBeInTheDocument();
  });

  it('selected: main button has aria-pressed=true and shows rank badge', () => {
    render(
      <PersonaCard
        persona={persona}
        rank={1}
        disabled={false}
        locale="en"
        onToggle={vi.fn()}
      />,
    );
    expect(screen.getByRole('button')).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByText('1')).toBeInTheDocument();
  });

  it('unselected: main button has aria-pressed=false and no badge', () => {
    render(
      <PersonaCard
        persona={persona}
        rank={0}
        disabled={false}
        locale="en"
        onToggle={vi.fn()}
      />,
    );
    expect(screen.getByRole('button')).toHaveAttribute('aria-pressed', 'false');
    expect(screen.queryByText('1')).not.toBeInTheDocument();
  });

  it('disabled at cap: button is disabled', () => {
    render(
      <PersonaCard
        persona={persona}
        rank={0}
        disabled={true}
        locale="en"
        onToggle={vi.fn()}
      />,
    );
    expect(screen.getByRole('button')).toBeDisabled();
  });

  it('calls onToggle on click', async () => {
    const onToggle = vi.fn();
    render(
      <PersonaCard
        persona={persona}
        rank={0}
        disabled={false}
        locale="en"
        onToggle={onToggle}
      />,
    );
    await userEvent.click(screen.getByRole('button'));
    expect(onToggle).toHaveBeenCalled();
  });
});
