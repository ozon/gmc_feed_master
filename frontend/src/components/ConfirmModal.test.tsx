import { describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { render } from '../test/render';
import { ConfirmModal } from './ConfirmModal';

describe('ConfirmModal', () => {
  it('confirms and cancels', async () => {
    const onConfirm = vi.fn();
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(
      <ConfirmModal
        opened
        title="Delete client"
        message="This cannot be undone."
        danger
        onConfirm={onConfirm}
        onClose={onClose}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'Confirm' }));
    expect(onConfirm).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('disables confirm until typeToConfirm matches exactly', async () => {
    const onConfirm = vi.fn();
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(
      <ConfirmModal
        opened
        title="Delete feed"
        message="This cannot be undone."
        typeToConfirm="Acme"
        danger
        onConfirm={onConfirm}
        onClose={onClose}
      />,
    );

    const confirm = screen.getByRole('button', { name: 'Confirm' });
    expect(confirm).toBeDisabled();

    const input = screen.getByLabelText(/type acme to confirm/i);
    await user.type(input, 'Ac');
    expect(confirm).toBeDisabled();

    await user.type(input, 'me');
    expect(confirm).toBeEnabled();

    await user.click(confirm);
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });
});
