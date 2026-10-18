import { describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '../../test/utils';
import PromotionRowAction from './PromotionRowAction';

describe('PromotionRowAction (#614)', () => {
  it('renders nothing while the offer is off (no promotion key)', () => {
    const { container } = renderWithProviders(
      <PromotionRowAction eventId={1} eventTitle="Jazz Night" promotion={undefined} locale="en" />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing for a row that is neither promotable nor badged', () => {
    const { container } = renderWithProviders(
      <PromotionRowAction eventId={1} eventTitle="Jazz Night" promotion={{ promotable: false, badge: null }} locale="en" />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it('links Promote to the request form for that event, named for screen readers', () => {
    renderWithProviders(
      <PromotionRowAction eventId={7} eventTitle="Jazz Night" promotion={{ promotable: true, badge: null }} locale="en" />,
    );
    const link = screen.getByRole('link', { name: 'Promote Jazz Night' });
    expect(link).toHaveTextContent('Promote');
    expect(link).toHaveAttribute('href', '/organizer/promotions/new?event_id=7');
  });

  it('replaces Promote with the status badge, localized', () => {
    renderWithProviders(
      <PromotionRowAction eventId={7} eventTitle="Jazz Night" promotion={{ promotable: true, badge: 'requested' }} locale="et" />,
    );
    const badge = screen.getByRole('link', { name: 'Taotletud: Jazz Night. Ava reklaamid.' });
    expect(badge).toHaveTextContent('Taotletud');
    expect(badge).toHaveAttribute('href', '/organizer/promotions?event=7');
    expect(screen.queryByText('Reklaami')).not.toBeInTheDocument();
  });
});
