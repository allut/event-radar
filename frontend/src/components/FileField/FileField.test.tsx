import { describe, it, expect, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import FileField from './FileField';
import { renderWithProviders } from '../../test/utils';

const baseProps = {
  id: 'image',
  accept: 'image/jpeg,image/png',
  onSelect: vi.fn(),
  onClear: vi.fn(),
  previewUrl: '',
  chooseLabel: 'Choose image',
  replaceLabel: 'Replace',
  emptyLabel: 'No image selected',
  uploadingLabel: 'Uploading image…',
  removeLabel: 'Remove image',
};

describe('FileField', () => {
  it('shows the empty state with no remove button', () => {
    renderWithProviders(<FileField {...baseProps} />);
    expect(screen.getByText('No image selected')).toBeInTheDocument();
    expect(screen.getByText('Choose image')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Remove image' })).not.toBeInTheDocument();
  });

  it('fires onSelect and shows the filename when a file is picked', async () => {
    const onSelect = vi.fn();
    renderWithProviders(<FileField {...baseProps} onSelect={onSelect} />);
    const file = new File(['content'], 'poster.jpg', { type: 'image/jpeg' });
    const input = document.getElementById('image') as HTMLInputElement;

    await userEvent.upload(input, file);

    expect(onSelect).toHaveBeenCalledWith(file);
    expect(screen.getByText('poster.jpg')).toBeInTheDocument();
  });

  it('renders the preview image and remove button when previewUrl is set', () => {
    const { container } = renderWithProviders(<FileField {...baseProps} previewUrl="https://res.cloudinary.com/demo/image/upload/v1/poster.jpg" />);
    const img = container.querySelector('img');
    expect(img).toHaveAttribute('src', 'https://res.cloudinary.com/demo/image/upload/v1/poster.jpg');
    expect(screen.getByRole('button', { name: 'Remove image' })).toBeInTheDocument();
    expect(screen.getByText('Replace')).toBeInTheDocument();
  });

  it('fires onClear when the remove button is clicked', async () => {
    const onClear = vi.fn();
    renderWithProviders(<FileField {...baseProps} previewUrl="https://example.com/poster.jpg" onClear={onClear} />);
    await userEvent.click(screen.getByRole('button', { name: 'Remove image' }));
    expect(onClear).toHaveBeenCalled();
  });

  it('shows the uploading label when uploading', () => {
    renderWithProviders(<FileField {...baseProps} uploading />);
    expect(screen.getByText('Uploading image…')).toBeInTheDocument();
  });

  it('disables the pick and remove buttons when disabled', () => {
    renderWithProviders(<FileField {...baseProps} previewUrl="https://example.com/poster.jpg" disabled />);
    expect(document.getElementById('image')).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Remove image' })).toBeDisabled();
  });
});
