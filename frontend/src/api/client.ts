export type User = { username: string; role: 'admin' | 'user'; client_ids: number[] | null };

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string | undefined;
  readonly errors: string[] | null;
  readonly detailObject: Record<string, unknown> | null;

  constructor(
    status: number,
    detail?: string,
    errors?: string[] | null,
    detailObject?: Record<string, unknown> | null,
  ) {
    super(detail ?? `Request failed with status ${status}`);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
    this.errors = errors ?? null;
    this.detailObject = detailObject ?? null;
  }
}

type UnauthorizedHandler = () => void;
let unauthorizedHandler: UnauthorizedHandler | null = null;

export function setUnauthorizedHandler(handler: UnauthorizedHandler | null) {
  unauthorizedHandler = handler;
}

async function parseError(response: Response): Promise<ApiError> {
  let detail: string | undefined;
  let detailObject: Record<string, unknown> | null = null;
  let errors: string[] | null = null;
  try {
    const body = (await response.json()) as {
      detail?: unknown;
      errors?: unknown;
    };
    if (Array.isArray(body.errors) && body.errors.every((item) => typeof item === 'string')) {
      errors = body.errors;
    } else if (typeof body.detail === 'string') {
      detail = body.detail;
    } else if (body.detail && typeof body.detail === 'object') {
      detailObject = body.detail as Record<string, unknown>;
    }
  } catch {
    detail = undefined;
  }
  return new ApiError(response.status, detail, errors, detailObject);
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, { ...init, credentials: 'include' });
  if (!response.ok) {
    const authExempt =
      url.startsWith('/auth/login') || url.startsWith('/auth/password');
    if (response.status === 401 && unauthorizedHandler && !authExempt) {
      unauthorizedHandler();
    }
    throw await parseError(response);
  }
  if (response.status === 204) return undefined as T;
  const contentType = response.headers.get('content-type');
  if (contentType && !contentType.includes('application/json')) {
    throw new ApiError(
      response.status,
      `Unexpected response content type: ${contentType}`,
    );
  }
  const text = await response.text();
  return text ? (JSON.parse(text) as T) : (undefined as T);
}

async function requestWithHeaders<T>(
  url: string,
  init?: RequestInit,
): Promise<{ data: T; headers: Headers }> {
  const response = await fetch(url, { ...init, credentials: 'include' });
  if (!response.ok) {
    const authExempt =
      url.startsWith('/auth/login') || url.startsWith('/auth/password');
    if (response.status === 401 && unauthorizedHandler && !authExempt) {
      unauthorizedHandler();
    }
    throw await parseError(response);
  }
  const text = await response.text();
  const data = (text ? JSON.parse(text) : undefined) as T;
  return { data, headers: response.headers };
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

export function apiGetWithHeaders<T>(url: string): Promise<{ data: T; headers: Headers }> {
  return requestWithHeaders<T>(url);
}

export function apiPost<T>(url: string, body?: unknown): Promise<T> {
  return request<T>(url, jsonInit('POST', body));
}

export function apiPut<T>(url: string, body?: unknown): Promise<T> {
  return request<T>(url, jsonInit('PUT', body));
}

export function apiPatch<T>(url: string, body?: unknown): Promise<T> {
  return request<T>(url, jsonInit('PATCH', body));
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
