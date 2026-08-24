import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App';

const fetchMock = vi.fn<typeof fetch>();

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

beforeEach(() => {
  vi.stubGlobal('fetch', fetchMock);
  fetchMock.mockReset();
});

it('shows the login form after an unauthenticated session check', async () => {
  fetchMock.mockResolvedValueOnce(jsonResponse({ detail: 'Not authenticated' }, 401));

  render(<App />);
  expect(await screen.findByLabelText(/username/i)).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledWith('/auth/me', expect.objectContaining({ credentials: 'include' }));
});

it('submits credentials and renders the authenticated shell', async () => {
  fetchMock.mockResolvedValueOnce(jsonResponse({}, 401));
  fetchMock.mockResolvedValueOnce(jsonResponse({ username: 'operator' }));
  const user = userEvent.setup();

  render(<App />);
  await user.type(await screen.findByLabelText(/username/i), 'operator');
  await user.type(screen.getByLabelText(/password/i), 'correct');
  await user.click(screen.getByRole('button', { name: /sign in/i }));

  expect(await screen.findByText(/signed in as operator/i)).toBeInTheDocument();
});

it('shows a generic login error and stays on the form after a 401', async () => {
  fetchMock.mockResolvedValueOnce(jsonResponse({}, 401));
  fetchMock.mockResolvedValueOnce(jsonResponse({ detail: 'Invalid credentials' }, 401));
  const user = userEvent.setup();

  render(<App />);
  await user.click(await screen.findByRole('button', { name: /sign in/i }));

  expect(await screen.findByRole('alert')).toHaveTextContent(/unable to sign in/i);
  expect(screen.getByLabelText(/username/i)).toBeInTheDocument();
});

it('logs out and returns to the login form', async () => {
  fetchMock.mockResolvedValueOnce(jsonResponse({ username: 'operator' }));
  fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
  const user = userEvent.setup();

  render(<App />);
  expect(await screen.findByText(/signed in as operator/i)).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: /sign out/i }));

  expect(await screen.findByRole('button', { name: /sign in/i })).toBeInTheDocument();
});

it('records an explicit interaction', async () => {
  fetchMock.mockResolvedValueOnce(jsonResponse({ username: 'operator' }));
  fetchMock.mockResolvedValueOnce(jsonResponse({ username: 'operator' }));
  const user = userEvent.setup();

  render(<App />);
  await screen.findByText(/signed in as operator/i);
  await user.click(screen.getByRole('button', { name: /record interaction/i }));

  expect(fetchMock).toHaveBeenLastCalledWith('/auth/interaction', expect.objectContaining({
    method: 'POST',
    credentials: 'include',
  }));
});
