export type User = { username: string };

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number) {
    super(`Request failed with status ${status}`);
    this.name = 'ApiError';
    this.status = status;
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, { ...init, credentials: 'include' });
  if (!response.ok) throw new ApiError(response.status);
  if (response.status === 204) return undefined as T;
  const contentLength = response.headers.get('content-length');
  const contentType = response.headers.get('content-type');
  if (contentLength === '0' || (contentType && !contentType.includes('application/json'))) {
    return undefined as T;
  }
  const text = await response.text();
  return text ? (JSON.parse(text) as T) : (undefined as T);
}

export function login(username: string, password: string): Promise<User> {
  return request<User>('/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
}

export function getCurrentUser(): Promise<User> {
  return request<User>('/auth/me');
}

export function logout(): Promise<void> {
  return request<void>('/auth/logout', { method: 'POST' });
}

export function recordInteraction(): Promise<User> {
  return request<User>('/auth/interaction', { method: 'POST' });
}
