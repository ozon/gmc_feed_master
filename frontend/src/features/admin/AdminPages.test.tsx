import { describe, expect, it, vi } from 'vitest';
import { render } from '@testing-library/react';
import { MemoryRouter } from 'react-router';

vi.mock('../../api/hooks', async () => {
  const actual = await vi.importActual<typeof import('../../api/hooks')>('../../api/hooks');
  return {
    ...actual,
    useSession: vi.fn(() => ({
      data: { username: 'bob', role: 'user', client_ids: [1] },
      status: 'success',
    })),
  };
});

import { RequireAdmin } from '../../app/router';

describe('RequireAdmin', () => {
  it('redirects non-admin users away from admin routes', () => {
    const { container } = render(
      <MemoryRouter initialEntries={['/admin/users']}>
        <RequireAdmin />
      </MemoryRouter>,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
