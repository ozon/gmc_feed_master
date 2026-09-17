import { beforeAll, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import i18n from '../../../i18n';
import { render } from '../../../test/render';
import { stubFetch } from '../../../test/fetch';
import { RuleAiActionEditor } from '../RuleAiActionEditor';
import type { RuleAction } from '../../../../../plugins/core/rules/frontend/ast';

beforeAll(async () => {
  await i18n.loadNamespaces(['rules', 'common']);
});

const options = [{ group: 'Field', items: [{ value: 'title', label: 'title' }] }];

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status, headers: { 'Content-Type': 'application/json' },
  });
}

it('lists templates in template mode', async () => {
  stubFetch((url) => {
    if (url.startsWith('/plugins/rules/ai/templates')) {
      return jsonResponse({ items: [
        { id: 5, name: 'T1', task_type: 'title_optimization', client_id: null, version: 1, is_active: true },
      ] });
    }
    return jsonResponse({});
  });
  const action: RuleAction = {
    op: 'ai', field: '', promptSource: 'template',
    taskType: 'title_optimization', templateId: 5,
  };
  render(
    <RuleAiActionEditor action={action} fieldOptions={options} feedSourceId={1} onChange={vi.fn()} />,
  );
  expect(await screen.findByText('T1')).toBeInTheDocument();
});

it('switching to custom emits a rule_value action', async () => {
  const user = userEvent.setup();
  stubFetch(() => jsonResponse({}));
  const onChange = vi.fn();
  const action: RuleAction = {
    op: 'ai', field: 'title', promptSource: 'template',
    taskType: 'title_optimization', templateId: 5,
  };
  render(
    <RuleAiActionEditor action={action} fieldOptions={options} feedSourceId={1} onChange={onChange} />,
  );
  await user.click(screen.getByTestId('ai-source'));
  await user.click(await screen.findByText('Custom'));
  const next = onChange.mock.calls.at(-1)?.[0] as RuleAction;
  expect(next.taskType).toBe('rule_value');
  expect(next.templateId).toBeUndefined();
});
