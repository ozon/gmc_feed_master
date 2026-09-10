import '@testing-library/jest-dom/vitest';
import { beforeAll, vi } from 'vitest';
import { configure } from '@testing-library/react';
import { localeResponse } from './fetch';

configure({ asyncUtilTimeout: 5000 });

const { getComputedStyle } = window;
window.getComputedStyle = (elt) => getComputedStyle(elt);
window.HTMLElement.prototype.scrollIntoView = () => {};

Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation((query) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});

if (!document.fonts) {
  Object.defineProperty(document, 'fonts', {
    writable: true,
    value: { addEventListener: vi.fn(), removeEventListener: vi.fn() },
  });
}

class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

window.ResizeObserver = ResizeObserver;

class MemoryStorage {
  private data = new Map<string, string>();

  get length(): number {
    return this.data.size;
  }

  clear(): void {
    this.data.clear();
  }

  getItem(key: string): string | null {
    return this.data.has(key) ? this.data.get(key)! : null;
  }

  key(index: number): string | null {
    return Array.from(this.data.keys())[index] ?? null;
  }

  removeItem(key: string): void {
    this.data.delete(key);
  }

  setItem(key: string, value: string): void {
    this.data.set(key, String(value));
  }
}

if (typeof window.localStorage === 'undefined' || window.localStorage === null) {
  Object.defineProperty(window, 'localStorage', {
    configurable: true,
    writable: true,
    value: new MemoryStorage(),
  });
}

vi.stubGlobal(
  'fetch',
  vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const locale = localeResponse(url);
    if (locale) return locale;
    throw new Error(`Unexpected fetch in test: ${url}`);
  }),
);

beforeAll(async () => {
  const { initPromise } = await import('../i18n');
  await initPromise;
});
