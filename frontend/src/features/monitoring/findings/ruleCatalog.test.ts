import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { RULE_CATALOG, RULE_CODES, ruleInfo, UNKNOWN_RULE } from './ruleCatalog';

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../../../../..');

const BACKEND_RULE_FILES = ['backend/app/qc/rules.py', 'backend/app/qc/ai_rules.py'];

function backendRuleIds(): string[] {
  const ids = new Set<string>();
  for (const relative of BACKEND_RULE_FILES) {
    const source = readFileSync(resolve(repoRoot, relative), 'utf8');
    for (const match of source.matchAll(/rule_id\s*=\s*"([^"]+)"/g)) ids.add(match[1]);
  }
  return [...ids].sort();
}

describe('ruleCatalog', () => {
  it('covers every backend rule_id', () => {
    const ids = backendRuleIds();
    expect(ids.length).toBeGreaterThan(0);
    for (const id of ids) {
      expect(RULE_CATALOG[id], `missing catalog entry for ${id}`).toBeDefined();
    }
  });

  it('lists exactly the known codes', () => {
    expect([...RULE_CODES].sort()).toEqual(Object.keys(RULE_CATALOG).sort());
  });

  it('falls back to the unknown rule', () => {
    expect(ruleInfo('does_not_exist')).toBe(UNKNOWN_RULE);
  });
});
