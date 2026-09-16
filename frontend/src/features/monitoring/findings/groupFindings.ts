import type { QualityFinding } from '../../../api/types';
import { severityRank } from './severity';

export const FEED_LEVEL_KEY = '__feed__';

export type SeverityCounts = { critical: number; warning: number; info: number };

export type FindingGroup = {
  key: string;
  findings: QualityFinding[];
  counts: SeverityCounts;
};

export function countBySeverity(findings: QualityFinding[]): SeverityCounts {
  const counts: SeverityCounts = { critical: 0, warning: 0, info: 0 };
  for (const finding of findings) {
    if (finding.severity in counts) counts[finding.severity as keyof SeverityCounts] += 1;
  }
  return counts;
}

function sortGroups(groups: FindingGroup[]): FindingGroup[] {
  return [...groups].sort((a, b) => {
    const rankA = Math.min(...a.findings.map((f) => severityRank(f.severity)));
    const rankB = Math.min(...b.findings.map((f) => severityRank(f.severity)));
    if (rankA !== rankB) return rankA - rankB;
    if (a.findings.length !== b.findings.length) return b.findings.length - a.findings.length;
    return a.key.localeCompare(b.key);
  });
}

function groupBy(
  findings: QualityFinding[],
  keyOf: (finding: QualityFinding) => string,
): FindingGroup[] {
  const buckets = new Map<string, QualityFinding[]>();
  for (const finding of findings) {
    const key = keyOf(finding);
    const bucket = buckets.get(key);
    if (bucket) bucket.push(finding);
    else buckets.set(key, [finding]);
  }
  return sortGroups(
    [...buckets.entries()].map(([key, groupFindings]) => ({
      key,
      findings: groupFindings,
      counts: countBySeverity(groupFindings),
    })),
  );
}

export function groupByRule(findings: QualityFinding[]): FindingGroup[] {
  return groupBy(findings, (finding) => finding.code);
}

export function groupByAttribute(findings: QualityFinding[]): FindingGroup[] {
  return groupBy(findings, (finding) => finding.field ?? FEED_LEVEL_KEY);
}

export type FindingsFilter = {
  severities?: string[];
  rules?: string[];
  search?: string;
};

export function filterFindings(
  findings: QualityFinding[],
  { severities = [], rules = [], search = '' }: FindingsFilter,
): QualityFinding[] {
  const needle = search.trim().toLowerCase();
  return findings.filter((finding) => {
    if (severities.length > 0 && !severities.includes(finding.severity)) return false;
    if (rules.length > 0 && !rules.includes(finding.code)) return false;
    if (needle) {
      const haystack = `${finding.message} ${finding.product_id} ${finding.field ?? ''}`.toLowerCase();
      if (!haystack.includes(needle)) return false;
    }
    return true;
  });
}
