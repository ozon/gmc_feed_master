import { beforeAll, describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { render } from '../../test/render';
import { LoginPage } from './LoginPage';
import i18n from '../../i18n';

function renderLogin() {
  return render(
    <MemoryRouter initialEntries={['/login']}>
      <LoginPage />
    </MemoryRouter>,
  );
}

beforeAll(async () => {
  await i18n.loadNamespaces('auth');
});

describe('LoginPage', () => {
  it('autofocuses the username input', () => {
    const { container } = renderLogin();
    const allInputs = container.querySelectorAll('input');
    expect(allInputs.length).toBeGreaterThanOrEqual(2);
    const username = allInputs[0];
    expect(username).toHaveAttribute('autocomplete', 'username');
    expect(username).toHaveFocus();
  });

  it('renders all form fields', () => {
    renderLogin();
    expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument();
  });
});
