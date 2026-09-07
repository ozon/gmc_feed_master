import type { PluginInfo } from '../../api/types';
import type { PluginScope } from '../../api/hooks';

export type ConfigTier = 'feed_source' | 'client' | 'global';

export function manifestScopes(
  manifest: PluginInfo['manifest'],
  key: 'config_scope' | 'data_scope',
): string[] {
  const value = manifest?.[key];
  if (typeof value === 'string') return [value];
  if (Array.isArray(value)) return value.filter((item): item is string => typeof item === 'string');
  return [];
}

export function tierOptions(
  manifest: PluginInfo['manifest'],
  available: { hasFeedSource: boolean; hasClient: boolean },
): ConfigTier[] {
  const scopes = new Set([
    ...manifestScopes(manifest, 'config_scope'),
    ...manifestScopes(manifest, 'data_scope'),
  ]);
  const tiers: ConfigTier[] = [];
  if (available.hasFeedSource && scopes.has('feed_source')) tiers.push('feed_source');
  if (available.hasClient && scopes.has('client')) tiers.push('client');
  if (scopes.has('global')) tiers.push('global');
  return tiers;
}

export function scopeForTier(
  tier: ConfigTier,
  route: { clientId?: string | number; feedSourceId?: string | number },
): PluginScope {
  if (tier === 'feed_source') return { feedSourceId: Number(route.feedSourceId) };
  if (tier === 'client') return { clientId: Number(route.clientId) };
  return {};
}

export function configEditableAtFeed(manifest: PluginInfo['manifest']): boolean {
  return manifestScopes(manifest, 'config_scope').includes('feed_source');
}

export function highestEditableConfigTier(
  manifest: PluginInfo['manifest'],
): 'client' | 'global' | null {
  const scopes = manifestScopes(manifest, 'config_scope');
  if (scopes.includes('client')) return 'client';
  if (scopes.includes('global')) return 'global';
  return null;
}
