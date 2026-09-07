import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import RichTextEditor from './RichTextEditor';

function getContent(container: HTMLElement): HTMLElement {
  const el = container.querySelector('[contenteditable="true"]');
  if (!el) throw new Error('contenteditable not found');
  return el as HTMLElement;
}


describe('RichTextEditor', () => {
  it('renders icon-only mark/list buttons and H3/H4 text glyphs, grouped with dividers', async () => {
    const onChange = vi.fn();
    render(<RichTextEditor value="<p>Hello</p>" onChange={onChange} locale="en" />);

    await waitFor(() => expect(screen.getByRole('toolbar', { name: 'Formatting' })).toBeInTheDocument());

    for (const label of ['Bold', 'Italic', 'Underline', 'Bullet list', 'Numbered list', 'Blockquote', 'Insert link']) {
      const btn = screen.getByRole('button', { name: label });
      expect(btn.querySelector('svg')).toBeInTheDocument();
      expect(btn.textContent).toBe('');
    }

    expect(screen.getByRole('button', { name: 'H3' })).toHaveTextContent('H3');
    expect(screen.getByRole('button', { name: 'H4' })).toHaveTextContent('H4');

    const toolbar = screen.getByRole('toolbar', { name: 'Formatting' });
    expect(toolbar.querySelectorAll('[class*="divider"]').length).toBe(3);
  });

  it('does not render any button for disallowed formatting', () => {
    const onChange = vi.fn();
    render(<RichTextEditor value="<p>Hello</p>" onChange={onChange} locale="en" />);

    for (const forbidden of ['Strikethrough', 'Code', 'Code block', 'Horizontal rule', 'H1', 'H2', 'H5', 'H6']) {
      expect(screen.queryByRole('button', { name: forbidden })).not.toBeInTheDocument();
    }
  });

  it('reflects heading active state on the toolbar when the cursor is in a heading', async () => {
    const onChange = vi.fn();
    const { container } = render(<RichTextEditor value="<p>Hello</p>" onChange={onChange} locale="en" />);
    await waitFor(() => getContent(container));

    const h3Button = screen.getByRole('button', { name: 'H3' });
    expect(h3Button).toHaveAttribute('aria-pressed', 'false');

    fireEvent.click(h3Button);

    await waitFor(() => expect(h3Button).toHaveAttribute('aria-pressed', 'true'));
    expect(h3Button).toHaveAttribute('data-active');
    await waitFor(() => expect(onChange).toHaveBeenCalledWith(expect.stringContaining('<h3>')));
  });

  it('reflects bullet-list active state on the toolbar', async () => {
    const onChange = vi.fn();
    const { container } = render(<RichTextEditor value="<p>Hello</p>" onChange={onChange} locale="en" />);
    await waitFor(() => getContent(container));

    const bulletButton = screen.getByRole('button', { name: 'Bullet list' });
    expect(bulletButton).toHaveAttribute('aria-pressed', 'false');

    fireEvent.click(bulletButton);

    await waitFor(() => expect(bulletButton).toHaveAttribute('aria-pressed', 'true'));
    await waitFor(() => expect(onChange).toHaveBeenCalledWith(expect.stringContaining('<ul>')));
  });

  it('opens the inline link row, closes it on cancel with no change, and applies the link to a selection', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const { container } = render(<RichTextEditor value="<p>Hello</p>" onChange={onChange} locale="en" />);
    const content = await waitFor(() => getContent(container));

    expect(screen.queryByPlaceholderText('https://…')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Insert link' }));
    const input = screen.getByPlaceholderText('https://…');
    expect(input).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByPlaceholderText('https://…')).not.toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();

    await user.click(content);
    await user.keyboard('{Control>}a{/Control}');
    await user.click(screen.getByRole('button', { name: 'Insert link' }));
    await user.type(screen.getByPlaceholderText('https://…'), 'https://example.com');
    await user.click(screen.getByRole('button', { name: 'Insert' }));

    expect(screen.queryByPlaceholderText('https://…')).not.toBeInTheDocument();
    await waitFor(() =>
      expect(onChange).toHaveBeenCalledWith(expect.stringContaining('href="https://example.com"')),
    );
  });

  it('strips disallowed tags/attributes from pasted content to the allowed mark set', async () => {
    const onChange = vi.fn();
    const { container } = render(<RichTextEditor value="<p></p>" onChange={onChange} locale="en" />);
    const content = await waitFor(() => getContent(container));

    const pasteHtml =
      '<h1>Big heading</h1>' +
      '<p><span style="color: red;">colored</span> and <strike>struck</strike> text ' +
      '<code>inline code</code></p>' +
      '<hr/>' +
      '<p><b>bold survives</b></p>';

    const clipboardData = {
      types: ['text/html', 'text/plain'],
      getData: (type: string) => (type === 'text/html' ? pasteHtml : 'plain fallback'),
    };

    fireEvent.paste(content, { clipboardData });

    await waitFor(() => expect(onChange).toHaveBeenCalled());
    const calls = onChange.mock.calls;
    const lastHtml = calls[calls.length - 1]?.[0] as string;

    expect(lastHtml).not.toMatch(/<h1/i);
    expect(lastHtml).not.toMatch(/<strike/i);
    expect(lastHtml).not.toMatch(/<code/i);
    expect(lastHtml).not.toMatch(/<hr/i);
    expect(lastHtml).not.toMatch(/color:\s*red/i);
    expect(lastHtml).toMatch(/<strong>bold survives<\/strong>/i);
  });

  it('disables all toolbar buttons and the field when disabled', () => {
    const onChange = vi.fn();
    render(<RichTextEditor value="<p>Hello</p>" onChange={onChange} disabled locale="en" />);

    for (const label of ['Bold', 'Italic', 'Underline', 'Bullet list', 'Numbered list', 'Blockquote', 'Insert link', 'H3', 'H4']) {
      expect(screen.getByRole('button', { name: label })).toBeDisabled();
    }
  });
});
