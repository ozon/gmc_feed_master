import { describe, expect, it } from 'vitest';
import { getPluginIcon } from './PluginIconMap';

describe('getPluginIcon', () => {
  it('maps every registry name to a distinct icon', () => {
    for (const name of [
      'cog', 'database', 'tag', 'wand', 'shield', 'lock', 'link',
      'mail', 'chart', 'transform', 'sitemap', 'letter-e', 'list-check',
    ]) {
      expect(getPluginIcon(name)).toBeDefined();
      expect(getPluginIcon(name)).not.toEqual(getPluginIcon(undefined));
    }
  });

  it('keeps the circle fallback for unknown names', () => {
    expect(getPluginIcon('unknown-icon-name')).toEqual(getPluginIcon(undefined));
  });
});
