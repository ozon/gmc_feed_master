import { describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { render } from '../test/render';
import { CopyField } from './CopyField';

describe('CopyField', () => {
  it('copies the value to the clipboard', async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText },
      configurable: true,
      writable: true,
    });
    render(<CopyField label="Export URL" value="http://localhost/export/abc.xml" />);

    expect(screen.getByDisplayValue('http://localhost/export/abc.xml')).toHaveAttribute('readonly');
    await user.click(screen.getByRole('button', { name: 'Copy' }));
    expect(writeText).toHaveBeenCalledWith('http://localhost/export/abc.xml');
  });
});
