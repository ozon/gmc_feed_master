export type ConditionOp =
  | 'all' | 'and' | 'or'
  | 'equals' | 'contains' | 'starts_with' | 'ends_with' | 'regex' | 'exists' | 'empty'
  | 'gt' | 'lt' | 'gte' | 'lte' | 'between';

export type ActionOp = 'set' | 'replace' | 'append' | 'prepend' | 'remove' | 'clear' | 'ai';

export type RuleCondition = {
  op: ConditionOp;
  field?: string;
  arg?: string | number;
  arg2?: number;
  caseSensitive?: boolean;
  children?: RuleCondition[];
};

export type RuleAction = {
  op: ActionOp;
  field: string;
  value?: string;
  find?: string;
  with?: string;
  caseSensitive?: boolean;
  promptSource?: 'template' | 'custom';
  taskType?: string;
  templateId?: number;
  system?: string;
  user?: string;
  variables?: string[];
};

export type Rule = {
  id: string;
  name: string;
  isMasterRule: boolean;
  isActive: boolean;
  when: RuleCondition;
  then: RuleAction[];
};

export type RulesConfig = { rules: Rule[] };

export const CONDITION_TEXT_OPS = ['equals', 'contains', 'starts_with', 'ends_with', 'regex'] as const;
export const CONDITION_NUMERIC_OPS = ['gt', 'lt', 'gte', 'lte', 'between'] as const;

const CONDITION_OPS: ReadonlySet<string> = new Set([
  'all', 'and', 'or', 'exists', 'empty', ...CONDITION_TEXT_OPS, ...CONDITION_NUMERIC_OPS,
]);
const ACTION_OPS: ReadonlySet<string> = new Set([
  'set', 'replace', 'append', 'prepend', 'remove', 'clear', 'ai',
]);

function newId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID();
  return `r_${Math.random().toString(36).slice(2)}${Date.now().toString(36)}`;
}

export function newRule(name: string): Rule {
  return { id: newId(), name, isMasterRule: false, isActive: true, when: { op: 'all' }, then: [] };
}

function normalizeCondition(value: unknown): RuleCondition {
  if (typeof value !== 'object' || value === null) return { op: 'all' };
  const raw = value as Record<string, unknown>;
  const op = typeof raw.op === 'string' && CONDITION_OPS.has(raw.op) ? (raw.op as ConditionOp) : 'all';
  const cond: RuleCondition = { op };
  if (typeof raw.field === 'string') cond.field = raw.field;
  if (typeof raw.arg === 'string' || typeof raw.arg === 'number') cond.arg = raw.arg;
  if (typeof raw.arg2 === 'number') cond.arg2 = raw.arg2;
  if (typeof raw.caseSensitive === 'boolean') cond.caseSensitive = raw.caseSensitive;
  if (Array.isArray(raw.children)) cond.children = raw.children.map(normalizeCondition);
  return cond;
}

export function normalizeAction(value: unknown): RuleAction | null {
  if (typeof value !== 'object' || value === null) return null;
  const raw = value as Record<string, unknown>;
  if (typeof raw.op !== 'string' || !ACTION_OPS.has(raw.op)) return null;
  const op = raw.op as ActionOp;
  const isAi = op === 'ai';
  if (!isAi && (typeof raw.field !== 'string' || !raw.field)) return null;
  const action: RuleAction = {
    op,
    field: typeof raw.field === 'string' ? raw.field : '',
  };
  if (typeof raw.value === 'string') action.value = raw.value;
  if (typeof raw.find === 'string') action.find = raw.find;
  if (typeof raw.with === 'string') action.with = raw.with;
  if (typeof raw.caseSensitive === 'boolean') action.caseSensitive = raw.caseSensitive;
  if (isAi) {
    if (raw.promptSource === 'template' || raw.promptSource === 'custom') {
      action.promptSource = raw.promptSource;
    }
    if (typeof raw.taskType === 'string') action.taskType = raw.taskType;
    if (typeof raw.templateId === 'number') action.templateId = raw.templateId;
    if (typeof raw.system === 'string') action.system = raw.system;
    if (typeof raw.user === 'string') action.user = raw.user;
    if (Array.isArray(raw.variables)) {
      action.variables = raw.variables.filter((v): v is string => typeof v === 'string');
    }
  }
  return action;
}

export function normalizeConfig(value: unknown): RulesConfig {
  const rules: Rule[] = [];
  if (typeof value === 'object' && value !== null && Array.isArray((value as { rules?: unknown }).rules)) {
    for (const entry of (value as { rules: unknown[] }).rules) {
      if (typeof entry !== 'object' || entry === null) continue;
      const raw = entry as Record<string, unknown>;
      if (typeof raw.id !== 'string' || !raw.id) continue;
      if (typeof raw.name !== 'string' || !raw.name) continue;
      rules.push({
        id: raw.id,
        name: raw.name,
        isMasterRule: raw.isMasterRule === true,
        isActive: raw.isActive !== false,
        when: normalizeCondition(raw.when),
        then: Array.isArray(raw.then)
          ? raw.then.map(normalizeAction).filter((a): a is RuleAction => a !== null)
          : [],
      });
    }
  }
  return { rules };
}

export function rulesEqual(a: RulesConfig, b: RulesConfig): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

export function sortRulesPinned(rules: Rule[]): Rule[] {
  const masters = rules.filter((r) => r.isMasterRule);
  const others = rules.filter((r) => !r.isMasterRule);
  return [...masters, ...others];
}

export function enforcePinning(rules: Rule[]): Rule[] {
  return sortRulesPinned(rules);
}
