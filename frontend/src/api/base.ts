export const API_BASE = '/api';

export function withApiBase(url: string): string {
  if (!url.startsWith('/') || url.startsWith('//')) return url;
  if (url === API_BASE || url.startsWith(`${API_BASE}/`)) return url;
  return `${API_BASE}${url}`;
}
