export type LogLevel = 'debug' | 'info' | 'warn' | 'error';
export type LogContext = Record<string, unknown>;

type LogEntry = {
  level: LogLevel;
  message: string;
  scope: string;
  route: string;
  url: string;
  request_id: string;
  context: LogContext;
  stack?: string;
  timestamp: string;
};

const SENSITIVE = [
  'password',
  'passwd',
  'token',
  'secret',
  'cookie',
  'authorization',
  'api_key',
  'apikey',
  'session',
  'credential',
  'private_key',
  'access_key',
  'refresh_token',
];
const MAX_VALUE = 2000;
const MAX_DEPTH = 3;
const MAX_BATCH = 10;
const FLUSH_INTERVAL_MS = 5000;

function isSensitive(key: string): boolean {
  const lowered = key.toLowerCase();
  return SENSITIVE.some((marker) => lowered.includes(marker));
}

function truncate(value: string): string {
  return value.length <= MAX_VALUE ? value : `${value.slice(0, MAX_VALUE)}…[truncated]`;
}

function scrub(value: unknown, depth = 0): unknown {
  if (depth >= MAX_DEPTH) return value;
  if (Array.isArray(value)) return value.map((item) => scrub(item, depth + 1));
  if (value !== null && typeof value === 'object') {
    const out: Record<string, unknown> = {};
    for (const [key, item] of Object.entries(value as Record<string, unknown>)) {
      out[key] = isSensitive(key) ? '[REDACTED]' : scrub(item, depth + 1);
    }
    return out;
  }
  if (typeof value === 'string') return truncate(value);
  return value;
}

let queue: LogEntry[] = [];
let timer: ReturnType<typeof setTimeout> | null = null;

function flush(): void {
  if (queue.length === 0) return;
  const entries = queue.splice(0, queue.length);
  const body = JSON.stringify({ entries });
  try {
    if (typeof navigator !== 'undefined' && typeof navigator.sendBeacon === 'function') {
      navigator.sendBeacon('/logs/client', new Blob([body], { type: 'application/json' }));
      return;
    }
  } catch {
    // fall through to fetch
  }
  void fetch('/logs/client', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body,
    keepalive: true,
    credentials: 'include',
  }).catch(() => undefined);
}

function enqueue(entry: LogEntry): void {
  queue.push(entry);
  if (queue.length >= MAX_BATCH) {
    if (timer !== null) {
      clearTimeout(timer);
      timer = null;
    }
    flush();
    return;
  }
  if (timer === null) {
    timer = setTimeout(() => {
      timer = null;
      flush();
    }, FLUSH_INTERVAL_MS);
  }
}

export function flushLogs(): void {
  flush();
}

export function resetLogQueue(): void {
  queue = [];
  if (timer !== null) {
    clearTimeout(timer);
    timer = null;
  }
}

export function newRequestId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `${Math.random().toString(36).slice(2)}${Date.now().toString(36)}`;
}

function currentPath(): string {
  return typeof window === 'undefined' ? '' : window.location.pathname;
}

export function createLogger(scope: string) {
  const log = (level: LogLevel, message: string, context: LogContext = {}, error?: unknown) => {
    const safe = scrub(context) as LogContext;
    if (level === 'debug' || level === 'info') {
      console[level](`[${scope}] ${message}`, safe);
      return;
    }
    console[level](`[${scope}] ${message}`, safe, error ?? '');
    enqueue({
      level,
      message: truncate(message),
      scope,
      route: currentPath(),
      url: currentPath(),
      request_id: typeof safe.request_id === 'string' ? safe.request_id : newRequestId(),
      context: safe,
      stack: error instanceof Error ? error.stack?.slice(0, 8000) : undefined,
      timestamp: new Date().toISOString(),
    });
  };
  return {
    debug: (message: string, context?: LogContext) => log('debug', message, context),
    info: (message: string, context?: LogContext) => log('info', message, context),
    warn: (message: string, context?: LogContext, error?: unknown) =>
      log('warn', message, context, error),
    error: (message: string, context?: LogContext, error?: unknown) =>
      log('error', message, context, error),
  };
}

export const logger = createLogger('app');

export function captureException(error: unknown, context: LogContext = {}): void {
  const scope = typeof context.scope === 'string' ? context.scope : 'app';
  const message = error instanceof Error ? error.message : String(error);
  createLogger(scope).error(message, context, error);
}

export function installGlobalErrorHandlers(): void {
  window.addEventListener('error', (event) => {
    createLogger('window').error(
      event.message,
      { url: currentPath() },
      event.error,
    );
  });
  window.addEventListener('unhandledrejection', (event) => {
    createLogger('promise').error(
      'unhandledrejection',
      { url: currentPath() },
      event.reason,
    );
  });
  window.addEventListener('pagehide', flush);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') flush();
  });
}
