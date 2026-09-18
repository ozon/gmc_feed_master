import { beforeAll, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import i18n from '../../../i18n';
import { render } from '../../../test/render';
import { RuleEditor } from '../RuleEditor';
import type { GroupedFieldOptions } from '../../../api/fieldOptions';
import type { Rule, RuleAction } from '../../../../../plugins/core/rules/frontend/ast';

beforeAll(async () => {
  await i18n.loadNamespaces(['rules', 'common']);
});

const fieldOptions: GroupedFieldOptions = [
  { group: 'Field', items: [{ value: 'title', label: 'title' }] },
];

const noop = () => {};

function makeRule(then: RuleAction[]): Rule {
  return {
    id: 'r1',
    name: 'R',
    isMasterRule: false,
    isActive: true,
    when: { op: 'all' },
    // oxlint-disable-next-line unicorn/no-thenable -- rule AST field 'then' holds actions, not a Promise thenable
    then,
  };
}

it('selecting the AI op initializes a template action with defaults', async () => {
  const user = userEvent.setup();
  const onPatchThen = vi.fn<(then: RuleAction[]) => void>();
  render(
    <RuleEditor
      rule={makeRule([{ op: 'set', field: 'title', value: 'x' }])}
      fieldOptions={fieldOptions}
      feedSourceId={1}
      onPatch={noop}
      onPatchWhen={noop}
      onPatchThen={onPatchThen}
      onToggleMaster={noop}
      onToggleActive={noop}
      onDelete={noop}
      onRename={noop}
    />,
  );

  await user.click(screen.getByTestId('then-op-0'));
  await user.click(await screen.findByText('set with AI'));

  const next = onPatchThen.mock.calls.at(-1)?.[0] as RuleAction[];
  expect(next[0]).toMatchObject({
    op: 'ai',
    field: 'title',
    promptSource: 'template',
    taskType: 'title_optimization',
  });
  expect(next[0].promptSource).toBeDefined();
  expect(next[0].taskType).toBeDefined();
});
