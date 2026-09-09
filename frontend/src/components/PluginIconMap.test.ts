import { describe, expect, it } from 'vitest';
import { getPluginIcon } from './PluginIconMap';

describe('getPluginIcon', () => {
  it('maps sitemap and keeps circle fallback for unknown names', () => {
    expect(getPluginIcon('sitemap')).toBeDefined();
    expect(getPluginIcon('sitemap')).not.toEqual(getPluginIcon('unknown-icon-name'));
    expect(getPluginIcon('unknown-icon-name')).toEqual(getPluginIcon(undefined));
  });
});
