export const SEVERITIES = ['critical', 'warning', 'info'] as const;

export type Severity = (typeof SEVERITIES)[number];

const SEVERITY_COLOR: Record<string, string> = {
  critical: 'red',
  warning: 'yellow',
  info: 'blue',
};

const SEVERITY_RANK: Record<string, number> = {
  critical: 0,
  warning: 1,
  info: 2,
};

export function severityColor(severity: string): string {
  return SEVERITY_COLOR[severity] ?? 'gray';
}

export function severityRank(severity: string): number {
  return SEVERITY_RANK[severity] ?? 99;
}
