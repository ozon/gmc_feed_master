import { describe, expect, it } from 'vitest';
import type { PluginInfo } from '../../api/types';
import {
  configEditableAtFeed,
  highestEditableConfigTier,
  scopeForTier,
  tierOptions,
} from './tierUtils';

const labelizer: PluginInfo['manifest'] = {
  config_scope: ['global', 'client'],
  data_scope: ['client', 'feed_source'],
};

const rules: PluginInfo['manifest'] = {
  config_scope: ['global', 'client', 'feed_source'],
  data_scope: ['global', 'client', 'feed_source'],
};

describe('tierOptions', () => {
  it('derives most-specific-first tiers from manifest scopes and route availability', () => {
    expect(tierOptions(labelizer, { hasFeedSource: true, hasClient: true }))
      .toEqual(['feed_source', 'client', 'global']);
  });

  it('omits feed_source when no feed source is in context', () => {
    expect(tierOptions(labelizer, { hasFeedSource: false, hasClient: true }))
      .toEqual(['client', 'global']);
  });

  it('accepts a string scope value', () => {
    expect(tierOptions({ data_scope: 'client' }, { hasFeedSource: true, hasClient: true }))
      .toEqual(['client']);
  });
});

describe('scopeForTier', () => {
  it('maps tiers to PluginScope using route ids', () => {
    const route = { clientId: '3', feedSourceId: '9' };
    expect(scopeForTier('feed_source', route)).toEqual({ feedSourceId: 9 });
    expect(scopeForTier('client', route)).toEqual({ clientId: 3 });
    expect(scopeForTier('global', route)).toEqual({});
  });
});

describe('config editability', () => {
  it('labelizer config is not editable at feed tier; client is the highest editable tier', () => {
    expect(configEditableAtFeed(labelizer)).toBe(false);
    expect(highestEditableConfigTier(labelizer)).toBe('client');
  });

  it('rules config is editable at feed tier', () => {
    expect(configEditableAtFeed(rules)).toBe(true);
    expect(highestEditableConfigTier(rules)).toBe('client');
  });

  it('falls back to global when client is not in config_scope', () => {
    expect(highestEditableConfigTier({ config_scope: ['global'] })).toBe('global');
    expect(highestEditableConfigTier(null)).toBe(null);
  });
});
