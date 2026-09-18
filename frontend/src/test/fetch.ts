import { existsSync, readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { vi } from 'vitest';

const localesDir = resolve(dirname(fileURLToPath(import.meta.url)), '../../public/locales');

export function localeResponse(url: string): Response | undefined {
  const match = url.match(/^\/locales\/([^/]+)\/([^/]+)\.json$/);
  if (!match) return undefined;
  const file = resolve(localesDir, match[1], `${match[2]}.json`);
  if (!existsSync(file)) return undefined;
  return new Response(readFileSync(file, 'utf8'), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
}

export function requestBody(init?: RequestInit): string {
  return typeof init?.body === 'string' ? init.body : '';
}

export function requestUrl(input: RequestInfo | URL): string {
  return typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
}

export function stubFetch(
  handler: (url: string, init?: RequestInit) => Response | Promise<Response>,
) {
  const fetchMock = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(
    async (url, init) => {
      const locale = localeResponse(url);
      if (locale) return locale;
      return handler(url, init);
    },
  );
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}
