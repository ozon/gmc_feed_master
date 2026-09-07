import type { PluginScope } from '../api/hooks';

export const probeScopes: Array<{ pluginId: string; scope: PluginScope }> = [];
export let crashOnRender = false;

export function setCrashOnRender(value: boolean) {
  crashOnRender = value;
}

export function resetProbe() {
  probeScopes.length = 0;
  crashOnRender = false;
}

export function ProbeComponent({ pluginId, scope }: { pluginId: string; scope: PluginScope }) {
  if (crashOnRender) throw new Error('boom');
  probeScopes.push({ pluginId, scope });
  return (
    <div
      data-testid="probe-component"
      data-plugin-id={pluginId}
      data-scope={JSON.stringify(scope)}
    />
  );
}
