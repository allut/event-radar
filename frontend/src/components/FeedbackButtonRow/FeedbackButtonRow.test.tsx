import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import FeedbackButtonRow from './FeedbackButtonRow';
import { SIGNAL_CONFIG, type Signal } from '../../constants';

describe('FeedbackButtonRow', () => {
  const signals = Object.keys(SIGNAL_CONFIG) as Signal[];

  it('renders all signal buttons', () => {
    render(
      <FeedbackButtonRow activeSignal={null} pending={false} onPress={vi.fn()} locale="en" />,
    );
    expect(screen.getAllByRole('button').length).toBe(signals.length);
  });

  it('active signal has aria-pressed=true', () => {
    render(
      <FeedbackButtonRow activeSignal="like" pending={false} onPress={vi.fn()} locale="en" />,
    );
    const likeBtn = screen.getByRole('button', { name: 'Like' });
    expect(likeBtn).toHaveAttribute('aria-pressed', 'true');
  });

  it('inactive signals have aria-pressed=false', () => {
    render(
      <FeedbackButtonRow activeSignal="like" pending={false} onPress={vi.fn()} locale="en" />,
    );
    const dislikeBtn = screen.getByRole('button', { name: 'Dislike' });
    expect(dislikeBtn).toHaveAttribute('aria-pressed', 'false');
  });

  it('calls onPress with correct signal on click', async () => {
    const onPress = vi.fn();
    render(
      <FeedbackButtonRow activeSignal={null} pending={false} onPress={onPress} locale="en" />,
    );
    await userEvent.click(screen.getByRole('button', { name: 'Bookmark' }));
    expect(onPress).toHaveBeenCalledWith('bookmark');
  });

  it('disables all buttons when pending', () => {
    render(
      <FeedbackButtonRow activeSignal={null} pending={true} onPress={vi.fn()} locale="en" />,
    );
    for (const btn of screen.getAllByRole('button')) {
      expect(btn).toBeDisabled();
    }
  });

  it('applies variant class', () => {
    const { container } = render(
      <FeedbackButtonRow activeSignal={null} pending={false} onPress={vi.fn()} locale="en" variant="detail" />,
    );
    expect(container.querySelector('[class*="detail"]')).toBeInTheDocument();
  });
});
