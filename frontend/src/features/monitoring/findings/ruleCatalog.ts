import type { TFunction } from 'i18next';

export type RuleInfo = {
  titleKey: string;
  descriptionKey: string;
  remediationKey: string;
};

export const RULE_CODES = [
  'baseline_required',
  'brand_required',
  'gtin_mpn',
  'enum_values',
  'conditional_required',
  'date_format',
  'length_limits',
  'cardinality',
  'currency_consistency',
  'image_requirements',
  'variant_consistency',
  'volume_drop',
  'ai_policy_check',
] as const;

export const RULE_CATALOG: Record<string, RuleInfo> = Object.fromEntries(
  RULE_CODES.map((code) => [
    code,
    {
      titleKey: `rules.${code}.title`,
      descriptionKey: `rules.${code}.description`,
      remediationKey: `rules.${code}.remediation`,
    },
  ]),
);

export const UNKNOWN_RULE: RuleInfo = {
  titleKey: 'rules.unknown.title',
  descriptionKey: 'rules.unknown.description',
  remediationKey: 'rules.unknown.remediation',
};

export function ruleInfo(code: string): RuleInfo {
  return RULE_CATALOG[code] ?? UNKNOWN_RULE;
}

export function ruleTitle(code: string, t: TFunction): string {
  return t(ruleInfo(code).titleKey, { code, defaultValue: code });
}
