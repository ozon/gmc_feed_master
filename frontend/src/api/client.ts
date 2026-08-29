export type User = { username: string };

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string | undefined;

  constructor(status: number, detail?: string) {
    super(detail ?? `Request failed with status ${status}`);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

type UnauthorizedHandler = () => void;
let unauthorizedHandler: UnauthorizedHandler | null = null;

export function setUnauthorizedHandler(handler: UnauthorizedHandler | null) {
  unauthorizedHandler = handler;
}

async function parseError(response: Response): Promise<ApiError> {
  let detail: string | undefined;
  try {
    const body = (await response.json()) as { detail?: string };
    detail = body.detail;
  } catch {
    detail = undefined;
  }
  return new ApiError(response.status, detail);
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, { ...init, credentials: 'include' });
  if (!response.ok) {
    if (response.status === 401 && unauthorizedHandler && !url.startsWith('/auth/login')) {
      unauthorizedHandler();
    }
    throw await parseError(response);
  }
  if (response.status === 204) return undefined as T;
  const contentType = response.headers.get('content-type');
  if (contentType && !contentType.includes('application/json')) return undefined as T;
  const text = await response.text();
  return text ? (JSON.parse(text) as T) : (undefined as T);
}

function jsonInit(method: string, body?: unknown): RequestInit {
  return {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  };
}

export function apiGet<T>(url: string): Promise<T> {
  return request<T>(url);
}

export function apiPost<T>(url: string, body?: unknown): Promise<T> {
  return request<T>(url, jsonInit('POST', body));
}

export function apiPut<T>(url: string, body?: unknown): Promise<T> {
  return request<T>(url, jsonInit('PUT', body));
}

export function apiDelete<T>(url: string): Promise<T> {
  return request<T>(url, { method: 'DELETE' });
}

export function login(username: string, password: string): Promise<User> {
  return apiPost<User>('/auth/login', { username, password });
}

export function getCurrentUser(): Promise<User> {
  return apiGet<User>('/auth/me');
}

export function logout(): Promise<{ status: string }> {
  return apiPost<{ status: string }>('/auth/logout');
}

export function changePassword(currentPassword: string, newPassword: string): Promise<{ status: string }> {
  return apiPost<{ status: string }>('/auth/password', {
    current_password: currentPassword,
    new_password: newPassword,
  });
}
