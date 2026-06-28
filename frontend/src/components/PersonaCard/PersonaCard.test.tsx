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
        role="none"
        isPrimaryTaken={false}
        locale="en"
        onClickPrimary={vi.fn()}
        onClickSecondary={vi.fn()}
      />,
    );
    expect(screen.getByText('Culture Buff')).toBeInTheDocument();
    expect(screen.getByText('🎭')).toBeInTheDocument();
  });

  it('primary role: main button has aria-pressed=true', () => {
    render(
      <PersonaCard
        persona={persona}
        role="primary"
        isPrimaryTaken={true}
        locale="en"
        onClickPrimary={vi.fn()}
        onClickSecondary={vi.fn()}
      />,
    );
    expect(screen.getAllByRole('button')[0]).toHaveAttribute('aria-pressed', 'true');
  });

  it('none role: main button has aria-pressed=false', () => {
    render(
      <PersonaCard
        persona={persona}
        role="none"
        isPrimaryTaken={false}
        locale="en"
        onClickPrimary={vi.fn()}
        onClickSecondary={vi.fn()}
      />,
    );
    const mainBtn = screen.getAllByRole('button')[0];
    expect(mainBtn).toHaveAttribute('aria-pressed', 'false');
  });

  it('shows add secondary button when isPrimaryTaken and role is none', () => {
    render(
      <PersonaCard
        persona={persona}
        role="none"
        isPrimaryTaken={true}
        locale="en"
        onClickPrimary={vi.fn()}
        onClickSecondary={vi.fn()}
      />,
    );
    expect(screen.getAllByRole('button').length).toBe(2);
  });

  it('does not show add secondary button when isPrimaryTaken is false', () => {
    render(
      <PersonaCard
        persona={persona}
        role="none"
        isPrimaryTaken={false}
        locale="en"
        onClickPrimary={vi.fn()}
        onClickSecondary={vi.fn()}
      />,
    );
    expect(screen.getAllByRole('button').length).toBe(1);
  });

  it('calls onClickPrimary on main button click', async () => {
    const onClickPrimary = vi.fn();
    render(
      <PersonaCard
        persona={persona}
        role="none"
        isPrimaryTaken={false}
        locale="en"
        onClickPrimary={onClickPrimary}
        onClickSecondary={vi.fn()}
      />,
    );
    await userEvent.click(screen.getAllByRole('button')[0]);
    expect(onClickPrimary).toHaveBeenCalled();
  });

  it('calls onClickSecondary on secondary button click', async () => {
    const onClickSecondary = vi.fn();
    render(
      <PersonaCard
        persona={persona}
        role="none"
        isPrimaryTaken={true}
        locale="en"
        onClickPrimary={vi.fn()}
        onClickSecondary={onClickSecondary}
      />,
    );
    const btns = screen.getAllByRole('button');
    await userEvent.click(btns[1]);
    expect(onClickSecondary).toHaveBeenCalled();
  });
});
