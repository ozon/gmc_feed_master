import { describe, expect, it } from 'vitest';
import { SEVERITIES, severityColor, severityRank } from './severity';

describe('severity', () => {
  it('orders severities critical, warning, info', () => {
    expect(SEVERITIES).toEqual(['critical', 'warning', 'info']);
  });

  it('maps severities to Mantine colors', () => {
    expect(severityColor('critical')).toBe('red');
    expect(severityColor('warning')).toBe('yellow');
    expect(severityColor('info')).toBe('blue');
    expect(severityColor('nonsense')).toBe('gray');
  });

  it('ranks critical first and unknown last', () => {
    expect(severityRank('critical')).toBeLessThan(severityRank('warning'));
    expect(severityRank('warning')).toBeLessThan(severityRank('info'));
    expect(severityRank('nonsense')).toBe(99);
  });
});
