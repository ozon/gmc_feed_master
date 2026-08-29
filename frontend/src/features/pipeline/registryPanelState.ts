const KEY = 'pipeline.registryPanelOpen';

export function loadRegistryPanelOpen(): boolean {
  if (typeof window === 'undefined') return false;
  const raw = window.localStorage.getItem(KEY);
  return raw === 'true';
}

export function saveRegistryPanelOpen(open: boolean): void {
  if (typeof window === 'undefined') return;
  window.localStorage.setItem(KEY, String(open));
}