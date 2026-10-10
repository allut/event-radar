import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import EventOverflowMenu from './EventOverflowMenu';
import styles from './EventOverflowMenu.module.css';

function renderMenu(anchor?: 'left' | 'right') {
  render(
    <EventOverflowMenu locale="en" reported={false} onShare={vi.fn()} onReport={vi.fn()} anchor={anchor} />,
  );
}

async function openMenu() {
  await userEvent.click(screen.getByRole('button', { name: 'More options' }));
  return screen.getByRole('menu');
}

describe('EventOverflowMenu anchor', () => {
  it('right-anchors the popover by default (EventCard corner trigger)', async () => {
    renderMenu();
    const pop = await openMenu();
    expect(styles.popRight).toBeTruthy();
    expect(pop.className).toContain(styles.popRight);
  });

  it('drops the right-anchor override when anchor is left (EventDetail mid-row trigger)', async () => {
    renderMenu('left');
    const pop = await openMenu();
    expect(pop.className).toContain(styles.pop);
    expect(pop.className).not.toContain(styles.popRight);
  });
});
