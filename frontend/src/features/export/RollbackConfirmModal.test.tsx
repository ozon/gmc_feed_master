import { beforeAll, describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Notifications } from '@mantine/notifications';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { RollbackConfirmModal } from './RollbackConfirmModal';

beforeAll(async () => {
  await i18n.loadNamespaces('export');
});

describe('RollbackConfirmModal', () => {
  it('renders nothing when version is null', () => {
    const { container } = render(
      <>
        <Notifications position="top-right" limit={1} />
        <RollbackConfirmModal
          opened={false}
          version={null}
          onClose={() => {}}
          onConfirm={() => {}}
          pending={false}
        />
      </>,
    );
    expect(container.querySelector('[role="dialog"]')).toBeNull();
  });

  it('requires typing the version number to enable confirm', async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    render(
      <>
        <Notifications position="top-right" limit={1} />
        <RollbackConfirmModal
          opened
          version={42}
          onClose={() => {}}
          onConfirm={onConfirm}
          pending={false}
        />
      </>,
    );
    const confirm = await screen.findByRole('button', { name: /rollback/i });
    expect(confirm).toBeDisabled();
    const input = screen.getByLabelText(/type/i);
    await user.type(input, '42');
    expect(confirm).not.toBeDisabled();
    await user.click(confirm);
    expect(onConfirm).toHaveBeenCalledWith(42);
  });
});