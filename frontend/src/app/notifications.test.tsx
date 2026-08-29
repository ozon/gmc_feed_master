import { describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { render } from '../test/render';
import { Notifications } from '@mantine/notifications';
import { notifyError, notifyMutationError, notifySuccess } from './notifications';
import { ApiError } from '../api/client';

describe('notification helpers', () => {
  it('shows success and error notifications', async () => {
    render(<Notifications />);
    notifySuccess('Saved');
    expect(await screen.findByText('Saved')).toBeInTheDocument();
    notifyError('Request failed');
    expect(await screen.findByText('Request failed')).toBeInTheDocument();
  });

  it('prefers the ApiError detail for mutation errors', async () => {
    render(<Notifications />);
    notifyMutationError(new ApiError(422, 'name already exists'), 'Request failed');
    expect(await screen.findByText('name already exists')).toBeInTheDocument();
  });

  it('falls back when the error has no detail', async () => {
    render(<Notifications />);
    notifyMutationError(new Error('boom'), 'Request failed');
    expect(await screen.findByText('Request failed')).toBeInTheDocument();
  });
});
