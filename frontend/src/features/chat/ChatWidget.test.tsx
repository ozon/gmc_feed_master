import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';
import {QueryClient} from '@tanstack/react-query';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { stubFetch } from '../../test/fetch';
import { ChatWidget } from './ChatWidget';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}


beforeAll(async () => {
  await i18n.loadNamespaces('chat');
});

beforeEach(() => {
  stubFetch((url, init) => {
    if (url === '/auth/me') {
      return jsonResponse({ username: 'admin', role: 'admin', is_active: true });
    }
    if (url === '/chat' && init?.method === 'POST') {
      return jsonResponse({ content: 'You have two feed sources.' });
    }
    return jsonResponse({});
  });
});

describe('ChatWidget', () => {
  it('opens the drawer on icon click and shows the admin scope badge', async () => {
    render(<ChatWidget />);
    fireEvent.click(screen.getByLabelText(/open ai chat/i));
    expect(await screen.findByText(/ai chat/i)).toBeInTheDocument();
    expect(await screen.findByText(/admin — all clients/i)).toBeInTheDocument();
  });

  it('sends on Enter, clears input, and appends the assistant reply', async () => {
    render(<ChatWidget />);
    fireEvent.click(screen.getByLabelText(/open ai chat/i));
    const input = await screen.findByLabelText(/message/i);
    fireEvent.change(input, { target: { value: 'what feed sources do I have?' } });
    fireEvent.keyDown(input, { key: 'Enter', shiftKey: false });
    await waitFor(() => {
      expect(screen.getByTestId('chat-message-0')).toHaveTextContent('what feed sources do I have?');
    });
    expect(input).toHaveValue('');
    await waitFor(() => {
      expect(screen.getByTestId('chat-message-1')).toHaveTextContent('You have two feed sources.');
    });
  });

  it('renders an inline alert when the mutation fails', async () => {
    stubFetch((url, init) => {
      if (url === '/auth/me') {
        return jsonResponse({ username: 'admin', role: 'admin', is_active: true });
      }
      if (url === '/chat' && init?.method === 'POST') {
        return jsonResponse({ detail: 'ai unavailable' }, 503);
      }
      return jsonResponse({});
    });
    render(<ChatWidget />);
    fireEvent.click(screen.getByLabelText(/open ai chat/i));
    const input = await screen.findByLabelText(/message/i);
    fireEvent.change(input, { target: { value: 'hello' } });
    fireEvent.keyDown(input, { key: 'Enter', shiftKey: false });
    expect(await screen.findByRole('alert')).toBeInTheDocument();
  });

  it('has en/de locale parity', async () => {
    await i18n.loadNamespaces('chat');
    await i18n.changeLanguage('de');
    const en = (i18n.getResourceBundle('en', 'chat') ?? {}) as Record<string, string>;
    const de = (i18n.getResourceBundle('de', 'chat') ?? {}) as Record<string, string>;
    expect(Object.keys(en).sort()).toEqual(Object.keys(de).sort());
    for (const key of Object.keys(en)) {
      expect(de[key]).toBeTruthy();
    }
    await i18n.changeLanguage('en');
  });
});
