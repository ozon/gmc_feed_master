import '@testing-library/jest-dom/vitest';
import { beforeAll, vi } from 'vitest';
import { configure } from '@testing-library/react';
import { localeResponse } from './fetch';
import { registerRelativeTime } from '../i18n/relativeTime';

registerRelativeTime();

configure({ asyncUtilTimeout: 5000 });

const originalGetComputedStyle = window.getComputedStyle.bind(window);
window.getComputedStyle = (elt) => originalGetComputedStyle(elt);
window.HTMLElement.prototype.scrollIntoView = () => {};

Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn<(query: string) => MediaQueryList>().mockImplementation((query) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn<MediaQueryList['addListener']>(),
    removeListener: vi.fn<MediaQueryList['removeListener']>(),
    addEventListener: vi.fn<MediaQueryList['addEventListener']>(),
    removeEventListener: vi.fn<MediaQueryList['removeEventListener']>(),
    dispatchEvent: vi.fn<MediaQueryList['dispatchEvent']>(),
  })),
});

if (!document.fonts) {
  Object.defineProperty(document, 'fonts', {
    writable: true,
    value: { addEventListener: vi.fn<() => void>(), removeEventListener: vi.fn<() => void>() },
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
  vi.fn(async (url: string) => {
    const locale = localeResponse(url);
    if (locale) return locale;
    throw new Error(`Unexpected fetch in test: ${url}`);
  }),
);

beforeAll(async () => {
  const { initPromise } = await import('../i18n');
  await initPromise;
});
